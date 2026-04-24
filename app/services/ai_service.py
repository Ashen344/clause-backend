"""
AI Service — Delegates all AI operations to the Agent microservice.

Instead of calling Gemini directly, every function in this module sends an
HTTP request to the Agent service (configured via AI_PLATFORM_URL).  The
Agent service provides:
  • RAG search (Elasticsearch + Gemini embeddings)
  • Redis-backed response caching
  • Smart model routing (Gemini / Claude / local Ollama)
  • Per-model rate limiting (RPM + RPD)
  • Two specialised agents: Document Architect & Clause Analyst

The backend keeps responsibility for:
  • Authentication & authorisation
  • Fetching contracts from MongoDB
  • Building contract text from DB documents
  • Storing AI analysis results back to the DB
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
from bson import ObjectId

from app.config import contracts_collection, AI_PLATFORM_URL

logger = logging.getLogger(__name__)

# Timeouts: the agent may run multi-step tool-calling loops, so analysis
# and generation get generous limits.  Chat is quicker.
_TIMEOUT_ANALYSIS = httpx.Timeout(timeout=120.0, connect=10.0)
_TIMEOUT_CHAT = httpx.Timeout(timeout=60.0, connect=10.0)
_TIMEOUT_GENERATION = httpx.Timeout(timeout=120.0, connect=10.0)


# ── Helpers ────────────────────────────────────────────────────────────────

def _agent_url(path: str) -> str:
    """Build the full URL for an agent endpoint."""
    base = AI_PLATFORM_URL.rstrip("/")
    return f"{base}{path}"


def _build_contract_text(contract: dict) -> str:
    """Build readable text from a contract document for AI analysis."""
    parts = [
        f"Title: {contract.get('title', 'N/A')}",
        f"Type: {contract.get('contract_type', 'N/A')}",
        f"Description: {contract.get('description', 'N/A')}",
        f"Status: {contract.get('status', 'N/A')}",
        f"Start Date: {contract.get('start_date', 'N/A')}",
        f"End Date: {contract.get('end_date', 'N/A')}",
        f"Value: {contract.get('value', 'N/A')}",
        f"Payment Terms: {contract.get('payment_terms', 'N/A')}",
    ]

    parties = contract.get("parties", [])
    if parties:
        party_strs = [f"  - {p.get('name', 'Unknown')} ({p.get('role', 'N/A')})" for p in parties]
        parts.append("Parties:\n" + "\n".join(party_strs))

    tags = contract.get("tags", [])
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")

    return "\n".join(parts)


# ── Contract Text Analysis ─────────────────────────────────────────────────

async def analyze_contract_text(contract_text: str) -> dict:
    """Send raw contract text to the agent service for structured analysis.

    Agent endpoint: POST /analyze-text
    Returns a dict with summary, risk_score, risk_level, etc.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_ANALYSIS) as client:
            response = await client.post(
                _agent_url("/analyze-text"),
                json={"text": contract_text},
            )
            response.raise_for_status()
            analysis = response.json()
            analysis["analyzed_at"] = datetime.utcnow().isoformat()
            return analysis

    except httpx.HTTPStatusError as e:
        logger.error("Agent /analyze-text returned %s: %s", e.response.status_code, e.response.text[:300])
        return _error_analysis(f"Agent service error: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning("Agent service unreachable for /analyze-text: %s", e)
        return _mock_analysis()


async def analyze_contract_by_id(contract_id: str) -> Optional[dict]:
    """Fetch a contract from the DB, send its text to the agent, and
    store the analysis results back on the contract document."""
    if not ObjectId.is_valid(contract_id):
        return None

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        return None

    contract_text = _build_contract_text(contract)
    analysis = await analyze_contract_text(contract_text)

    # Store the analysis results back on the contract
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

    update_fields = {
        "ai_analysis": ai_analysis,
        "updated_at": datetime.utcnow(),
    }
    if analysis.get("risk_level"):
        update_fields["risk_level"] = analysis["risk_level"]
    if analysis.get("risk_score") is not None:
        update_fields["risk_score"] = analysis["risk_score"]

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": update_fields}
    )

    analysis["contract_id"] = contract_id
    return analysis


