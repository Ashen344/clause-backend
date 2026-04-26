import io
import os
import uuid
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Depends
from typing import Optional
from app.models.contract import (
    ContractCreate,
    ContractUpdate,
    ContractResponse,
    ContractFilter,
    ContractType,
    ContractStatus,
    WorkflowStage,
    RiskLevel,
)
from app.services.contract_service import (
    create_contract,
    get_contract,
    get_contracts,
    update_contract,
    delete_contract,
    update_workflow_stage,
    get_dashboard_stats,
)
from app.config import contracts_collection, UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_FILE_SIZE, COLLABORA_INTERNAL_URL
from app.middleware.auth import get_current_user_with_role
from app.services.audit_service import create_audit_log
from app.models.audit_log import AuditAction

router = APIRouter(prefix="/api/contracts", tags=["Contracts"])


@router.post("/", response_model=None)
async def create_new_contract(
    contract: ContractCreate,
    current_user: dict = Depends(get_current_user_with_role),
):
    result = await create_contract(contract, user_id=current_user["user_id"])
    create_audit_log(
        action=AuditAction.create,
        resource_type="contract",
        resource_id=result.get("id", ""),
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Contract created: {contract.title}",
    )
    return result


@router.get("/")
async def list_contracts(
    search: Optional[str] = Query(None, description="Search by title"),
    contract_type: Optional[ContractType] = Query(None),
    status: Optional[ContractStatus] = Query(None),
    workflow_stage: Optional[WorkflowStage] = Query(None),
    risk_level: Optional[RiskLevel] = Query(None),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=500, description="Items per page"),
    current_user: dict = Depends(get_current_user_with_role),
):
    is_admin = current_user.get("role") in ("admin", "manager")
    filters = ContractFilter(
        search=search,
        contract_type=contract_type,
        status=status,
        workflow_stage=workflow_stage,
        risk_level=risk_level,
        page=page,
        per_page=per_page,
    )
    return await get_contracts(filters, user_id=current_user["user_id"], is_admin=is_admin)


# Must be above /{contract_id} or FastAPI matches "dashboard" as an ID
@router.get("/dashboard")
async def dashboard_statistics():
    return await get_dashboard_stats()


# Must be above /{contract_id} or FastAPI matches "upload" as an ID
def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF using PyPDF2."""
    try:
        import io
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        pages_text = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        return "\n\n".join(pages_text)
    except Exception:
        return ""


async def _convert_pdf_to_docx(pdf_content: bytes) -> bytes | None:
    """Convert PDF bytes to DOCX using Collabora's built-in conversion API."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{COLLABORA_INTERNAL_URL}/cool/convert-to/docx",
                files={"data": ("document.pdf", io.BytesIO(pdf_content), "application/pdf")},
            )
            if resp.status_code == 200:
                return resp.content
    except Exception:
        pass
    return None


