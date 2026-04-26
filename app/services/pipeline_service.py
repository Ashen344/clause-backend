"""
Contract Pipeline Service
Handles the full flow: Upload -> Extract Text -> AI Analyze -> Conflict Detection -> Ready for Approval or Edit
"""

import io
import os
import uuid
from datetime import datetime
from typing import Optional, List

from bson import ObjectId

from app.config import contracts_collection, UPLOAD_DIR
from app.services.ai_service import (
    analyze_contract_text,
    detect_conflicts,
    _build_contract_text,
)

def extract_text_from_file(file_bytes: bytes, file_type: str) -> str:
    """Extract plain text from uploaded file bytes based on file type."""
    try:
        if file_type == ".pdf":
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            return "\n\n".join(p.extract_text() or "" for p in reader.pages).strip()
        if file_type in (".txt", ".rtf"):
            return file_bytes.decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def _get_mime_type(ext: str) -> str:
    return {
        ".pdf":  "application/pdf",
        ".doc":  "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt":  "text/plain",
        ".rtf":  "application/rtf",
        ".odt":  "application/vnd.oasis.opendocument.text",
    }.get(ext, "application/octet-stream")


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
      1. Store document to the local uploads directory
      2. Extract text from the document
      3. Run AI analysis (risk scoring, clause extraction, etc.)
      4. Run conflict detection against other contracts (optional)
      5. Return a result dict with pipeline_status + all findings
    """

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        return {"error": "Contract not found", "pipeline_status": "error"}

    # ── Step 1: Store to local filesystem ───────────────────────────────────
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored_filename = f"{uuid.uuid4().hex}{file_type}"
    file_path = os.path.join(UPLOAD_DIR, stored_filename)
    with open(file_path, "wb") as fh:
        fh.write(file_bytes)

    current_version = contract.get("current_version", 0)
    new_version = current_version + 1

    version_entry = {
        "version_number": new_version,
        "file_url": stored_filename,
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
                "file_url": stored_filename,
                "current_version": new_version,
                "updated_at": datetime.utcnow(),
            },
        },
    )

    # ── Step 2: Extract text ─────────────────────────────────────────────────
    extracted_text = extract_text_from_file(file_bytes, file_type)

    if extracted_text:
        contracts_collection.update_one(
            {"_id": ObjectId(contract_id)},
            {"$set": {"extracted_text": extracted_text}},
        )

    # ── Step 3: AI analysis ──────────────────────────────────────────────────
    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    full_text = _build_contract_text(contract)
    analysis = await analyze_contract_text(full_text)

    ai_analysis = {
        "summary":           analysis.get("summary"),
        "extracted_clauses": analysis.get("extracted_clauses"),
        "key_information":   analysis.get("key_information"),
        "risk_score":        analysis.get("risk_score"),
        "risk_level":        analysis.get("risk_level"),
        "risk_factors":      analysis.get("risk_factors"),
        "recommendations":   analysis.get("recommendations"),
        "analyzed_at":       datetime.utcnow(),
    }

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {"ai_analysis": ai_analysis, "updated_at": datetime.utcnow()}},
    )

    # ── Step 4: Conflict detection (optional) ───────────────────────────────
    conflicts_result = None
    if compare_contract_ids:
        all_ids = list(set([contract_id] + compare_contract_ids))
        if len(all_ids) >= 2:
            conflicts_result = await detect_conflicts(all_ids)

    # ── Step 5: Evaluate issues ──────────────────────────────────────────────
    issues: list = []

    risk_level = analysis.get("risk_level", "low")
    risk_score = analysis.get("risk_score") or 0
    if risk_level == "high" or risk_score >= 70:
        issues.append({
            "type":     "high_risk",
            "severity": "high",
            "message":  f"Contract has a high risk score ({risk_score}/100)",
            "details":  analysis.get("risk_factors", []),
        })

    risk_factors = analysis.get("risk_factors", [])
    if len(risk_factors) >= 3:
        issues.append({
            "type":     "multiple_risk_factors",
            "severity": "medium",
            "message":  f"{len(risk_factors)} risk factors identified",
            "details":  risk_factors,
        })

    if conflicts_result and conflicts_result.get("total_conflicts", 0) > 0:
        high_conflicts = [c for c in conflicts_result.get("conflicts", []) if c.get("severity") == "high"]
        issues.append({
            "type":     "conflicts_detected",
            "severity": "high" if high_conflicts else "medium",
            "message":  f"{conflicts_result['total_conflicts']} conflict(s) found with other contracts",
            "details":  conflicts_result.get("conflicts", []),
        })

    pipeline_status = "issues_found" if issues else "ready_for_approval"
    new_stage = "review" if issues else "approval"

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {"workflow_stage": new_stage, "updated_at": datetime.utcnow()}},
    )

    return {
        "pipeline_status": pipeline_status,
        "contract_id":     contract_id,
        "document": {
            "version":              new_version,
            "filename":             filename,
            "file_size":            len(file_bytes),
            "file_type":            file_type,
            "extracted_text_length": len(extracted_text),
        },
        "analysis": {
            "summary":           analysis.get("summary"),
            "risk_score":        analysis.get("risk_score"),
            "risk_level":        analysis.get("risk_level"),
            "risk_factors":      analysis.get("risk_factors", []),
            "extracted_clauses": analysis.get("extracted_clauses", []),
            "recommendations":   analysis.get("recommendations", []),
        },
        "conflicts":    conflicts_result or {"total_conflicts": 0, "conflicts": []},
        "issues":       issues,
        "issues_count": len(issues),
        "next_action":  "edit_and_resubmit" if issues else "send_for_approval",
        "workflow_stage": new_stage,
    }
