import httpx
from datetime import datetime
from typing import Optional
from bson import ObjectId
from app.config import contracts_collection, AI_PLATFORM_URL

# Shared HTTP client timeout (seconds)
_TIMEOUT = 60.0


def _platform_url(path: str) -> str:
    return f"{AI_PLATFORM_URL}{path}"


async def analyze_contract_text(contract_text: str) -> dict:
    """Send contract text to the AI platform for structured analysis."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _platform_url("/analyze-text"),
                json={"text": contract_text},
            )
            resp.raise_for_status()
            analysis = resp.json()
            analysis["analyzed_at"] = datetime.utcnow().isoformat()
            return analysis
    except Exception as e:
        return {
            "error": str(e),
            "summary": "AI analysis failed. Please try again.",
            "risk_score": None,
            "risk_level": None,
            "analyzed_at": datetime.utcnow().isoformat(),
        }


async def analyze_contract_by_id(contract_id: str) -> Optional[dict]:
    """Analyze a contract from the database by its ID."""
    if not ObjectId.is_valid(contract_id):
        return None

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        return None

    contract_text = _build_contract_text(contract)
    analysis = await analyze_contract_text(contract_text)

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
        }}
    )

    analysis["contract_id"] = contract_id
    return analysis


async def generate_contract_draft(
    contract_type: str,
    parties: list,
    key_terms: dict,
) -> dict:
    """Delegate draft generation to the AI platform."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _platform_url("/generate-draft"),
                json={
                    "contract_type": contract_type,
                    "parties": parties or [],
                    "key_terms": key_terms or {},
                },
            )
            resp.raise_for_status()
            result = resp.json()
            result["generated_at"] = datetime.utcnow().isoformat()
            return result
    except Exception as e:
        return {
            "error": str(e),
            "content": "AI draft generation failed. Please try again.",
            "generated_at": datetime.utcnow().isoformat(),
        }


async def ai_chat(contract_id: str, question: str, contract_text: str | None = None, session_id: str | None = None) -> dict:
    """Delegate AI chat to the platform, passing contract context if available."""
    if not contract_text and contract_id and ObjectId.is_valid(contract_id):
        contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
        if contract:
            contract_text = _build_contract_text(contract)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            payload = {"question": question}
            if contract_text:
                payload["contract_text"] = contract_text
            if session_id:
                payload["session_id"] = session_id

            resp = await client.post(
                _platform_url("/chat"),
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            result["contract_id"] = contract_id
            return result
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {
                "answer": "The AI service is currently busy. Please wait a minute and try again.",
                "contract_id": contract_id,
            }
        return {
            "answer": "The AI service encountered an issue. Please try again later.",
            "contract_id": contract_id,
        }
    except httpx.ConnectError:
        return {
            "answer": "Unable to reach the AI service. Please make sure it is running and try again.",
            "contract_id": contract_id,
        }
    except Exception:
        return {
            "answer": "Something went wrong while contacting the AI service. Please try again later.",
            "contract_id": contract_id,
        }


async def embed_and_analyze(
    document_text: str,
    file_name: str,
    question: str,
    session_id: str | None = None,
) -> dict:
    """Send extracted document text to the AI platform for embedding and analysis."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "text": document_text,
                "file_name": file_name,
                "question": question,
            }
            if session_id:
                payload["session_id"] = session_id

            resp = await client.post(
                _platform_url("/embed-and-analyze"),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {
                "answer": "The AI service is currently busy. Please wait a minute and try again.",
            }
        return {
            "answer": "The AI service encountered an issue. Please try again later.",
        }
    except httpx.ConnectError:
        return {
            "answer": "Unable to reach the AI service. Please make sure it is running and try again.",
        }
    except Exception:
        return {
            "answer": "Something went wrong while contacting the AI service. Please try again later.",
        }


async def detect_conflicts(contract_ids: list[str]) -> dict:
    """Fetch contracts from DB and delegate conflict detection to the AI platform."""
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

    try:
        contract_payloads = [
            {
                "title": c.get("title", "Untitled"),
                "text": _build_contract_text(c),
            }
            for c in contracts
        ]

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _platform_url("/detect-conflicts"),
                json={"contracts": contract_payloads},
            )
            resp.raise_for_status()
            result = resp.json()
            result["analyzed_at"] = datetime.utcnow().isoformat()
            result["contracts_analyzed"] = [
                {"id": str(c["_id"]), "title": c.get("title", "Untitled")}
                for c in contracts
            ]
            return result
    except Exception as e:
        return {
            "error": str(e),
            "conflicts": [],
            "total_conflicts": 0,
            "analyzed_at": datetime.utcnow().isoformat(),
        }


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