@router.post("/upload")
async def upload_and_create_contract(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user_with_role),
):
    """Upload a document (PDF/DOCX/TXT) and create a new draft contract from it."""
    # Validate extension
    original_name = file.filename or "untitled"
    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 20 MB limit")

    # Save to disk
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_id = uuid.uuid4().hex
    stored_filename = f"{file_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_filename)
    with open(file_path, "wb") as f:
        f.write(content)

    # For PDFs: convert to DOCX via Collabora so the document is fully editable.
    # The original PDF is kept as version 1; the DOCX becomes version 2 (working copy).
    pdf_original_stored = None
    if ext == ".pdf":
        docx_bytes = await _convert_pdf_to_docx(content)
        if docx_bytes:
            pdf_original_stored = stored_filename
            docx_id = uuid.uuid4().hex
            stored_filename = f"{docx_id}.docx"
            docx_path = os.path.join(UPLOAD_DIR, stored_filename)
            with open(docx_path, "wb") as f:
                f.write(docx_bytes)
            content = docx_bytes
            ext = ".docx"
            original_name = os.path.splitext(original_name)[0] + ".docx"

    # Extract text for downstream AI analysis / display
    extracted_text = ""
    if pdf_original_stored:
        extracted_text = _extract_text_from_pdf(open(os.path.join(UPLOAD_DIR, pdf_original_stored), "rb").read())
    elif ext == ".txt":
        try:
            extracted_text = content.decode("utf-8", errors="replace")
        except Exception:
            extracted_text = ""

    # Derive a title from the filename (strip extension, replace underscores)
    title = os.path.splitext(original_name)[0].replace("_", " ").replace("-", " ").strip()
    if not title:
        title = "Uploaded Contract"

    now = datetime.utcnow()
    user_id = current_user["user_id"]

    version_entry = {
        "version_number": 1,
        "file_url": stored_filename,
        "original_filename": original_name,
        "file_size": len(content),
        "file_type": ext,
        "uploaded_by": user_id,
        "uploaded_at": now,
        "change_notes": "Initial upload",
    }

    contract_doc = {
        "title": title,
        "contract_type": "other",
        "description": f"Created from uploaded file: {original_name}",
        "parties": [],
        "start_date": now,
        "end_date": now + timedelta(days=365),
        "value": None,
        "payment_terms": None,
        "status": "draft",
        "workflow_stage": "request",
        "approval_type": "all_required",
        "workflow_trigger": "creation",
        "file_url": stored_filename,
        "versions": [version_entry],
        "current_version": 1,
        "ai_analysis": None,
        "created_by": user_id,
        "organization_id": None,
        "tags": ["uploaded"],
        "template_id": None,
        "created_at": now,
        "updated_at": now,
    }

    if extracted_text:
        contract_doc["extracted_text"] = extracted_text

    result = contracts_collection.insert_one(contract_doc)
    contract_doc["id"] = str(result.inserted_id)
    del contract_doc["_id"]

    create_audit_log(
        action=AuditAction.file_upload,
        resource_type="contract",
        resource_id=contract_doc["id"],
        user_id=user_id,
        user_email=current_user.get("email"),
        details=f"Document uploaded: {original_name}",
    )

    return {
        "id": contract_doc["id"],
        "contract": contract_doc,
        "message": "Contract created from uploaded document",
        "extracted_text": extracted_text[:2000] if extracted_text else "",
    }


@router.get("/{contract_id}")
async def get_single_contract(
    contract_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    is_admin = current_user.get("role") in ("admin", "manager")
    contract = await get_contract(contract_id, user_id=current_user["user_id"], is_admin=is_admin)

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    return contract


@router.put("/{contract_id}")
async def update_existing_contract(
    contract_id: str,
    update_data: ContractUpdate,
    current_user: dict = Depends(get_current_user_with_role),
):
    is_admin = current_user.get("role") in ("admin", "manager")
    existing = await get_contract(contract_id, user_id=current_user["user_id"], is_admin=is_admin)
    if not existing:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract = await update_contract(contract_id, update_data)
    create_audit_log(
        action=AuditAction.update,
        resource_type="contract",
        resource_id=contract_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Contract updated: {existing.get('title', contract_id)}",
    )
    return contract


@router.delete("/{contract_id}")
async def delete_existing_contract(
    contract_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    is_admin = current_user.get("role") in ("admin", "manager")
    existing = await get_contract(contract_id, user_id=current_user["user_id"], is_admin=is_admin)
    if not existing:
        raise HTTPException(status_code=404, detail="Contract not found")

    await delete_contract(contract_id)
    create_audit_log(
        action=AuditAction.delete,
        resource_type="contract",
        resource_id=contract_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Contract deleted: {existing.get('title', contract_id)}",
    )
    return {"message": "Contract deleted successfully"}


@router.patch("/{contract_id}/workflow")
async def change_workflow_stage(
    contract_id: str,
    stage: WorkflowStage,
    current_user: dict = Depends(get_current_user_with_role),
):
    is_admin = current_user.get("role") in ("admin", "manager")
    existing = await get_contract(contract_id, user_id=current_user["user_id"], is_admin=is_admin)
    if not existing:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract = await update_workflow_stage(contract_id, stage.value)
    create_audit_log(
        action=AuditAction.status_change,
        resource_type="contract",
        resource_id=contract_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Workflow stage changed to: {stage.value} on contract: {existing.get('title', contract_id)}",
    )
    return contract