import os
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile, File, Depends
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
from app.config import contracts_collection, UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_FILE_SIZE
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
    """Extract text from a PDF using PyMuPDF (fitz)."""
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from a DOCX file using python-docx."""
    try:
        import io
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        paragraphs.append(cell.text.strip())
        return "\n".join(paragraphs)
    except Exception:
        return ""


def _convert_pdf_to_docx(pdf_content: bytes) -> bytes | None:
    """Convert PDF bytes to DOCX using pdf2docx (pure Python, no external service needed)."""
    try:
        import tempfile
        from pdf2docx import Converter
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_tmp:
            pdf_tmp.write(pdf_content)
            pdf_tmp_path = pdf_tmp.name
        docx_tmp_path = pdf_tmp_path.replace(".pdf", ".docx")
        cv = Converter(pdf_tmp_path)
        cv.convert(docx_tmp_path, start=0, end=None)
        cv.close()
        with open(docx_tmp_path, "rb") as f:
            result = f.read()
        os.unlink(pdf_tmp_path)
        os.unlink(docx_tmp_path)
        return result
    except Exception:
        return None


@router.post("/upload")
async def upload_and_create_contract(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
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

    # For PDFs: convert to DOCX via pdf2docx so the document is fully editable.
    # The original PDF is kept as version 1; the DOCX becomes version 2 (working copy).
    pdf_original_stored = None
    if ext == ".pdf":
        docx_bytes = _convert_pdf_to_docx(content)
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
        # PDF was converted to DOCX — extract from the original PDF
        extracted_text = _extract_text_from_pdf(open(os.path.join(UPLOAD_DIR, pdf_original_stored), "rb").read())
    elif ext == ".docx":
        extracted_text = _extract_text_from_docx(content)
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
        "start_date": None,
        "end_date": None,
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

    # Trigger AI analysis in the background to extract dates, parties, type, value
    if extracted_text and background_tasks is not None:
        from app.services.ai_service import analyze_contract_by_id
        background_tasks.add_task(analyze_contract_by_id, contract_doc["id"])

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