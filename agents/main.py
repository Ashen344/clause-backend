"""
main.py — FastAPI gateway for the CLM Agent service.

Endpoints:
    POST /generate  — Document Architect: generate a contract from a template
    POST /analyse   — Clause Analyst: answer questions about contract clauses
    GET  /health    — Health check
    GET  /templates — List available contract templates and their fields
"""

import os
import re
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Ollama summarizer — reuses the Clause Analyst agent's guardrails so the
# summary that Gemini consumes is already shaped by the same rules the
# analyst enforces (SUMMARY / RISKS / COMPARISON / RECOMMENDATION, plain
# language, base output on retrieved/provided text).
_OLLAMA_SUMMARY_SYSTEM = (
    "You are the Clause Analyst summarizer for a Contract Lifecycle "
    "Management (CLM) platform. Produce a dense, factual pre-analysis "
    "summary of the uploaded contract that a downstream model (Gemini) "
    "will use to answer user questions.\n\n"
    "Guardrails (apply strictly):\n"
    "- Base every statement on the provided document text. Do not invent "
    "  facts, parties, dates, numbers, or clause language.\n"
    "- If a detail is not present, write 'not specified'. Never guess.\n"
    "- Preserve exact names, dates, monetary amounts, durations, and "
    "  governing-law references verbatim.\n"
    "- Use plain, professional English. Avoid legal jargon where plain "
    "  language suffices. Be concise.\n"
    "- Do not provide legal advice or recommendations to the end user; "
    "  flag risks factually.\n\n"
    "Output format (use these exact headings):\n"
    "PARTIES: ...\n"
    "CONTRACT TYPE: ...\n"
    "EFFECTIVE DATES / DURATION: ...\n"
    "KEY OBLIGATIONS: bullet list\n"
    "PAYMENT TERMS: ...\n"
    "TERMINATION CONDITIONS: ...\n"
    "GOVERNING LAW / JURISDICTION: ...\n"
    "NOTABLE CLAUSES: bullet list (verbatim snippets where useful)\n"
    "RISK FLAGS: bullet list of concerning terms, unusual language, or "
    "missing protections (factual, no advice)."
)


def _summarize_with_ollama(text: str, file_name: str | None = None) -> str | None:
    """Summarize an uploaded document via Ollama, applying the Clause
    Analyst guardrails. The returned summary is passed to Gemini as
    compressed, structured context for final analysis.

    Returns the summary string, or None if Ollama is unavailable or fails.
    """
    from tools import (LOCAL_MODEL_ENABLED, is_ollama_available,
                       generate_text_local)

    if not (LOCAL_MODEL_ENABLED and is_ollama_available()):
        return None

    snippet = text[:6000]
    label = f" '{file_name}'" if file_name else ""
    messages = [
        {"role": "system", "content": _OLLAMA_SUMMARY_SYSTEM},
        {"role": "user",
         "content": f"Summarize the following contract document{label} using the "
                    f"required headings. Keep the total output under ~300 words.\n\n"
                    f"--- DOCUMENT START ---\n{snippet}\n--- DOCUMENT END ---"},
    ]
    try:
        summary = generate_text_local(messages, max_tokens=400, temperature=0.2)
        logger.info("Ollama summary produced (len=%d) for%s", len(summary or ""), label or " document")
        return (summary or "").strip() or None
    except Exception as e:
        logger.warning("Ollama summarization failed: %s", e)
        return None


_OLLAMA_DRIVER_SYSTEM = (
    "You are the Clause Analyst for a CLM platform. Produce a structured summary "
    "of the uploaded contract using the required headings. If a piece of information "
    "is missing from the document, or you are not confident, you MUST call the "
    "`ask_gemini` tool instead of guessing. To call a tool, respond with ONLY a "
    'JSON object: {"name": "ask_gemini", "arguments": {"question": "...", "context": "..."}}. '
    "Otherwise produce the final summary. Do not fabricate facts.\n\n"
    "Output format when giving the final summary (use these exact headings):\n"
    "PARTIES: ...\n"
    "CONTRACT TYPE: ...\n"
    "EFFECTIVE DATES / DURATION: ...\n"
    "KEY OBLIGATIONS: bullet list\n"
    "PAYMENT TERMS: ...\n"
    "TERMINATION CONDITIONS: ...\n"
    "GOVERNING LAW / JURISDICTION: ...\n"
    "NOTABLE CLAUSES: bullet list (verbatim snippets where useful)\n"
    "RISK FLAGS: bullet list of concerning terms, unusual language, or "
    "missing protections (factual, no advice)."
)


