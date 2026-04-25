from fastapi import APIRouter, HTTPException, Depends
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

    history = [{"role": m.role, "content": m.content} for m in (request.history or [])]

    result = await ai_chat(
        contract_id=request.contract_id or "",
        question=request.question,
        history=history,
    )
    return result
