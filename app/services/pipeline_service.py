"""
Contract Pipeline Service
Handles the full flow: Upload -> Extract Text -> AI Analyze -> Conflict Detection -> Ready for Approval or Edit
"""

import os
from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from app.config import contracts_collection, fs
from app.services.ai_service import (
    analyze_contract_text,
    extract_text_from_file,
    get_document_text_from_gridfs,
    detect_conflicts,
    _build_contract_text,
)


async def run_pipeline(
    contract_id: str,
    file_bytes: bytes,
    filename: str,
    file_type: str,
    user_id: str,
    change_notes: str = "",
    compare_contract_ids: Optional[List[str]] = None,
) -> dict:
    """
    Run the full contract processing pipeline:
    1. Store document in GridFS
    2. Extract text from the document
    3. Run AI analysis (risk scoring, clause extraction, etc.)
    4. Run conflict detection against other contracts (if IDs provided)
    5. Return results with a status indicating if issues were found

    Returns a dict with:
    - pipeline_status: "issues_found" or "ready_for_approval"
    - analysis: AI analysis results
    - conflicts: conflict detection results (if applicable)
    - document: upload metadata
    - issues_summary: list of issues found (if any)
    """

    # --- Step 1: Store document in GridFS ---
    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        return {"error": "Contract not found", "pipeline_status": "error"}

    gridfs_id = fs.put(
        file_bytes,
        filename=filename,
        content_type=_get_mime_type(file_type),
        contract_id=contract_id,
        uploaded_by=user_id,
        uploaded_at=datetime.utcnow(),
    )

    current_version = contract.get("current_version", 0)
    new_version = current_version + 1

    version_entry = {
        "version_number": new_version,
        "gridfs_id": str(gridfs_id),
        "original_filename": filename,
        "file_size": len(file_bytes),
        "file_type": file_type,
        "uploaded_by": user_id,
        "uploaded_at": datetime.utcnow(),
        "change_notes": change_notes or None,
    }

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {
            "$push": {"versions": version_entry},
            "$set": {
                "current_version": new_version,
                "current_gridfs_id": str(gridfs_id),
                "updated_at": datetime.utcnow(),
            },
        },
    )

    # --- Step 2: Extract text from the document ---
    extracted_text = extract_text_from_file(file_bytes, file_type)

    # Also build context from contract metadata
    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    full_text = _build_contract_text(contract)

    # --- Step 3: Run AI analysis ---
    analysis = await analyze_contract_text(full_text)

    # Store analysis on the contract
    ai_analysis = {
        "summary": analysis.get("summary"),
        "extracted_clauses": analysis.get("extracted_clauses"),
        "key_information": analysis.get("key_information"),
        "risk_score": analysis.get("risk_score"),
        "risk_level": analysis.get("risk_level"),
        "risk_factors": analysis.get("risk_factors"),
        "recommendations": analysis.get("recommendations"),
        "analyzed_at": datetime.utcnow(),
    }

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {
            "ai_analysis": ai_analysis,
            "updated_at": datetime.utcnow(),
        }},
    )

    # --- Step 4: Conflict detection (optional) ---
    conflicts_result = None
    if compare_contract_ids and len(compare_contract_ids) >= 1:
        # Include current contract in the comparison
        all_ids = list(set([contract_id] + compare_contract_ids))
        if len(all_ids) >= 2:
            conflicts_result = await detect_conflicts(all_ids)

    # --- Step 5: Determine pipeline status ---
    issues = []

    # Check risk level
    risk_level = analysis.get("risk_level", "low")
    risk_score = analysis.get("risk_score", 0)
    if risk_level == "high" or (risk_score and risk_score >= 70):
        issues.append({
            "type": "high_risk",
            "severity": "high",
            "message": f"Contract has a high risk score ({risk_score}/100)",
            "details": analysis.get("risk_factors", []),
        })

    # Check for risk factors
    risk_factors = analysis.get("risk_factors", [])
    if len(risk_factors) >= 3:
        issues.append({
            "type": "multiple_risk_factors",
            "severity": "medium",
            "message": f"{len(risk_factors)} risk factors identified",
            "details": risk_factors,
        })

    # Check conflicts
    if conflicts_result and conflicts_result.get("total_conflicts", 0) > 0:
        high_conflicts = [
            c for c in conflicts_result.get("conflicts", [])
            if c.get("severity") == "high"
        ]
        issues.append({
            "type": "conflicts_detected",
            "severity": "high" if high_conflicts else "medium",
            "message": f"{conflicts_result['total_conflicts']} conflict(s) found with other contracts",
            "details": conflicts_result.get("conflicts", []),
        })

    # Check recommendations
    recommendations = analysis.get("recommendations", [])

    pipeline_status = "issues_found" if issues else "ready_for_approval"

    # Update contract workflow stage based on result
    new_stage = "review" if issues else "approval"
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {
            "workflow_stage": new_stage,
            "updated_at": datetime.utcnow(),
        }},
    )

    return {
        "pipeline_status": pipeline_status,
        "contract_id": contract_id,
        "document": {
            "version": new_version,
            "filename": filename,
            "file_size": len(file_bytes),
            "file_type": file_type,
            "gridfs_id": str(gridfs_id),
            "extracted_text_length": len(extracted_text),
        },
        "analysis": {
            "summary": analysis.get("summary"),
            "risk_score": analysis.get("risk_score"),
            "risk_level": analysis.get("risk_level"),
            "risk_factors": analysis.get("risk_factors", []),
            "extracted_clauses": analysis.get("extracted_clauses", []),
            "recommendations": recommendations,
        },
        "conflicts": conflicts_result if conflicts_result else {"total_conflicts": 0, "conflicts": []},
        "issues": issues,
        "issues_count": len(issues),
        "next_action": "edit_and_resubmit" if issues else "send_for_approval",
        "workflow_stage": new_stage,
    }


def _get_mime_type(ext: str) -> str:
    mime_map = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".rtf": "application/rtf",
        ".odt": "application/vnd.oasis.opendocument.text",
    }
    return mime_map.get(ext, "application/octet-stream")