def _ollama_with_gemini_helper(
    document_text: str,
    file_name: str | None = None,
    user_question: str | None = None,
) -> dict:
    """Ollama-driven tool-call loop that can delegate to Gemini via ask_gemini.

    Runs up to 2 iterations. On each iteration Ollama either produces the
    final summary or emits a JSON tool call; a parse failure is treated as a
    final answer (gemma3:4b is flaky with JSON formatting).

    Returns:
        {"summary": str | None, "gemini_calls": int, "iterations": int}
    """
    from tools import (LOCAL_MODEL_ENABLED, is_ollama_available,
                       generate_text_local, parse_tool_call, ask_gemini,
                       TOOL_SCHEMAS)

    if not (LOCAL_MODEL_ENABLED and is_ollama_available()):
        return {"summary": None, "gemini_calls": 0, "iterations": 0}

    # Only expose ask_gemini to the driver loop
    driver_tools = [s for s in TOOL_SCHEMAS if s["function"]["name"] == "ask_gemini"]
    tools_json = __import__("json").dumps(driver_tools)

    snippet = document_text[:6000]
    label = f" '{file_name}'" if file_name else ""
    user_content = (
        f"Summarize the following contract document{label} using the required headings. "
        f"Keep the total output under ~300 words.\n\n"
        f"Available tools (JSON):\n{tools_json}\n\n"
        f"--- DOCUMENT START ---\n{snippet}\n--- DOCUMENT END ---"
    )
    if user_question:
        user_content += f"\n\nUser question: {user_question}"

    messages = [
        {"role": "system", "content": _OLLAMA_DRIVER_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    max_iterations = 2
    gemini_calls = 0
    last_text: str | None = None

    for i in range(max_iterations):
        try:
            response = generate_text_local(messages, max_tokens=400, temperature=0.2)
        except Exception as e:
            logger.warning("[ollama-driver] iter=%d generate_text_local failed: %s", i + 1, e)
            break

        tool_call = parse_tool_call(response)
        tool_name = tool_call["name"] if tool_call else "none"
        logger.info("[ollama-driver] iter=%d tool_call=%s text_len=%d",
                    i + 1, tool_name, len(response))

        if tool_call and tool_call.get("name") == "ask_gemini":
            args = tool_call.get("arguments", {})
            try:
                gemini_answer = ask_gemini(**args)
            except Exception as e:
                logger.warning("[ollama-driver] ask_gemini failed: %s", e)
                gemini_answer = "Gemini unavailable."
            gemini_calls += 1
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "tool", "content": gemini_answer})
        else:
            # Parse failure or plain text — treat as final answer
            last_text = response.strip() or None
            return {
                "summary": last_text,
                "gemini_calls": gemini_calls,
                "iterations": i + 1,
            }

    # Exhausted iterations without a final text answer
    return {"summary": last_text, "gemini_calls": gemini_calls, "iterations": max_iterations}


def _extract_json_from_response(text: str) -> str:
    """Extract JSON from a response that may be wrapped in markdown code fences."""
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

# ── Rate limiter ───────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024  # 1 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate Gemini API key on startup
    from tools import (get_gemini, GEMINI_MODEL, get_rate_limiter,
                       LOCAL_MODEL_ENABLED, OLLAMA_MODEL,
                       check_ollama_health, pull_ollama_model)
    try:
        client = get_gemini()
        logger.info(f"Gemini client initialized — model: {GEMINI_MODEL}")
        app.state.gemini_ready = True
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        app.state.gemini_ready = False

    # Initialize local model if enabled
    app.state.local_model_ready = False
    if LOCAL_MODEL_ENABLED:
        if check_ollama_health():
            logger.info(f"Local model ready — {OLLAMA_MODEL}")
            app.state.local_model_ready = True
        else:
            # Pull in a background thread so the server can start accepting
            # requests immediately (Gemini is available as a fallback).
            def _pull_in_background():
                logger.info("Pulling local model in background...")
                if pull_ollama_model() and check_ollama_health():
                    logger.info(f"Local model ready — {OLLAMA_MODEL}")
                    app.state.local_model_ready = True
                else:
                    logger.warning("Local model unavailable — all tasks will use Gemini")
            threading.Thread(target=_pull_in_background, daemon=True).start()
    else:
        logger.info("Local model disabled (LOCAL_MODEL_ENABLED=false)")

    yield
    logger.info("Shutting down")


app = FastAPI(
    title="CLM Agent Service",
    description="Document Architect and Clause Analyst agents for Contract Lifecycle Management",
    version="1.0.0",
    lifespan=lifespan
)

# Attach limiter state and exception handler
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://localhost:5174,http://localhost:8080"
    ).split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"}
    )


# ── Request size middleware ────────────────────────────────────────────────

@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body too large (max 1 MB)"}
        )
    return await call_next(request)


# ── Request / Response schemas ─────────────────────────────────────────────

class GenerateRequest(BaseModel):
    doc_type: Literal["nda", "msa", "sow", "sla"] = Field(
        ...,
        description="Contract type: nda, msa, sow, sla",
        examples=["nda"]
    )
    fields: dict = Field(
        default={},
        description="Template field values (party names, dates, terms, etc.)",
        examples=[{"party_a": "Acme Corp", "party_b": "Beta Ltd", "effective_date": "2024-01-01"}]
    )
    extra_context: Optional[str] = Field(
        default="",
        max_length=5000,
        description="Additional free-text instructions for the agent"
    )


class GenerateResponse(BaseModel):
    document:       str
    missing_fields: list
    clauses_used:   int
    doc_type:       str


class AnalyseRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Question about a clause or contract topic",
        examples=["What does the limitation of liability clause mean?"]
    )
    doc_type: Optional[Literal["nda", "msa", "sow", "sla"]] = Field(
        default=None,
        description="Optional contract type filter: nda, msa, sow, sla"
    )
    document_text: Optional[str] = Field(
        default=None,
        max_length=100000,
        description="Optional raw contract text to analyse directly"
    )