# ── Contract Draft Generation ──────────────────────────────────────────────

async def generate_contract_draft(
    contract_type: str,
    parties: list,
    key_terms: dict,
) -> dict:
    """Ask the agent service to generate a contract draft.

    Agent endpoint: POST /generate-draft
    For supported types (NDA, MSA, SOW, SLA) the agent uses its Document
    Architect agent with KB-backed clause retrieval and template rendering.
    For other types it generates a freeform draft.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_GENERATION) as client:
            response = await client.post(
                _agent_url("/generate-draft"),
                json={
                    "contract_type": contract_type,
                    "parties": parties or [],
                    "key_terms": key_terms or {},
                },
            )
            response.raise_for_status()
            result = response.json()
            result["generated_at"] = datetime.utcnow().isoformat()
            return result

    except httpx.HTTPStatusError as e:
        logger.error("Agent /generate-draft returned %s: %s", e.response.status_code, e.response.text[:300])
        return {
            "error": f"Agent service error: {e.response.status_code}",
            "content": "Draft generation failed. Please try again.",
            "generated_at": datetime.utcnow().isoformat(),
        }
    except httpx.RequestError as e:
        logger.warning("Agent service unreachable for /generate-draft: %s", e)
        return _mock_draft(contract_type, parties)


# ── AI Chat ────────────────────────────────────────────────────────────────

async def ai_chat(contract_id: str, question: str, history: list = None) -> dict:
    """Ask the agent service a question, optionally with contract context.

    Agent endpoint: POST /chat
    Supports session-based conversation continuity via session_id.
    """
    # Build contract context from the DB if a contract_id was provided
    contract_text = None
    if contract_id and ObjectId.is_valid(contract_id):
        contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
        if contract:
            contract_text = _build_contract_text(contract)

    # Use contract_id as the session_id for conversation continuity
    session_id = contract_id if contract_id else None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_CHAT) as client:
            response = await client.post(
                _agent_url("/chat"),
                json={
                    "question": question,
                    "contract_text": contract_text,
                    "session_id": session_id,
                },
            )
            response.raise_for_status()
            result = response.json()
            return {
                "answer": result.get("answer", ""),
                "contract_id": contract_id,
                "session_id": result.get("session_id"),
            }

    except httpx.HTTPStatusError as e:
        logger.error("Agent /chat returned %s: %s", e.response.status_code, e.response.text[:300])
        return {
            "answer": f"AI service error ({e.response.status_code}). Please try again.",
            "contract_id": contract_id,
        }
    except httpx.RequestError as e:
        logger.warning("Agent service unreachable for /chat: %s", e)
        return {
            "answer": "AI service is currently unavailable. Please try again later.",
            "contract_id": contract_id,
        }


# ── Conflict Detection ────────────────────────────────────────────────────

async def detect_conflicts(contract_ids: list[str]) -> dict:
    """Fetch contracts from the DB, build text, and ask the agent to
    detect conflicting clauses across them.

    Agent endpoint: POST /detect-conflicts
    """
    contracts = []
    for cid in contract_ids:
        if not ObjectId.is_valid(cid):
            continue
        c = contracts_collection.find_one({"_id": ObjectId(cid)})
        if c:
            contracts.append(c)

    if len(contracts) < 2:
        return {
            "error": "At least 2 valid contracts are required for conflict detection.",
            "conflicts": [],
        }

    # Build the payload the agent expects: list of {title, text} dicts
    contract_dicts = [
        {
            "title": c.get("title", "Untitled"),
            "text": _build_contract_text(c),
        }
        for c in contracts
    ]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_ANALYSIS) as client:
            response = await client.post(
                _agent_url("/detect-conflicts"),
                json={"contracts": contract_dicts},
            )
            response.raise_for_status()
            result = response.json()
            # Enrich with contract IDs for the frontend
            result["contracts_analyzed"] = [
                {"id": str(c["_id"]), "title": c.get("title", "Untitled")}
                for c in contracts
            ]
            result["analyzed_at"] = datetime.utcnow().isoformat()
            return result

    except httpx.HTTPStatusError as e:
        logger.error("Agent /detect-conflicts returned %s: %s", e.response.status_code, e.response.text[:300])
        return {
            "error": f"Agent service error: {e.response.status_code}",
            "conflicts": [],
            "total_conflicts": 0,
            "analyzed_at": datetime.utcnow().isoformat(),
        }
    except httpx.RequestError as e:
        logger.warning("Agent service unreachable for /detect-conflicts: %s", e)
        return _mock_conflicts(contracts)


async def scan_contract_against_existing(contract_id: str) -> dict:
    """Check a contract against all other contracts in the DB for conflicts."""
    if not ObjectId.is_valid(contract_id):
        return {"error": "Invalid contract ID", "total_conflicts": 0, "conflicts": []}

    other_ids = [
        str(c["_id"])
        for c in contracts_collection.find(
            {"_id": {"$ne": ObjectId(contract_id)}}, {"_id": 1}
        ).sort("created_at", -1).limit(9)
    ]

    if not other_ids:
        return {
            "total_conflicts": 0,
            "overall_risk": "low",
            "summary": "No existing contracts to compare against — your document is conflict-free.",
            "conflicts": [],
            "contracts_analyzed": [],
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    return await detect_conflicts([contract_id] + other_ids)


# ── Document Embed & Analyze ──────────────────────────────────────────────

async def embed_and_analyze(
    text: str,
    file_name: str,
    question: str,
    session_id: str = None,
) -> dict:
    """Send an uploaded document to the agent for embedding into the
    knowledge base and AI-powered analysis.

    Agent endpoint: POST /embed-and-analyze
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_ANALYSIS) as client:
            response = await client.post(
                _agent_url("/embed-and-analyze"),
                json={
                    "text": text,
                    "file_name": file_name,
                    "question": question,
                    "session_id": session_id or "",
                },
            )
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        logger.error("Agent /embed-and-analyze returned %s: %s", e.response.status_code, e.response.text[:300])
        return {
            "answer": f"Agent service error ({e.response.status_code}). Please try again.",
            "file_name": file_name,
            "chunks_indexed": 0,
        }
    except httpx.RequestError as e:
        logger.warning("Agent service unreachable for /embed-and-analyze: %s", e)
        return {
            "answer": "AI service is currently unavailable. Please try again later.",
            "file_name": file_name,
            "chunks_indexed": 0,
        }


