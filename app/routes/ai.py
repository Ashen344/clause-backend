import io
import json
import os

from fastapi import APIRouter, Form, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
from app.middleware.auth import get_current_user, get_optional_user
from app.services.ai_service import (
    analyze_contract_text,
    analyze_contract_by_id,
    generate_contract_draft,
    ai_chat,
    detect_conflicts,
    scan_contract_against_existing,
    embed_and_analyze,
    bulk_embed_contracts,
)

router = APIRouter(prefix="/api/ai", tags=["AI Analysis"])


class AnalyzeTextRequest(BaseModel):
    text: str


class GenerateDraftRequest(BaseModel):
    contract_type: str
    parties: Optional[List[dict]] = []
    key_terms: Optional[dict] = {}


class ConflictDetectionRequest(BaseModel):
    contract_ids: List[str]


class ChatHistoryMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    contract_id: Optional[str] = None
    question: str
    history: Optional[List[ChatHistoryMessage]] = []
    mode: Optional[str] = "general"


class EmbedAndAnalyzeRequest(BaseModel):
    text: str
    file_name: str = "upload"
    question: str = "Summarize the key information in this document."
    session_id: Optional[str] = None


@router.post("/analyze/text")
async def analyze_text(request: AnalyzeTextRequest):
    """Analyze raw contract text with AI."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Contract text cannot be empty")

    result = await analyze_contract_text(request.text)
    return result


@router.post("/analyze/{contract_id}")
async def analyze_contract(contract_id: str):
    """Run AI analysis on a contract stored in the database."""
    result = await analyze_contract_by_id(contract_id)
    if not result:
        raise HTTPException(status_code=404, detail="Contract not found")
    return result


@router.post("/generate-draft")
async def generate_draft(request: GenerateDraftRequest):
    """Generate a contract draft using AI."""
    result = await generate_contract_draft(
        contract_type=request.contract_type,
        parties=request.parties,
        key_terms=request.key_terms,
    )
    return result


@router.post("/conflicts")
async def detect_contract_conflicts(request: ConflictDetectionRequest):
    """Detect conflicting clauses across multiple contracts."""
    if len(request.contract_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 contract IDs are required")
    if len(request.contract_ids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 contracts can be compared at once")

    result = await detect_conflicts(request.contract_ids)
    return result


@router.post("/conflicts/scan/{contract_id}")
async def scan_conflicts_for_contract(contract_id: str):
    """Scan a newly uploaded contract against all existing contracts for conflicts.
    Returns zero conflicts (clean) if no other contracts exist yet."""
    result = await scan_contract_against_existing(contract_id)
    return result


@router.post("/chat")
async def chat_with_ai(request: ChatRequest):
    """Ask AI a question about a contract or general legal question."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = await ai_chat(
        contract_id=request.contract_id or "",
        question=request.question,
    )
    return result


def _extract_text(content: bytes, ext: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT bytes."""
    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=content, filetype="pdf")
            return "\n\n".join(page.get_text() for page in doc)
        except Exception:
            return ""
    if ext in (".txt", ".md", ".rtf"):
        return content.decode("utf-8", errors="replace")
    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return ""
    return ""


@router.post("/chat-file")
async def chat_with_file(
    question: str = Form(...),
    file: UploadFile = File(...),
    history: str = Form("[]"),
):
    """Chat with an uploaded document (PDF/DOCX/TXT) as context."""
    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    ext = os.path.splitext(file.filename or "")[1].lower()
    allowed = {".pdf", ".txt", ".md", ".rtf", ".docx"}
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed))}",
        )

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds 20 MB limit")

    text = _extract_text(content, ext)
    if not text.strip():
        raise HTTPException(status_code=422, detail="Could not extract text from file")

    try:
        json.loads(history)
    except ValueError:
        history = "[]"

    result = await ai_chat(
        contract_id="",
        question=question,
        contract_text=text[:12000],
    )
    result["file_name"] = file.filename
    return result


@router.post("/embed-and-analyze")
async def embed_and_analyze_document(request: EmbedAndAnalyzeRequest):
    """Upload a document's text for embedding into the knowledge base and
    AI-powered analysis.

    The agent service will:
    1. Chunk the text and embed it into Elasticsearch
    2. Search the KB for relevant context
    3. Use Ollama + Gemini to produce a structured analysis
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Document text cannot be empty")

    result = await embed_and_analyze(
        text=request.text,
        file_name=request.file_name,
        question=request.question,
        session_id=request.session_id,
    )
    return result


class BulkEmbedRequest(BaseModel):
    force: bool = False
    batch_size: int = 20


@router.post("/embed-all")
async def embed_all_contracts(
    request: BulkEmbedRequest,
    current_user: dict = Depends(get_current_user),
):
    """Embed all contracts from MongoDB into the Elasticsearch knowledge base.

    Skips contracts already marked as embedded unless force=True.
    Returns a summary with succeeded/skipped/failed counts.
    """
    result = await bulk_embed_contracts(
        force=request.force,
        batch_size=max(1, min(request.batch_size, 50)),
    )
    return result