class AnalyseResponse(BaseModel):
    analysis:       str
    clauses_found:  int
    sources:        list
    question:       str


class AnalyzeTextRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="Raw contract text to analyse",
    )


class ChatRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Question about a contract or general legal question",
    )
    contract_text: Optional[str] = Field(
        default=None,
        max_length=100000,
        description="Optional contract text for context",
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Session ID for conversation continuity. "
                    "Send the same session_id across requests to maintain context.",
    )


class GenerateDraftRequest(BaseModel):
    contract_type: str = Field(
        ...,
        description="Type of contract (e.g. NDA, MSA, SOW, SLA, or any type)",
    )
    parties: list = Field(
        default=[],
        description="List of party dicts with 'name' and optional 'role'",
    )
    key_terms: dict = Field(
        default={},
        description="Key terms and values for the contract",
    )


class EmbedAndAnalyzeRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=200000,
        description="Extracted plain text from the uploaded document",
    )
    file_name: str = Field(
        default="upload",
        max_length=256,
        description="Original filename for metadata",
    )
    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="User's question about the document",
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Session ID for conversation continuity",
    )


class DetectConflictsRequest(BaseModel):
    contracts: list = Field(
        ...,
        min_length=2,
        max_length=10,
        description="List of contract dicts, each with 'title' and 'text'",
    )


class HealthResponse(BaseModel):
    status:            str
    model:             str
    es_status:         str
    redis_status:      str
    gemini_usage:      dict = {}
    local_model:       str = "disabled"
    local_model_name:  str = ""


# ── Endpoints ──────────────────────────────────────────────────────────────


class DebugOllamaSummaryRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw document text to summarize")
    file_name: Optional[str] = Field(default=None, description="Optional file name for context")


class DebugOllamaDriverRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw document text to run through the driver loop")
    file_name: Optional[str] = Field(default=None, description="Optional file name for context")
    question: Optional[str] = Field(default=None, description="Optional user question")


@app.get("/health", response_model=HealthResponse, tags=["system"])
@limiter.limit("60/minute")
def health(request: Request):
    """Check the health of the service and its dependencies."""
    from tools import (get_es, get_redis, get_rate_limiter, GEMINI_MODEL,
                       LOCAL_MODEL_ENABLED, OLLAMA_MODEL, is_ollama_available)

    # ES health
    try:
        get_es().cluster.health(timeout="2s")
        es_status = "ok"
    except Exception as e:
        es_status = f"error: {e}"

    # Redis health
    try:
        get_redis().ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {e}"

    # Local model health
    if LOCAL_MODEL_ENABLED:
        local_status = "ok" if is_ollama_available() else "unavailable"
        local_name = OLLAMA_MODEL
    else:
        local_status = "disabled"
        local_name = ""

    gemini_ready = getattr(request.app.state, "gemini_ready", False)
    return HealthResponse(
        status="ok" if gemini_ready else "gemini_not_ready",
        model=GEMINI_MODEL,
        es_status=es_status,
        redis_status=redis_status,
        gemini_usage=get_rate_limiter().usage,
        local_model=local_status,
        local_model_name=local_name,
    )


@app.get("/templates", tags=["documents"])
def list_templates():
    """List available contract templates and their required fields."""
    templates_dir = Path(__file__).parent / "templates"
    result = {}
    for name, filename in [("nda", "nda.txt"), ("msa", "msa.txt"),
                            ("sow", "sow.txt"), ("sla", "sla.txt")]:
        path = templates_dir / filename
        if path.exists():
            text = path.read_text()
            fields = re.findall(r'\{([^}]+)\}', text)
            result[name] = {
                "description": {
                    "nda": "Non-Disclosure Agreement",
                    "msa": "Master Service Agreement",
                    "sow": "Statement of Work",
                    "sla": "Service Level Agreement",
                }[name],
                "required_fields": sorted(set(fields))
            }
    return result


@app.post("/generate", response_model=GenerateResponse, tags=["documents"])
@limiter.limit("10/minute")
def generate_document(request: Request, body: GenerateRequest):
    """
    Generate a contract document using the Document Architect agent.

    The agent searches the knowledge base for relevant clauses,
    merges them with your field values, and renders the final contract.
    """
    logger.info(f"POST /generate doc_type={body.doc_type} fields_count={len(body.fields)}")

    if not getattr(request.app.state, "gemini_ready", False):
        raise HTTPException(status_code=503, detail="Gemini client not ready")

    try:
        from agents.architect import run as architect_run
        result = architect_run(
            doc_type=body.doc_type.lower(),
            user_fields=body.fields,
            extra_context=body.extra_context or ""
        )
        return GenerateResponse(
            document=result["document"],
            missing_fields=result["missing_fields"],
            clauses_used=result["clauses_used"],
            doc_type=body.doc_type.upper()
        )
    except Exception as e:
        logger.exception("Error in /generate")
        status = 429 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))