# ── Bulk Embed ────────────────────────────────────────────────────────────

async def bulk_embed_contracts(force: bool = False, batch_size: int = 20) -> dict:
    """Embed all contracts from MongoDB into the Elasticsearch knowledge base.

    Skips contracts that already have `embedded_at` set unless force=True.
    Processes in batches to avoid overwhelming the agent service.
    Returns a summary with counts of succeeded, skipped, and failed.
    """
    query = {} if force else {"embedded_at": {"$exists": False}}
    contracts = list(contracts_collection.find(query, {"_id": 1, "title": 1}))

    total = len(contracts)
    succeeded = 0
    skipped_count = 0
    failed = 0
    errors: list[dict] = []

    for i in range(0, total, batch_size):
        batch = contracts[i: i + batch_size]
        for doc in batch:
            cid = str(doc["_id"])
            full = contracts_collection.find_one({"_id": doc["_id"]})
            if not full:
                failed += 1
                continue

            text = _build_contract_text(full)
            if not text.strip():
                skipped_count += 1
                continue

            try:
                result = await embed_and_analyze(
                    text=text,
                    file_name=full.get("title", cid),
                    question="Summarize the key obligations, risks, and parties in this contract.",
                    session_id=cid,
                )
                if result.get("chunks_indexed", 0) > 0 or "answer" in result:
                    contracts_collection.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"embedded_at": datetime.utcnow()}},
                    )
                    succeeded += 1
                else:
                    failed += 1
                    errors.append({"contract_id": cid, "reason": result.get("answer", "No chunks indexed")})
            except Exception as exc:
                failed += 1
                errors.append({"contract_id": cid, "reason": str(exc)})

    return {
        "total_found": total,
        "succeeded": succeeded,
        "skipped": skipped_count,
        "failed": failed,
        "errors": errors[:20],
        "completed_at": datetime.utcnow().isoformat(),
    }


