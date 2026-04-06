"""
Pipeline Route
Unified endpoint for the contract processing flow:
Upload -> Analyze -> Conflict Detection -> Approve or Edit
"""

import os
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Query
from bson import ObjectId
from app.middleware.auth import get_current_user, require_role
from app.services.pipeline_service import run_pipeline
from app.services.approval_service import create_approval
from app.models.approval import ApprovalCreate
from app.config import contracts_collection

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline"])

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/process/{contract_id}")
async def process_contract(
    contract_id: str,
    file: UploadFile = File(...),
    change_notes: str = Form(default=""),
    compare_contract_ids: str = Form(default=""),
    current_user: dict = Depends(get_current_user),
):
    """
    Full contract processing pipeline.

    1. Uploads the document (stored in MongoDB GridFS)
    2. Extracts text from the PDF/document
    3. Runs AI analysis (risk scoring, clause extraction, recommendations)
    4. Runs conflict detection against specified contracts (optional)
    5. Returns pipeline result:
       - "ready_for_approval": No issues found, contract can be sent for approval
       - "issues_found": Issues detected, user should edit and resubmit

    Form fields:
    - file: The contract document (PDF, DOC, DOCX, TXT, RTF, ODT)
    - change_notes: Optional notes about this upload
    - compare_contract_ids: Comma-separated contract IDs for conflict detection
    """
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Validate file
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 20MB limit")

    # Parse comparison contract IDs
    compare_ids = []
    if compare_contract_ids.strip():
        compare_ids = [cid.strip() for cid in compare_contract_ids.split(",") if cid.strip()]

    # Run the full pipeline
    result = await run_pipeline(
        contract_id=contract_id,
        file_bytes=content,
        filename=file.filename or "document",
        file_type=ext,
        user_id=current_user["user_id"],
        change_notes=change_notes,
        compare_contract_ids=compare_ids if compare_ids else None,
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/send-for-approval/{contract_id}")
async def send_for_approval(
    contract_id: str,
    approver_ids: List[str] = Query(..., description="List of approver user IDs"),
    current_user: dict = Depends(get_current_user),
):
    """
    Send a contract for approval after pipeline passes.
    Creates an approval request and advances workflow to 'approval' stage.
    Only works if the contract has been analyzed and has no blocking issues.
    """
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Check the contract has been analyzed
    if not contract.get("ai_analysis"):
        raise HTTPException(
            status_code=400,
            detail="Contract must be analyzed before sending for approval. Use the pipeline endpoint first.",
        )

    if not approver_ids:
        raise HTTPException(status_code=400, detail="At least one approver is required")

    # Create the approval request
    approval_data = ApprovalCreate(
        contract_id=contract_id,
        approval_type=contract.get("approval_type", "all_required"),
        approver_ids=approver_ids,
    )

    approval = await create_approval(approval_data, user_id=current_user["user_id"])

    # Update contract workflow stage to approval
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {
            "workflow_stage": "approval",
            "status": "active",
            "updated_at": datetime.utcnow(),
        }},
    )

    return {
        "message": "Contract sent for approval successfully",
        "contract_id": contract_id,
        "approval_id": approval.get("id"),
        "approvers": approver_ids,
        "workflow_stage": "approval",
    }


@router.get("/status/{contract_id}")
async def get_pipeline_status(
    contract_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get the current pipeline/analysis status of a contract."""
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    ai_analysis = contract.get("ai_analysis")
    has_document = bool(contract.get("versions"))
    has_analysis = bool(ai_analysis)

    risk_level = ai_analysis.get("risk_level") if ai_analysis else None
    risk_score = ai_analysis.get("risk_score") if ai_analysis else None

    has_issues = False
    if has_analysis:
        has_issues = (
            risk_level == "high"
            or (risk_score is not None and risk_score >= 70)
            or len(ai_analysis.get("risk_factors", [])) >= 3
        )

    return {
        "contract_id": contract_id,
        "title": contract.get("title"),
        "workflow_stage": contract.get("workflow_stage"),
        "status": contract.get("status"),
        "has_document": has_document,
        "has_analysis": has_analysis,
        "current_version": contract.get("current_version", 0),
        "analysis_summary": ai_analysis.get("summary") if ai_analysis else None,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "has_issues": has_issues,
        "next_action": "edit_and_resubmit" if has_issues else (
            "send_for_approval" if has_analysis else "upload_document"
        ),
    }