@app.post("/analyse", response_model=AnalyseResponse, tags=["clauses"])
@limiter.limit("10/minute")
def analyse_clause(request: Request, body: AnalyseRequest):
    """
    Analyse contract clauses using the Clause Analyst agent.

    The agent searches the knowledge base for relevant clause examples
    and provides a structured analysis with risk flags and recommendations.
    """
    logger.info(f"POST /analyse question_len={len(body.question)} doc_type={body.doc_type}")

    if not getattr(request.app.state, "gemini_ready", False):
        raise HTTPException(status_code=503, detail="Gemini client not ready")

    try:
        from agents.analyst import run as analyst_run
        result = analyst_run(
            question=body.question,
            doc_type=body.doc_type,
            document_text=body.document_text
        )
        return AnalyseResponse(
            analysis=result["analysis"],
            clauses_found=result["clauses_found"],
            sources=result["sources"],
            question=body.question
        )
    except Exception as e:
        logger.exception("Error in /analyse")
        status = 429 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))


# ── CLM Integration Endpoints ────────────────────────────────────────────
# These endpoints are designed for the CLAUSE CLM backend to delegate its
# AI operations to this agent service instead of calling Gemini directly.


@app.post("/analyze-text", tags=["clm-integration"])
@limiter.limit("10/minute")
def analyze_contract_text(request: Request, body: AnalyzeTextRequest):
    """
    Analyze raw contract text and return structured analysis with risk scoring.
    Used by the CLAUSE CLM backend for contract analysis.
    """
    logger.info(f"POST /analyze-text text_length={len(body.text)}")

    from tools import LOCAL_MODEL_ENABLED, is_ollama_available

    gemini_ready = getattr(request.app.state, "gemini_ready", False)
    local_ready = LOCAL_MODEL_ENABLED and is_ollama_available()

    if not gemini_ready and not local_ready:
        raise HTTPException(status_code=503, detail="No AI model available")

    response_text = None
    try:
        from tools import generate_text, search_clauses
        import json

        # Search knowledge base for similar clauses to improve analysis.
        # This calls Gemini Embedding — skip if Gemini is rate-limited
        # (the analysis can still work without KB context).
        kb_context = ""
        try:
            kb_results = search_clauses(query=body.text[:300], top_k=2)
            kb_data = json.loads(kb_results)
            if kb_data:
                kb_context = (
                    "\n\nReference clauses from knowledge base:\n"
                    + "\n".join(f"- {c['text'][:200]}" for c in kb_data)
                )
        except Exception:
            logger.warning("KB search failed during analyze-text, proceeding without")

        # Pre-summarize with Ollama (tool-call loop) so Gemini receives compressed context.
        driver_result = _ollama_with_gemini_helper(body.text)
        ollama_summary = driver_result["summary"]
        logger.info("ollama-driver: gemini_calls=%d iterations=%d summary_len=%d",
                    driver_result["gemini_calls"], driver_result["iterations"],
                    len(ollama_summary or ""))
        summary_block = (
            f"\n\nPre-computed summary (from local model):\n{ollama_summary}\n"
            if ollama_summary else ""
        )

        prompt = f"""Analyze the following contract text and provide a structured analysis in JSON format.
Return ONLY valid JSON with these fields:
{{
    "summary": "A 2-3 sentence summary of the contract",
    "extracted_clauses": ["list of key clauses found"],
    "key_information": {{
        "parties": ["list of parties involved"],
        "duration": "contract duration",
        "payment_terms": "payment terms if found",
        "termination_conditions": "how the contract can be terminated",
        "governing_law": "applicable law/jurisdiction"
    }},
    "risk_score": <number 0-100>,
    "risk_level": "<low|medium|high>",
    "risk_factors": ["list of identified risk factors"],
    "recommendations": ["list of recommendations for improvement"]
}}
{kb_context}{summary_block}

Contract text:
{body.text}"""

        messages = [
            {"role": "system", "content": "You are a legal AI analyst for a CLM platform. Provide precise, structured contract analysis."},
            {"role": "user", "content": prompt},
        ]

        # When Ollama produced the summary, send the analysis to Gemini
        # (bypass local routing by using a task key not in LOCAL_CAPABLE_TASKS).
        # If Gemini is ready, always route the final analysis to Gemini — avoids
        # a second long wait on local when Ollama is slow or already timed out.
        analysis_task = "analyze-text-gemini" if gemini_ready else "analyze-text"
        response_text = generate_text(messages, max_tokens=1024, temperature=0.3, task=analysis_task)

        # Parse JSON from response (robust code fence handling)
        response_text = _extract_json_from_response(response_text)

        analysis = json.loads(response_text)
        return analysis

    except json.JSONDecodeError:
        # If JSON parsing fails, return the raw text in a structured wrapper
        return {
            "summary": response_text[:500] if response_text else "Analysis failed",
            "error": "Could not parse structured analysis",
        }
    except Exception as e:
        logger.exception("Error in /analyze-text")
        status = 429 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))