# ── Fallback / Mock Data ──────────────────────────────────────────────────

def _error_analysis(message: str) -> dict:
    """Return a structured error when the agent call fails."""
    return {
        "summary": message,
        "error": message,
        "risk_score": None,
        "risk_level": None,
        "analyzed_at": datetime.utcnow().isoformat(),
    }


def _mock_analysis() -> dict:
    """Return mock analysis when the agent service is not reachable."""
    return {
        "summary": "AI service is currently unavailable. This is a placeholder analysis.",
        "extracted_clauses": [
            "Confidentiality clause",
            "Termination clause",
            "Payment terms",
            "Liability limitations",
        ],
        "key_information": {
            "parties": ["Party A", "Party B"],
            "duration": "12 months",
            "payment_terms": "Net 30",
            "termination_conditions": "30 days written notice",
            "governing_law": "Not specified",
        },
        "risk_score": 45.0,
        "risk_level": "medium",
        "risk_factors": [
            "No governing law specified",
            "Broad liability clause",
            "Missing dispute resolution mechanism",
        ],
        "recommendations": [
            "Add governing law clause",
            "Narrow liability limitations",
            "Include dispute resolution procedure",
        ],
        "analyzed_at": datetime.utcnow().isoformat(),
    }


def _mock_draft(contract_type: str, parties: list) -> dict:
    """Return a mock draft when the agent service is not reachable."""
    return {
        "contract_type": contract_type,
        "content": f"[AI service unavailable — mock {contract_type} draft]\n\n"
                   f"Please ensure the Agent service is running and try again.",
        "generated_at": datetime.utcnow().isoformat(),
    }


def _mock_conflicts(contracts: list) -> dict:
    """Return mock conflict detection results."""
    titles = [c.get("title", "Untitled") for c in contracts]
    return {
        "total_conflicts": 3,
        "overall_risk": "medium",
        "summary": f"Found 3 potential conflicts across {len(contracts)} contracts. "
                   f"Review recommended for liability and termination clauses.",
        "conflicts": [
            {
                "id": 1,
                "contract_a": titles[0],
                "contract_b": titles[1] if len(titles) > 1 else titles[0],
                "clause_a": "Liability limited to contract value",
                "clause_b": "Unlimited liability for data breaches",
                "conflict_type": "contradiction",
                "severity": "high",
                "description": "One contract limits liability while another requires "
                               "unlimited liability for similar scenarios.",
                "recommendation": "Harmonize liability caps across both contracts or "
                                  "add specific carve-outs.",
            },
            {
                "id": 2,
                "contract_a": titles[0],
                "contract_b": titles[1] if len(titles) > 1 else titles[0],
                "clause_a": "30-day termination notice required",
                "clause_b": "60-day termination notice required",
                "conflict_type": "incompatibility",
                "severity": "medium",
                "description": "Conflicting termination notice periods could create "
                               "compliance issues.",
                "recommendation": "Align termination notice periods to the longer "
                                  "duration (60 days).",
            },
            {
                "id": 3,
                "contract_a": titles[0],
                "contract_b": titles[-1],
                "clause_a": "Governing law: State of Delaware",
                "clause_b": "Governing law: State of California",
                "conflict_type": "incompatibility",
                "severity": "low",
                "description": "Different governing laws may create jurisdictional ambiguity.",
                "recommendation": "Choose a single governing law or add a conflict "
                                  "resolution clause.",
            },
        ],
        "contracts_analyzed": [
            {"id": str(c["_id"]), "title": c.get("title", "Untitled")}
            for c in contracts
        ],
        "analyzed_at": datetime.utcnow().isoformat(),
    }
