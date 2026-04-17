import os
import uuid
import logging

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
from app.middleware.auth import get_current_user, get_optional_user
from app.services.ai_service import (
    analyze_contract_text,
    analyze_contract_by_id,
    generate_contract_draft,
    ai_chat,
    embed_and_analyze,
    detect_conflicts,
)
from app.services.document_parser import (
    extract_text,
    SUPPORTED_EXTENSIONS,
)
from app.services.audit_service import create_audit_log
from app.models.audit_log import AuditAction

logger = logging.getLogger(__name__)

# Uploaded chat documents are kept on disk; directory is configurable via env.
CHAT_UPLOAD_DIR = os.environ.get(
    "CHAT_UPLOAD_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads", "chat"),
)
os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/api/ai", tags=["AI Analysis"])


class AnalyzeTextRequest(BaseModel):
    text: str


class GenerateDraftRequest(BaseModel):
    contract_type: str
    parties: Optional[List[dict]] = []
    key_terms: Optional[dict] = {}


class ConflictDetectionRequest(BaseModel):
    contract_ids: List[str]


class ChatRequest(BaseModel):
    contract_id: Optional[str] = None
    contract_text: Optional[str] = None
    question: str
    session_id: Optional[str] = None


@router.post("/analyze/text")
async def analyze_text(
    request: AnalyzeTextRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Analyze raw contract text with AI."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Contract text cannot be empty")

    result = await analyze_contract_text(request.text)

    create_audit_log(
        action=AuditAction.ai_analysis,
        resource_type="contract_text",
        resource_id="inline",
        user_id=current_user["user_id"] if current_user else "anonymous",
        user_email=current_user.get("email") if current_user else None,
        details="Ran AI text analysis",
    )

    return result


@router.post("/analyze/{contract_id}")
async def analyze_contract(
    contract_id: str,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Run AI analysis on a contract stored in the database."""
    result = await analyze_contract_by_id(contract_id)
    if not result:
        raise HTTPException(status_code=404, detail="Contract not found")

    create_audit_log(
        action=AuditAction.ai_analysis,
        resource_type="contract",
        resource_id=contract_id,
        user_id=current_user["user_id"] if current_user else "anonymous",
        user_email=current_user.get("email") if current_user else None,
        details=f"Ran AI analysis on contract {contract_id}",
    )

    return result


@router.post("/generate-draft")
async def generate_draft(
    request: GenerateDraftRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Generate a contract draft using AI."""
    result = await generate_contract_draft(
        contract_type=request.contract_type,
        parties=request.parties,
        key_terms=request.key_terms,
    )

    create_audit_log(
        action=AuditAction.ai_analysis,
        resource_type="draft",
        resource_id="generated",
        user_id=current_user["user_id"] if current_user else "anonymous",
        user_email=current_user.get("email") if current_user else None,
        details=f"Generated {request.contract_type} draft",
    )

    return result


@router.post("/conflicts")
async def detect_contract_conflicts(
    request: ConflictDetectionRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Detect conflicting clauses across multiple contracts."""
    if len(request.contract_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 contract IDs are required")
    if len(request.contract_ids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 contracts can be compared at once")

    result = await detect_conflicts(request.contract_ids)

    create_audit_log(
        action=AuditAction.ai_analysis,
        resource_type="conflict_analysis",
        resource_id="batch",
        user_id=current_user["user_id"] if current_user else "anonymous",
        user_email=current_user.get("email") if current_user else None,
        details=f"Analyzed {len(request.contract_ids)} contracts for conflicts",
    )

    return result


@router.post("/chat")
async def chat_with_ai(
    request: ChatRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Ask AI a question about a contract or general legal question."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = await ai_chat(
        contract_id=request.contract_id or "",
        question=request.question,
        contract_text=request.contract_text,
        session_id=request.session_id,
    )

    create_audit_log(
        action=AuditAction.ai_analysis,
        resource_type="ai_chat",
        resource_id=request.contract_id or "general",
        user_id=current_user["user_id"] if current_user else "anonymous",
        user_email=current_user.get("email") if current_user else None,
        details="AI chat query",
    )

    return result


MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/chat/upload")
async def chat_with_document(
    file: UploadFile = File(...),
    question: str = Form(...),
    session_id: Optional[str] = Form(None),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Upload a document (PDF, DOCX, TXT, etc.), parse and chunk it,
    extract key contract information, and send it to the AI for analysis.
    """
    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Validate file extension
    original_name = file.filename or "upload"
    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not supported. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    # Read and size-check
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 10 MB limit")

    # Persist the upload so it can be referenced or re-processed later.
    safe_basename = os.path.basename(original_name)
    saved_path = os.path.join(CHAT_UPLOAD_DIR, f"{uuid.uuid4().hex}_{safe_basename}")
    with open(saved_path, "wb") as fh:
        fh.write(content)

    try:
        # Extract text from the saved file
        raw_text = extract_text(saved_path)
        if not raw_text or not raw_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract any text from the uploaded file.",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse the document: {e}",
        )

    logger.info("chat/upload persisted file: %s", saved_path)

    # Send to the AI agent service for embedding + KB indexing + analysis
    result = await embed_and_analyze(
        document_text=raw_text,
        file_name=original_name,
        question=question,
        session_id=session_id,
    )

    create_audit_log(
        action=AuditAction.ai_analysis,
        resource_type="ai_chat_document",
        resource_id="upload",
        user_id=current_user["user_id"] if current_user else "anonymous",
        user_email=current_user.get("email") if current_user else None,
        details=f"AI chat with uploaded document: {original_name} saved_at={saved_path}",
    )

    return result