@app.post("/generate-draft", tags=["clm-integration"])
@limiter.limit("10/minute")
def generate_draft(request: Request, body: GenerateDraftRequest):
    """
    Generate a contract draft from parameters (type, parties, key terms).
    Used by the CLAUSE CLM backend for AI-powered draft generation.
    """
    logger.info(f"POST /generate-draft type={body.contract_type} parties={len(body.parties)}")

    if not getattr(request.app.state, "gemini_ready", False):
        raise HTTPException(status_code=503, detail="Gemini client not ready")

    try:
        from tools import generate_text, search_clauses
        import json

        doc_type_lower = body.contract_type.lower()
        supported_templates = ["nda", "msa", "sow", "sla"]

        # If it's a supported template type, use the architect agent
        if doc_type_lower in supported_templates:
            from agents.architect import run as architect_run
            fields = dict(body.key_terms)
            if body.parties:
                for i, p in enumerate(body.parties):
                    name = p.get("name", f"Party {chr(65 + i)}")
                    fields[f"party_{chr(97 + i)}"] = name
            result = architect_run(
                doc_type=doc_type_lower,
                user_fields=fields,
                extra_context="",
            )
            return {
                "contract_type": body.contract_type,
                "content": result["document"],
                "missing_fields": result["missing_fields"],
                "clauses_used": result["clauses_used"],
            }

        # For non-template types, generate freeform with knowledge base context
        kb_context = ""
        try:
            kb_results = search_clauses(query=f"{body.contract_type} contract clauses", top_k=5)
            kb_data = json.loads(kb_results)
            if kb_data:
                kb_context = (
                    "\n\nReference clauses from knowledge base:\n"
                    + "\n---\n".join(c["text"][:300] for c in kb_data)
                )
        except Exception:
            logger.warning("KB search failed during generate-draft, proceeding without")

        parties_str = ", ".join(
            p.get("name", "Party") for p in body.parties
        ) if body.parties else "Party A, Party B"
        terms_str = "\n".join(
            f"- {k}: {v}" for k, v in body.key_terms.items()
        ) if body.key_terms else "Standard terms"

        prompt = f"""Generate a professional {body.contract_type} contract between {parties_str}.

Key terms:
{terms_str}
{kb_context}

Generate a complete, professional contract with standard legal clauses.
Include sections for: Parties, Scope, Term, Payment, Confidentiality, Termination, Governing Law, and Signatures.
Return the contract as plain text."""

        messages = [
            {"role": "system", "content": "You are a Document Architect for a CLM platform. Generate complete, professional contracts."},
            {"role": "user", "content": prompt},
        ]

        content = generate_text(messages, max_tokens=4096, temperature=0.2, task="generate-draft")

        return {
            "contract_type": body.contract_type,
            "content": content,
        }

    except Exception as e:
        logger.exception("Error in /generate-draft")
        status = 429 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))


CHAT_HISTORY_TTL = 1800  # 30 minutes
CHAT_MAX_HISTORY = 20    # keep last 20 messages (10 turns) for context

# Short or generic messages that don't need a knowledge base search.
# KB search calls Gemini Embedding API which costs tokens and can hit rate limits.
MIN_QUERY_LENGTH_FOR_KB = 15


def _chat_history_key(session_id: str) -> str:
    return f"chat_history:{session_id}"


def _load_chat_history(session_id: str) -> list[dict]:
    """Load previous conversation messages from Redis."""
    from tools import get_redis
    import json
    try:
        raw = get_redis().get(_chat_history_key(session_id))
        if raw:
            return json.loads(raw)
    except Exception:
        logger.warning("Failed to load chat history for session %s", session_id)
    return []


def _save_chat_history(session_id: str, history: list[dict]):
    """Persist conversation messages to Redis with a TTL."""
    from tools import get_redis
    import json
    try:
        # Keep only the most recent messages to stay within token limits
        trimmed = history[-CHAT_MAX_HISTORY:]
        get_redis().setex(
            _chat_history_key(session_id),
            CHAT_HISTORY_TTL,
            json.dumps(trimmed),
        )
    except Exception:
        logger.warning("Failed to save chat history for session %s", session_id)


@app.post("/chat", tags=["clm-integration"])
@limiter.limit("15/minute")
def chat(request: Request, body: ChatRequest):
    """
    AI Q&A — answer questions about contracts or general legal topics.
    Augmented with knowledge base search for better answers.
    Supports conversation continuity via session_id.
    Used by the CLAUSE CLM backend for the AI chat feature.
    """
    logger.info(f"POST /chat question_len={len(body.question)} session={body.session_id or 'none'}")

    from tools import (generate_text, search_clauses,
                       LOCAL_MODEL_ENABLED, is_ollama_available)

    # Allow chat if EITHER Gemini or local model is available
    gemini_ready = getattr(request.app.state, "gemini_ready", False)
    local_ready = LOCAL_MODEL_ENABLED and is_ollama_available()

    if not gemini_ready and not local_ready:
        raise HTTPException(status_code=503, detail="No AI model available (Gemini and local model both unavailable)")

    try:
        import json

        # Only search the knowledge base for substantive questions.
        # Short messages like "hi", "thanks", "ok" don't need a KB lookup,
        # which would call Gemini Embedding API and burn tokens / hit rate limits.
        kb_context = ""
        question_stripped = body.question.strip()
        needs_kb_search = len(question_stripped) >= MIN_QUERY_LENGTH_FOR_KB

        if needs_kb_search:
            try:
                kb_results = search_clauses(query=body.question, top_k=2)
                kb_data = json.loads(kb_results)
                if kb_data:
                    kb_context = (
                        "\n\nRelevant clauses from knowledge base:\n"
                        + "\n".join(f"- {c['text'][:200]}" for c in kb_data)
                    )
            except Exception:
                logger.warning("KB search failed during chat, proceeding without")

        context = ""
        if body.contract_text:
            context = f"\n\nContract context:\n{body.contract_text[:5000]}"

        # Build the current user message
        user_content = ""
        if context:
            user_content += context
        if kb_context:
            user_content += kb_context
        user_content += f"\n\nQuestion: {body.question}"

        system_message = {
            "role": "system",
            "content": (
                "You are a legal AI assistant for a Contract Lifecycle Management system. "
                "Answer questions clearly and professionally. Use the provided contract context "
                "and knowledge base references when available. "
                "You have access to the conversation history, so you can reference "
                "previous questions and answers for continuity."
            ),
        }

        # Load conversation history if session_id is provided
        history = []
        if body.session_id:
            history = _load_chat_history(body.session_id)

        messages = [system_message] + history + [{"role": "user", "content": user_content}]

        answer = generate_text(messages, max_tokens=1024, temperature=0.3, task="chat")

        # Save updated history
        if body.session_id:
            history.append({"role": "user", "content": user_content})
            history.append({"role": "assistant", "content": answer})
            _save_chat_history(body.session_id, history)

        return {
            "answer": answer,
            "session_id": body.session_id,
        }

    except Exception as e:
        logger.exception("Error in /chat")
        status = 429 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))


@app.post("/detect-conflicts", tags=["clm-integration"])
@limiter.limit("5/minute")
def detect_conflicts(request: Request, body: DetectConflictsRequest):
    """
    Detect conflicting clauses across multiple contracts.
    Accepts a list of contract dicts with 'title' and 'text' fields.
    Used by the CLAUSE CLM backend for cross-contract conflict detection.
    """
    logger.info(f"POST /detect-conflicts contracts={len(body.contracts)}")

    if not getattr(request.app.state, "gemini_ready", False):
        raise HTTPException(status_code=503, detail="Gemini client not ready")

    response_text = None
    try:
        from tools import generate_text
        import json

        contract_texts = []
        for i, c in enumerate(body.contracts, 1):
            title = c.get("title", f"Contract {i}")
            text = c.get("text", "")[:10000]
            contract_texts.append(f"--- CONTRACT {i}: {title} ---\n{text}")

        all_text = "\n\n".join(contract_texts)

        prompt = f"""Analyze the following {len(body.contracts)} contracts and identify conflicting, contradictory, or incompatible clauses.

For each conflict, provide:
1. Which contracts are involved (by title)
2. The specific clauses that conflict
3. The nature of the conflict
4. Severity (high, medium, low)
5. Resolution recommendation

Return ONLY valid JSON:
{{
    "total_conflicts": <number>,
    "overall_risk": "<low|medium|high|critical>",
    "summary": "Brief summary of findings",
    "conflicts": [
        {{
            "id": 1,
            "contract_a": "Title of first contract",
            "contract_b": "Title of second contract",
            "clause_a": "Clause from contract A",
            "clause_b": "Conflicting clause from contract B",
            "conflict_type": "<contradiction|overlap|incompatibility|ambiguity>",
            "severity": "<high|medium|low>",
            "description": "Why these conflict",
            "recommendation": "How to resolve"
        }}
    ]
}}

If no conflicts are found, return total_conflicts: 0 with an empty conflicts array.

Contracts:
{all_text}"""

        messages = [
            {"role": "system", "content": "You are a legal analyst specializing in contract conflict detection for a CLM platform."},
            {"role": "user", "content": prompt},
        ]

        response_text = generate_text(messages, max_tokens=4096, temperature=0.3, task="detect-conflicts")

        # Robust code fence handling
        response_text = _extract_json_from_response(response_text)

        result = json.loads(response_text)
        result["contracts_analyzed"] = [
            {"title": c.get("title", f"Contract {i+1}")}
            for i, c in enumerate(body.contracts)
        ]
        return result

    except json.JSONDecodeError:
        return {
            "total_conflicts": 0,
            "conflicts": [],
            "summary": response_text[:500] if response_text else "Conflict analysis failed",
            "error": "Could not parse structured conflict analysis",
        }
    except Exception as e:
        logger.exception("Error in /detect-conflicts")
        status = 429 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))


# ── Embed & Analyze — ingest a document, then answer questions ───────────

# Chunking parameters (mirrors the ingestion pipeline)
_CHUNK_SIZE = 2000
_CHUNK_OVERLAP = 200
_MIN_CHUNK_LEN = 50
_EMBED_BATCH_SIZE = 100
_MAX_CONTEXT_FOR_CHAT = 50000


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks using recursive separators."""
    separators = ["\n\n", "\n", ". ", " "]

    def _split(text: str, seps: list[str]) -> list[str]:
        if len(text) <= _CHUNK_SIZE:
            return [text]

        sep = seps[0] if seps else ""
        rest = seps[1:] if len(seps) > 1 else [""]
        parts = text.split(sep) if sep else [text[i:i + _CHUNK_SIZE] for i in range(0, len(text), _CHUNK_SIZE)]

        chunks = []
        current = ""
        for part in parts:
            candidate = f"{current}{sep}{part}" if current else part
            if len(candidate) <= _CHUNK_SIZE:
                current = candidate
            else:
                if current:
                    chunks.extend(_split(current, rest) if len(current) > _CHUNK_SIZE else [current])
                current = part
        if current:
            chunks.extend(_split(current, rest) if len(current) > _CHUNK_SIZE else [current])
        return chunks

    chunks = _split(text, separators)
    return [c for c in chunks if len(c.strip()) >= _MIN_CHUNK_LEN]


def _embed_and_index(chunks: list[str], file_name: str) -> int:
    """Embed chunks with Gemini and index them in Elasticsearch.

    Returns the number of chunks successfully indexed.
    """
    import hashlib
    from elasticsearch.helpers import bulk as es_bulk
    from tools import get_gemini, get_es, get_rate_limiter, INDEX_NAME

    es = get_es()
    client = get_gemini()
    content_hash = hashlib.sha256(("\n".join(chunks)).encode()).hexdigest()

    # Check if already indexed
    try:
        resp = es.search(
            index=INDEX_NAME,
            query={"bool": {"filter": [
                {"term": {"metadata.source": file_name}},
                {"term": {"metadata.content_hash": content_hash}},
            ]}},
            size=1,
            _source=False,
        )
        if resp["hits"]["total"]["value"] > 0:
            logger.info("Document '%s' already indexed with same content, skipping embed", file_name)
            return resp["hits"]["total"]["value"]
    except Exception:
        pass

    # Clear old chunks from a previous version of this file
    try:
        es.delete_by_query(
            index=INDEX_NAME,
            query={"term": {"metadata.source": file_name}},
            refresh=True,
        )
    except Exception:
        pass

    # Embed and index in batches
    actions = []
    for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + _EMBED_BATCH_SIZE]

        get_rate_limiter().acquire()
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=batch,
        )

        for offset, (chunk, emb_obj) in enumerate(zip(batch, result.embeddings)):
            actions.append({
                "_index": INDEX_NAME,
                "_source": {
                    "text": chunk,
                    "vector": emb_obj.values,
                    "metadata": {
                        "source": file_name,
                        "doc_type": "upload",
                        "customer": "chat_upload",
                        "chunk_id": batch_start + offset,
                        "file_type": file_name.rsplit(".", 1)[-1] if "." in file_name else "unknown",
                        "content_hash": content_hash,
                    },
                },
            })

    success_count, errors = es_bulk(es, actions, raise_on_error=False)
    if errors:
        logger.error("Embed-and-index had %d error(s) for %s", len(errors), file_name)
    logger.info("Indexed %d chunks from uploaded document '%s'", success_count, file_name)

    # Force refresh so the chunks are immediately searchable
    try:
        es.indices.refresh(index=INDEX_NAME)
    except Exception:
        pass

    return success_count


@app.post("/embed-and-analyze", tags=["clm-integration"])
@limiter.limit("5/minute")
def embed_and_analyze(request: Request, body: EmbedAndAnalyzeRequest):
    """
    Embed an uploaded document into the knowledge base, then use it
    (along with KB search) to answer the user's question.

    Flow:
      1. Chunk the extracted text
      2. Embed each chunk with Gemini Embedding API
      3. Index chunks in Elasticsearch
      4. Search the KB (now including this document) for relevant context
      5. Send the context + question to the AI for analysis
    """
    logger.info(
        "POST /embed-and-analyze file=%s text_len=%d question_len=%d",
        body.file_name, len(body.text), len(body.question),
    )

    from tools import (generate_text, search_clauses,
                       LOCAL_MODEL_ENABLED, is_ollama_available)

    gemini_ready = getattr(request.app.state, "gemini_ready", False)
    local_ready = LOCAL_MODEL_ENABLED and is_ollama_available()

    if not gemini_ready and not local_ready:
        raise HTTPException(status_code=503, detail="No AI model available")

    try:
        import json

        # --- Step 1-3: Chunk, embed, and index the document ---
        chunks = _chunk_text(body.text)
        if not chunks:
            raise HTTPException(status_code=400, detail="No meaningful text found in the document")

        indexed_count = 0
        try:
            indexed_count = _embed_and_index(chunks, body.file_name)
            logger.info("Embedded %d chunks for '%s'", indexed_count, body.file_name)
        except Exception as e:
            # Embedding failed — fall back to using raw text as context
            logger.warning("Embedding failed for '%s': %s — using raw text", body.file_name, e)

        # --- Step 4: Search KB for relevant context (now includes this doc) ---
        kb_context = ""
        try:
            kb_results = search_clauses(query=body.question, top_k=5)
            kb_data = json.loads(kb_results)
            if kb_data:
                kb_context = (
                    "\n\nRelevant clauses from knowledge base:\n"
                    + "\n---\n".join(f"[{c.get('source', 'unknown')}] {c['text'][:500]}" for c in kb_data)
                )
        except Exception:
            logger.warning("KB search failed during embed-and-analyze, proceeding without")

        # --- Step 5: Build prompt and get AI response ---
        # Pre-summarize the document with the Ollama driver (tool-call loop)
        # so Gemini receives compressed context in addition to the raw preview.
        driver_result = _ollama_with_gemini_helper(body.text, body.file_name, body.question)
        ollama_summary = driver_result["summary"]
        logger.info("ollama-driver: gemini_calls=%d iterations=%d summary_len=%d",
                    driver_result["gemini_calls"], driver_result["iterations"],
                    len(ollama_summary or ""))
        summary_block = (
            f"\n\n--- LOCAL MODEL SUMMARY ---\n{ollama_summary}\n--- END SUMMARY ---"
            if ollama_summary else ""
        )

        # Include the beginning of the document as direct context
        # (the AI also has the embedded chunks available via KB search above)
        doc_preview = body.text[:_MAX_CONTEXT_FOR_CHAT]

        user_content = (
            "The following contract document has been uploaded and embedded "
            "into the knowledge base for reference. First, identify the key "
            "information: parties involved, contract type, effective dates, "
            "key terms, payment terms, obligations, termination conditions, "
            "and any notable clauses or risks.\n\n"
            f"--- DOCUMENT: {body.file_name} ---\n"
            f"{doc_preview}\n"
            "--- END DOCUMENT ---"
            f"{summary_block}"
            f"{kb_context}"
            f"\n\nQuestion: {body.question}"
        )

        system_message = {
            "role": "system",
            "content": (
                "You are a legal AI assistant for a Contract Lifecycle Management system. "
                "A document has been uploaded and embedded into the knowledge base. "
                "Use both the document text and the knowledge base search results to "
                "provide thorough, accurate analysis. Answer clearly and professionally."
            ),
        }

        # Load conversation history if session_id is provided
        history = []
        if body.session_id:
            history = _load_chat_history(body.session_id)

        messages = [system_message] + history + [{"role": "user", "content": user_content}]

        # Send the final analysis to Gemini once Ollama has produced a summary
        # (bypass local routing by using a task key not in LOCAL_CAPABLE_TASKS).
        # If Gemini is ready, always route the final analysis to Gemini — avoids
        # a second long wait on local when Ollama is slow or already timed out.
        analysis_task = "analyze-text-gemini" if gemini_ready else "analyze-text"
        answer = generate_text(messages, max_tokens=2048, temperature=0.3, task=analysis_task)

        # Save updated history
        if body.session_id:
            history.append({"role": "user", "content": user_content})
            history.append({"role": "assistant", "content": answer})
            _save_chat_history(body.session_id, history)

        return {
            "answer": answer,
            "session_id": body.session_id,
            "file_name": body.file_name,
            "chunks_indexed": indexed_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /embed-and-analyze")
        status = 429 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 500
        raise HTTPException(status_code=status, detail=str(e))


@app.post("/debug/ollama-summary", tags=["debug"])
@limiter.limit("10/minute")
def debug_ollama_summary(request: Request, body: DebugOllamaSummaryRequest):
    """Return the raw Ollama summary produced by the guardrail-applied
    summarizer. Use this to inspect exactly what Gemini will receive as
    pre-analysis context for an uploaded document."""
    from tools import LOCAL_MODEL_ENABLED, is_ollama_available, OLLAMA_MODEL

    if not LOCAL_MODEL_ENABLED:
        raise HTTPException(status_code=503, detail="Local model disabled (LOCAL_MODEL_ENABLED=false)")
    if not is_ollama_available():
        raise HTTPException(status_code=503, detail="Ollama is not reachable")

    import time
    t0 = time.time()
    summary = _summarize_with_ollama(body.text, body.file_name)
    elapsed_ms = int((time.time() - t0) * 1000)

    if summary is None:
        raise HTTPException(status_code=502, detail="Ollama summarization returned no content")

    return {
        "model": OLLAMA_MODEL,
        "file_name": body.file_name,
        "input_chars": len(body.text),
        "summary_chars": len(summary),
        "elapsed_ms": elapsed_ms,
        "summary": summary,
    }


@app.post("/debug/ollama-driver", tags=["debug"])
@limiter.limit("10/minute")
def debug_ollama_driver(request: Request, body: DebugOllamaDriverRequest):
    """Run the Ollama tool-call driver loop and return its output + stats.
    Use this to verify ask_gemini delegation and driver loop behaviour."""
    from tools import LOCAL_MODEL_ENABLED, is_ollama_available, OLLAMA_MODEL

    if not LOCAL_MODEL_ENABLED:
        raise HTTPException(status_code=503, detail="Local model disabled (LOCAL_MODEL_ENABLED=false)")
    if not is_ollama_available():
        raise HTTPException(status_code=503, detail="Ollama is not reachable")

    import time
    t0 = time.time()
    result = _ollama_with_gemini_helper(body.text, body.file_name, body.question)
    elapsed_ms = int((time.time() - t0) * 1000)

    return {
        "model": OLLAMA_MODEL,
        "input_chars": len(body.text),
        "summary": result["summary"],
        "summary_chars": len(result["summary"] or ""),
        "gemini_calls": result["gemini_calls"],
        "iterations": result["iterations"],
        "elapsed_ms": elapsed_ms,
    }
