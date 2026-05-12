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
_TIMEOUT_CHAT = httpx.Timeout(timeout=240.0, connect=10.0)
_TIMEOUT_GENERATION = httpx.Timeout(timeout=120.0, connect=10.0)


# ── Helpers ────────────────────────────────────────────────────────────────

def _agent_url(path: str) -> str:
    """Build the full URL for an agent endpoint."""
    base = AI_PLATFORM_URL.rstrip("/")
    return f"{base}{path}"


def _build_contract_text(contract: dict) -> str:
    """Build text for AI analysis — actual document content takes priority over metadata."""
    extracted = (contract.get("extracted_text") or "").strip()
    if extracted:
        # Prepend a brief metadata header so the AI knows what it's reading,
        # then append the full document content.
        header_parts = [f"Title: {contract.get('title', 'N/A')}"]
        if contract.get("contract_type"):
            header_parts.append(f"Type: {contract['contract_type']}")
        parties = contract.get("parties", [])
        if parties:
            names = ", ".join(p.get("name", "Unknown") for p in parties)
            header_parts.append(f"Parties: {names}")
        header = "\n".join(header_parts)
        return f"{header}\n\n--- DOCUMENT CONTENT ---\n\n{extracted}"

    # Fallback: no extracted text — build from stored metadata fields only
    parts = [
        f"Title: {contract.get('title', 'N/A')}",
        f"Type: {contract.get('contract_type', 'N/A')}",
        f"Description: {contract.get('description', 'N/A')}",
        f"Status: {contract.get('status', 'N/A')}",
    ]
    if contract.get("start_date"):
        parts.append(f"Start Date: {contract['start_date']}")
    if contract.get("end_date"):
        parts.append(f"End Date: {contract['end_date']}")
    if contract.get("value"):
        parts.append(f"Value: {contract['value']}")
    if contract.get("payment_terms"):
        parts.append(f"Payment Terms: {contract['payment_terms']}")

    parties = contract.get("parties", [])
    if parties:
        party_strs = [f"  - {p.get('name', 'Unknown')} ({p.get('role', 'N/A')})" for p in parties]
        parts.append("Parties:\n" + "\n".join(party_strs))

    tags = contract.get("tags", [])
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")

    return "\n".join(parts)


def _apply_extracted_metadata(contract: dict, update_fields: dict, key_info: dict) -> None:
    """Write AI-extracted metadata into update_fields, skipping fields already set."""
    from datetime import datetime as _dt

    _DATE_FMTS = [
        "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y",
        "%d %B %Y", "%B %d, %Y", "%B %d %Y",
        "%d %b %Y", "%b %d, %Y", "%b %d %Y",
        "%Y/%m/%d",
    ]

    def _parse_date(raw: str):
        s = str(raw).strip()
        for fmt in _DATE_FMTS:
            try:
                return _dt.strptime(s, fmt)
            except ValueError:
                continue
        return None

    # Dates — only fill in if currently None/missing
    for field, key in (("start_date", "start_date"), ("end_date", "end_date")):
        if not contract.get(field) and key_info.get(key):
            raw = key_info[key]
            if raw and str(raw).strip().lower() not in ("null", "none", "n/a", ""):
                parsed = _parse_date(raw)
                if parsed:
                    update_fields[field] = parsed

    # Contract value — strip currency symbols and commas before parsing
    if contract.get("value") is None and key_info.get("contract_value"):
        raw_val = str(key_info["contract_value"])
        # Remove currency symbols, spaces, and commas
        cleaned = "".join(c for c in raw_val if c.isdigit() or c == ".")
        if cleaned:
            try:
                update_fields["value"] = float(cleaned)
            except (ValueError, TypeError):
                pass

    # Contract type — only overwrite the default "other"
    if contract.get("contract_type") in (None, "other") and key_info.get("contract_type"):
        ct = key_info["contract_type"].lower().strip()
        valid = {"nda", "service", "employment", "lease", "purchase", "partnership", "licensing", "other"}
        if ct in valid:
            update_fields["contract_type"] = ct

    # Parties — only fill if currently empty
    if not contract.get("parties") and key_info.get("parties"):
        raw_parties = key_info["parties"]
        if isinstance(raw_parties, list) and raw_parties:
            update_fields["parties"] = [
                {"name": str(p), "role": "party"} for p in raw_parties if p
            ]


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

    # Write back extracted contract metadata only if the field is currently unset
    key_info = analysis.get("key_information") or {}
    _apply_extracted_metadata(contract, update_fields, key_info)

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

async def ai_chat(
    contract_id: str,
    question: str,
    contract_text: str = None,
) -> dict:
    """Ask the agent service a question, optionally with contract context.

    Agent endpoint: POST /chat
    Supports session-based conversation continuity via session_id.
    Pass contract_text directly to skip the DB lookup (e.g. for uploaded files).
    """
    if contract_text is None and contract_id and ObjectId.is_valid(contract_id):
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
            # Enrich with contract IDs, titles, and version info for the frontend
            result["contracts_analyzed"] = [
                {
                    "id": str(c["_id"]),
                    "title": c.get("title", "Untitled"),
                    "current_version": c.get("current_version", 1),
                }
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
    """Return a full contract draft when the agent service is not reachable."""
    pa = parties[0].get("name", "Party A") if parties else "Party A"
    pb = parties[1].get("name", "Party B") if len(parties) > 1 else "Party B"
    today = datetime.utcnow().strftime("%B %d, %Y")

    type_lower = (contract_type or "").lower()
    if "nda" in type_lower or "non" in type_lower:
        content = _draft_nda(pa, pb, today)
    elif "employment" in type_lower:
        content = _draft_employment(pa, pb, today)
    elif "vendor" in type_lower:
        content = _draft_vendor(pa, pb, today)
    elif "licensing" in type_lower or "licence" in type_lower or "license" in type_lower:
        content = _draft_licensing(pa, pb, today)
    elif "partnership" in type_lower:
        content = _draft_partnership(pa, pb, today)
    else:
        content = _draft_service(pa, pb, today)

    return {
        "contract_type": contract_type,
        "content": content,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _draft_nda(pa: str, pb: str, today: str) -> str:
    return f"""# NON-DISCLOSURE AGREEMENT

**This Non-Disclosure Agreement** ("Agreement") is entered into as of {today} (the "Effective Date"), by and between:

**{pa}** ("Disclosing Party")

and

**{pb}** ("Receiving Party")

(each a "Party" and collectively the "Parties").

---

## RECITALS

WHEREAS, the Parties wish to explore a potential business relationship (the "Purpose") and, in connection therewith, the Disclosing Party may disclose certain Confidential Information to the Receiving Party;

NOW, THEREFORE, in consideration of the mutual covenants and agreements set forth herein, the Parties agree as follows:

---

## 1. DEFINITIONS

**1.1 Confidential Information.** "Confidential Information" means any non-public information disclosed by the Disclosing Party to the Receiving Party, whether orally, in writing, electronically, or by any other means, that is designated as confidential or that reasonably should be understood to be confidential given the nature of the information and circumstances of disclosure, including without limitation: trade secrets, technical data, specifications, designs, algorithms, source code, financial information, business plans, customer lists, and any other proprietary information.

**1.2 Excluded Information.** Confidential Information shall not include information that:

- is or becomes publicly available through no act or omission of the Receiving Party;
- was in the Receiving Party's possession prior to receipt without restriction on disclosure;
- is rightfully received from a third party without restriction; or
- is independently developed by the Receiving Party without use of the Confidential Information.

## 2. OBLIGATIONS OF THE RECEIVING PARTY

**2.1 Non-Disclosure.** The Receiving Party shall hold all Confidential Information in strict confidence and shall not disclose it to any third party without the prior written consent of the Disclosing Party.

**2.2 Restricted Use.** The Receiving Party shall use the Confidential Information solely for the Purpose and shall not use it for any other purpose, including to compete with the Disclosing Party.

**2.3 Standard of Care.** The Receiving Party shall protect the Confidential Information using at least the same degree of care it applies to its own most sensitive proprietary information, but in no event less than reasonable care.

**2.4 Permitted Disclosures.** The Receiving Party may disclose Confidential Information to its employees, directors, advisors, and contractors on a strict need-to-know basis, provided such persons are bound by confidentiality obligations at least as restrictive as those set forth herein.

## 3. RETURN OR DESTRUCTION

Upon the Disclosing Party's written request or termination of this Agreement, the Receiving Party shall promptly: (a) return all tangible materials containing Confidential Information; (b) permanently delete all electronic copies; and (c) certify in writing that it has complied with this Section 3.

## 4. INTELLECTUAL PROPERTY

Nothing herein shall be construed as granting the Receiving Party any licence, right, title, or interest in or to any Confidential Information or intellectual property of the Disclosing Party. All Confidential Information remains the sole and exclusive property of the Disclosing Party.

## 5. TERM

**5.1 Duration.** This Agreement commences on the Effective Date and continues for three (3) years unless earlier terminated by either Party upon thirty (30) days' written notice.

**5.2 Survival.** The obligations under Section 2 survive termination for five (5) years.

## 6. REMEDIES

The Receiving Party acknowledges that breach of this Agreement would cause irreparable harm for which monetary damages would be inadequate, and that the Disclosing Party is entitled to seek equitable relief, including injunction and specific performance, in addition to all other remedies available at law.

## 7. GENERAL PROVISIONS

**7.1 Governing Law.** This Agreement shall be governed by applicable law without regard to conflict of laws principles.

**7.2 Entire Agreement.** This Agreement constitutes the entire agreement between the Parties regarding its subject matter and supersedes all prior negotiations and understandings.

**7.3 Amendment.** This Agreement may not be amended except by a written instrument signed by both Parties.

**7.4 Severability.** If any provision is held invalid or unenforceable, the remaining provisions shall continue in full force.

**7.5 Counterparts.** This Agreement may be executed in counterparts, and electronic signatures shall be deemed valid.

---

## SIGNATURES

IN WITNESS WHEREOF, the Parties have executed this Non-Disclosure Agreement as of the date first written above.

**{pa}**

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________


**{pb}**

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________
"""


def _draft_service(pa: str, pb: str, today: str) -> str:
    return f"""# SERVICE AGREEMENT

**This Service Agreement** ("Agreement") is entered into as of {today} (the "Effective Date"), by and between:

**{pa}** ("Client")

and

**{pb}** ("Service Provider")

(each a "Party" and collectively the "Parties").

---

## RECITALS

WHEREAS, the Client desires to engage the Service Provider to perform certain services, and the Service Provider desires to provide such services to the Client, on the terms and conditions set forth herein;

NOW, THEREFORE, in consideration of the mutual covenants and the compensation described herein, the Parties agree as follows:

---

## 1. SERVICES

**1.1 Scope of Services.** The Service Provider agrees to perform the services described in Schedule A attached hereto and incorporated by reference (the "Services"). The Service Provider shall perform the Services in a professional and workmanlike manner, consistent with industry standards.

**1.2 Change Orders.** Any material change to the scope of Services shall be agreed upon in writing by both Parties prior to implementation. Changes may affect the timeline and fees.

**1.3 Personnel.** The Service Provider shall assign qualified personnel to perform the Services. The Service Provider may use subcontractors provided that the Service Provider remains responsible for all work performed.

## 2. TERM

**2.1 Commencement.** This Agreement commences on the Effective Date and continues until the Services are completed or the Agreement is terminated in accordance with Section 8.

**2.2 Milestones.** If milestones are specified in Schedule A, the Service Provider shall use commercially reasonable efforts to meet them. The Client shall not unreasonably withhold approvals required to enable the Service Provider to meet milestones.

## 3. FEES AND PAYMENT

**3.1 Fees.** The Client shall pay the Service Provider the fees set out in Schedule B. Unless otherwise specified, fees are invoiced monthly in arrears.

**3.2 Expenses.** The Client shall reimburse pre-approved out-of-pocket expenses within thirty (30) days of submission of receipts.

**3.3 Payment Terms.** All invoices are due and payable within thirty (30) days of the invoice date. Overdue amounts accrue interest at 1.5% per month.

**3.4 Taxes.** Each Party is responsible for its own applicable taxes. The Client shall withhold taxes only as required by law.

## 4. INTELLECTUAL PROPERTY

**4.1 Client Materials.** The Client retains all rights in materials, data, and information it provides to the Service Provider ("Client Materials"). The Service Provider shall use Client Materials solely to perform the Services.

**4.2 Deliverables.** Upon full payment, the Service Provider assigns to the Client all right, title, and interest in deliverables specifically created for the Client under this Agreement ("Deliverables"), excluding any pre-existing intellectual property of the Service Provider.

**4.3 Service Provider IP.** The Service Provider retains ownership of all tools, methodologies, frameworks, and pre-existing intellectual property used in performing the Services ("Service Provider IP"). To the extent any Service Provider IP is incorporated into Deliverables, the Service Provider grants the Client a non-exclusive, royalty-free, perpetual licence to use it for the purposes contemplated by this Agreement.

## 5. CONFIDENTIALITY

Each Party agrees to maintain in confidence all non-public information received from the other Party ("Confidential Information") and to use it solely for the purposes of this Agreement. This obligation survives termination of this Agreement for three (3) years.

## 6. REPRESENTATIONS AND WARRANTIES

**6.1 Service Provider.** The Service Provider represents and warrants that: (a) the Services will be performed in a professional and workmanlike manner; (b) the Deliverables will conform to agreed specifications; and (c) the Services and Deliverables will not infringe any third-party intellectual property rights.

**6.2 Client.** The Client represents and warrants that: (a) it has the authority to enter into this Agreement; and (b) Client Materials do not infringe third-party rights.

## 7. LIMITATION OF LIABILITY

**7.1 Exclusion.** Neither Party shall be liable for indirect, incidental, special, punitive, or consequential damages, even if advised of the possibility of such damages.

**7.2 Cap.** Each Party's aggregate liability under this Agreement shall not exceed the total fees paid or payable in the twelve (12) months preceding the event giving rise to liability.

## 8. TERMINATION

**8.1 Termination for Convenience.** Either Party may terminate this Agreement upon thirty (30) days' written notice.

**8.2 Termination for Cause.** Either Party may terminate immediately upon written notice if the other Party materially breaches this Agreement and fails to cure such breach within fifteen (15) days after receiving written notice of the breach.

**8.3 Effect of Termination.** Upon termination, the Client shall pay for all Services satisfactorily performed up to the termination date. Sections 4, 5, 7, and 9 survive termination.

## 9. GENERAL PROVISIONS

**9.1 Independent Contractor.** The Service Provider is an independent contractor. Nothing in this Agreement creates an employment, agency, joint venture, or partnership relationship.

**9.2 Governing Law.** This Agreement is governed by applicable law without regard to conflict of laws principles.

**9.3 Dispute Resolution.** The Parties shall attempt in good faith to resolve any dispute through negotiation. If unresolved within thirty (30) days, either Party may pursue available legal remedies.

**9.4 Entire Agreement.** This Agreement, together with all Schedules, constitutes the entire agreement between the Parties and supersedes all prior agreements relating to its subject matter.

**9.5 Amendment.** Amendments must be in writing and signed by authorised representatives of both Parties.

**9.6 Waiver.** Failure to enforce any provision shall not constitute a waiver of future enforcement.

**9.7 Severability.** If any provision is held invalid, the remaining provisions continue in full force.

---

## SCHEDULE A — SCOPE OF SERVICES

*(To be completed by the Parties)*

---

## SCHEDULE B — FEES

*(To be completed by the Parties)*

---

## SIGNATURES

IN WITNESS WHEREOF, the Parties have executed this Service Agreement as of the date first written above.

**{pa}** (Client)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________


**{pb}** (Service Provider)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________
"""


def _draft_employment(pa: str, pb: str, today: str) -> str:
    return f"""# EMPLOYMENT AGREEMENT

**This Employment Agreement** ("Agreement") is entered into as of {today} (the "Commencement Date"), by and between:

**{pa}** ("Employer")

and

**{pb}** ("Employee")

(each a "Party" and collectively the "Parties").

---

## 1. POSITION AND DUTIES

**1.1 Position.** The Employer agrees to employ the Employee in the position set out in Schedule A, and the Employee agrees to accept such employment, on the terms and conditions set forth herein.

**1.2 Duties.** The Employee shall perform the duties and responsibilities described in Schedule A and such other duties as the Employer may reasonably assign from time to time.

**1.3 Reporting.** The Employee shall report to the individual specified in Schedule A or such other person as the Employer may designate.

**1.4 Full-Time Commitment.** The Employee shall devote their full working time, attention, and efforts to the performance of their duties and shall not engage in any other business activity that creates a conflict of interest without the Employer's prior written consent.

## 2. COMMENCEMENT AND TERM

**2.1 Start Date.** Employment commences on the Commencement Date.

**2.2 Probationary Period.** The first three (3) months of employment constitute a probationary period during which either Party may terminate this Agreement on one (1) week's written notice.

**2.3 Ongoing Employment.** Following the probationary period, this Agreement continues until terminated in accordance with Section 8.

## 3. COMPENSATION

**3.1 Base Salary.** The Employee shall receive the base salary set out in Schedule B, payable in equal instalments in accordance with the Employer's regular payroll cycle.

**3.2 Review.** Salary shall be reviewed annually at the discretion of the Employer. No review creates an entitlement to any increase.

**3.3 Benefits.** The Employee is entitled to the benefits set out in Schedule B, subject to the terms of the applicable benefit plans.

**3.4 Expenses.** The Employer shall reimburse reasonable pre-approved business expenses upon submission of receipts.

## 4. WORKING HOURS AND LOCATION

**4.1 Hours.** The Employee shall work the hours set out in Schedule A and such additional hours as are reasonably necessary to fulfil their duties.

**4.2 Location.** The Employee's primary place of work is the location specified in Schedule A, subject to travel requirements.

## 5. LEAVE ENTITLEMENTS

**5.1 Annual Leave.** The Employee is entitled to the annual leave specified in Schedule B per year, accrued pro rata.

**5.2 Sick Leave.** The Employee is entitled to paid sick leave in accordance with applicable law and the Employer's policies.

**5.3 Public Holidays.** The Employee is entitled to all statutory public holidays.

## 6. CONFIDENTIALITY AND INTELLECTUAL PROPERTY

**6.1 Confidential Information.** During and after employment, the Employee shall maintain in strict confidence all trade secrets, business plans, client information, financial data, and other proprietary information of the Employer.

**6.2 Intellectual Property.** All work product, inventions, software, and other intellectual property created by the Employee in the course of their duties belongs exclusively to the Employer. The Employee hereby assigns all such intellectual property to the Employer.

**6.3 Return of Property.** Upon termination, the Employee shall immediately return all Employer property, including devices, documents, and access credentials.

## 7. RESTRICTIVE COVENANTS

**7.1 Non-Compete.** For a period of twelve (12) months following termination, the Employee shall not engage in any business activity that directly competes with the Employer's business within the geographic area specified in Schedule A.

**7.2 Non-Solicitation.** For a period of twelve (12) months following termination, the Employee shall not solicit the Employer's clients, customers, or employees.

**7.3 Reasonableness.** The Employee acknowledges that the restrictions in this Section are reasonable and necessary to protect the Employer's legitimate business interests.

## 8. TERMINATION

**8.1 Notice by Employer.** Following the probationary period, the Employer may terminate this Agreement by providing the notice period set out in Schedule B or payment in lieu thereof, except in cases of summary dismissal.

**8.2 Summary Dismissal.** The Employer may terminate this Agreement immediately without notice or payment in lieu in cases of serious misconduct, gross negligence, or material breach.

**8.3 Resignation.** The Employee may resign upon providing the notice period set out in Schedule B.

**8.4 Effect of Termination.** Upon termination, the Employee shall receive all accrued and unpaid remuneration. No further amounts are owed unless otherwise required by law.

## 9. GENERAL PROVISIONS

**9.1 Entire Agreement.** This Agreement constitutes the entire agreement between the Parties regarding the Employee's employment and supersedes all prior agreements.

**9.2 Governing Law.** This Agreement is governed by applicable employment law.

**9.3 Amendment.** Amendments must be in writing and signed by both Parties.

**9.4 Severability.** If any provision is held invalid, the remaining provisions continue in full force.

---

## SCHEDULE A — POSITION DETAILS

- **Position Title:** ___________________________
- **Reporting To:** ___________________________
- **Place of Work:** ___________________________
- **Working Hours:** ___________________________

---

## SCHEDULE B — REMUNERATION AND BENEFITS

- **Annual Base Salary:** ___________________________
- **Notice Period:** ___________________________
- **Annual Leave:** ___________________________
- **Benefits:** ___________________________

---

## SIGNATURES

IN WITNESS WHEREOF, the Parties have executed this Employment Agreement as of the date first written above.

**{pa}** (Employer)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________


**{pb}** (Employee)

Signature: ___________________________

Date: ________________________________
"""


def _draft_vendor(pa: str, pb: str, today: str) -> str:
    return f"""# VENDOR AGREEMENT

**This Vendor Agreement** ("Agreement") is entered into as of {today} (the "Effective Date"), by and between:

**{pa}** ("Buyer")

and

**{pb}** ("Vendor")

(each a "Party" and collectively the "Parties").

---

## 1. SUPPLY OF GOODS AND/OR SERVICES

**1.1 Purchase Orders.** The Buyer may issue purchase orders to the Vendor from time to time specifying the goods and/or services required ("Goods/Services"), quantities, prices, and delivery dates. Each accepted purchase order forms a binding contract incorporating the terms of this Agreement.

**1.2 Acceptance.** A purchase order is accepted when the Vendor provides written acknowledgement or commences performance. The Vendor may reject a purchase order within five (5) business days of receipt.

**1.3 Specifications.** The Vendor shall supply Goods/Services that conform strictly to the specifications, standards, and requirements set out in each purchase order and Schedule A.

## 2. DELIVERY AND RISK

**2.1 Delivery.** The Vendor shall deliver Goods/Services by the dates specified in each purchase order. Time is of the essence. Failure to deliver on time may result in liquidated damages as specified in Schedule B.

**2.2 Risk of Loss.** Risk of loss transfers to the Buyer upon delivery to the delivery address specified in the purchase order and acceptance by the Buyer.

**2.3 Inspection.** The Buyer shall inspect Goods/Services within ten (10) business days of delivery. Goods/Services not rejected within this period are deemed accepted, subject to latent defects.

## 3. PRICE AND PAYMENT

**3.1 Pricing.** Prices are as set out in the applicable purchase order and may not be varied without the Buyer's prior written consent.

**3.2 Invoicing.** The Vendor shall submit invoices upon delivery. Invoices must reference the applicable purchase order number and include all information required by the Buyer.

**3.3 Payment Terms.** The Buyer shall pay undisputed invoices within thirty (30) days of receipt.

**3.4 Set-Off.** The Buyer may set off against amounts payable any amounts owed by the Vendor.

## 4. WARRANTIES

**4.1 Vendor Warranties.** The Vendor warrants that: (a) all Goods are new, merchantable, and fit for their intended purpose; (b) Services are performed in a professional and workmanlike manner; (c) Goods/Services conform to all applicable specifications and laws; and (d) Goods/Services do not infringe any third-party intellectual property rights.

**4.2 Warranty Period.** Warranties in Section 4.1 survive for twelve (12) months after delivery unless otherwise specified.

**4.3 Remedy.** If the Vendor breaches any warranty, the Buyer may require the Vendor to, at the Buyer's option, repair or replace defective Goods or re-perform non-conforming Services at no additional cost.

## 5. COMPLIANCE AND ETHICS

**5.1 Legal Compliance.** The Vendor shall comply with all applicable laws, regulations, and standards in performing its obligations.

**5.2 Anti-Bribery.** The Vendor shall not engage in any form of bribery, corruption, or unethical conduct in connection with this Agreement.

**5.3 Sustainability.** The Vendor shall conduct its operations in an environmentally responsible manner consistent with the Buyer's sustainability policies as communicated from time to time.

## 6. CONFIDENTIALITY

Each Party agrees to maintain in confidence all non-public information received from the other Party and to use it solely for the purposes of this Agreement. This obligation survives termination for three (3) years.

## 7. LIMITATION OF LIABILITY

**7.1 Exclusions.** Neither Party shall be liable for indirect, incidental, or consequential damages.

**7.2 Cap.** Each Party's aggregate liability is capped at the total value of purchase orders placed in the twelve (12) months preceding the event giving rise to liability, except for breaches of confidentiality, intellectual property, or indemnification obligations.

## 8. TERMINATION

**8.1 Termination for Convenience.** Either Party may terminate this Agreement on sixty (60) days' written notice. Outstanding purchase orders accepted prior to notice shall be fulfilled.

**8.2 Termination for Cause.** Either Party may terminate immediately if the other materially breaches this Agreement and fails to cure within fifteen (15) days of written notice.

## 9. GENERAL PROVISIONS

**9.1 Relationship.** The Vendor is an independent contractor. Nothing herein creates employment, agency, or partnership.

**9.2 Governing Law.** This Agreement is governed by applicable law.

**9.3 Entire Agreement.** This Agreement and all purchase orders constitute the entire agreement and supersede all prior understandings.

**9.4 Amendment.** Amendments require written agreement signed by both Parties.

---

## SIGNATURES

IN WITNESS WHEREOF, the Parties have executed this Vendor Agreement as of the date first written above.

**{pa}** (Buyer)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________


**{pb}** (Vendor)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________
"""


def _draft_licensing(pa: str, pb: str, today: str) -> str:
    return f"""# SOFTWARE LICENSING AGREEMENT

**This Licensing Agreement** ("Agreement") is entered into as of {today} (the "Effective Date"), by and between:

**{pa}** ("Licensor")

and

**{pb}** ("Licensee")

(each a "Party" and collectively the "Parties").

---

## 1. GRANT OF LICENCE

**1.1 Licence.** Subject to the terms of this Agreement and payment of all applicable fees, the Licensor hereby grants the Licensee a non-exclusive, non-transferable, revocable licence to use the software, documentation, and related materials specified in Schedule A (collectively, the "Licensed Materials") solely for the Licensee's internal business purposes.

**1.2 Restrictions.** The Licensee shall not: (a) sublicence, sell, resell, transfer, assign, or otherwise exploit the Licensed Materials; (b) modify, adapt, translate, reverse engineer, decompile, disassemble, or create derivative works based on the Licensed Materials; (c) remove or alter any proprietary notices; or (d) use the Licensed Materials for any unlawful purpose.

**1.3 Permitted Users.** The licence extends only to the Licensee's authorised employees and contractors who need access to perform their duties for the Licensee.

## 2. INTELLECTUAL PROPERTY

All right, title, and interest in and to the Licensed Materials, including all intellectual property rights, remain exclusively with the Licensor. This Agreement does not transfer any ownership rights. The Licensee acknowledges that the Licensed Materials constitute valuable trade secrets and proprietary information of the Licensor.

## 3. LICENCE FEES

**3.1 Fees.** The Licensee shall pay the licence fees specified in Schedule B in accordance with the payment schedule set out therein.

**3.2 Late Payment.** Overdue amounts accrue interest at 1.5% per month from the due date until paid.

**3.3 No Refunds.** Except as expressly provided herein, all fees paid are non-refundable.

## 4. SUPPORT AND MAINTENANCE

**4.1 Support.** During the term, the Licensor shall provide support services as described in Schedule C.

**4.2 Updates.** The Licensor shall provide updates and patches to the Licensed Materials as they become generally available to licensees at the applicable support tier.

## 5. CONFIDENTIALITY

Each Party shall maintain in confidence all non-public information of the other Party and use it solely for the purposes of this Agreement. The Licensed Materials are confidential information of the Licensor. This obligation survives termination for five (5) years.

## 6. WARRANTIES AND DISCLAIMERS

**6.1 Licensor Warranty.** The Licensor warrants that the Licensed Materials will perform materially in accordance with the documentation for ninety (90) days from the Effective Date.

**6.2 Disclaimer.** EXCEPT AS EXPRESSLY PROVIDED IN SECTION 6.1, THE LICENSED MATERIALS ARE PROVIDED "AS IS" AND THE LICENSOR DISCLAIMS ALL OTHER WARRANTIES, EXPRESS OR IMPLIED.

## 7. LIMITATION OF LIABILITY

IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR INDIRECT, INCIDENTAL, SPECIAL, PUNITIVE, OR CONSEQUENTIAL DAMAGES. THE LICENSOR'S AGGREGATE LIABILITY SHALL NOT EXCEED THE FEES PAID IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM.

## 8. TERM AND TERMINATION

**8.1 Term.** This Agreement commences on the Effective Date and continues for the period specified in Schedule B, unless earlier terminated.

**8.2 Termination for Breach.** Either Party may terminate upon thirty (30) days' written notice if the other materially breaches this Agreement and fails to cure within such period.

**8.3 Effect.** Upon termination, all licences granted hereunder immediately cease, and the Licensee shall destroy all copies of the Licensed Materials and certify such destruction in writing.

## 9. GENERAL PROVISIONS

**9.1 Governing Law.** This Agreement is governed by applicable law.

**9.2 Entire Agreement.** This Agreement constitutes the entire agreement regarding the Licensed Materials and supersedes all prior agreements.

**9.3 Amendment.** Amendments must be in writing and signed by both Parties.

---

## SIGNATURES

**{pa}** (Licensor)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________


**{pb}** (Licensee)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________
"""


def _draft_partnership(pa: str, pb: str, today: str) -> str:
    return f"""# PARTNERSHIP AGREEMENT

**This Partnership Agreement** ("Agreement") is entered into as of {today} (the "Effective Date"), by and between:

**{pa}** ("Partner A")

and

**{pb}** ("Partner B")

(each a "Partner" and collectively the "Partners").

---

## 1. FORMATION AND PURPOSE

**1.1 Partnership.** The Partners hereby agree to form a general partnership (the "Partnership") for the purpose described in Schedule A (the "Business Purpose").

**1.2 Name.** The Partnership shall conduct business under the name specified in Schedule A or such other name as the Partners may agree in writing.

**1.3 Principal Place of Business.** The Partnership's principal place of business is the address set out in Schedule A.

## 2. CAPITAL CONTRIBUTIONS

**2.1 Initial Contributions.** Each Partner shall contribute to the Partnership the capital specified in Schedule B ("Capital Contribution") within thirty (30) days of the Effective Date.

**2.2 Additional Contributions.** Additional capital contributions shall require unanimous written consent of the Partners.

**2.3 No Interest.** No Partner shall be entitled to interest on their Capital Contribution unless otherwise agreed in writing.

## 3. PROFIT AND LOSS SHARING

**3.1 Distribution.** Net profits and net losses of the Partnership shall be allocated between the Partners in the proportions set out in Schedule B.

**3.2 Distributions.** Distributions shall be made at such times and in such amounts as the Partners unanimously agree, provided that no distribution shall be made that renders the Partnership unable to pay its debts as they fall due.

**3.3 Drawings.** Partners may draw against anticipated profit allocations with unanimous consent, subject to Schedule B.

## 4. MANAGEMENT AND DECISION-MAKING

**4.1 Management.** The Partners shall manage the Partnership jointly. Each Partner shall have equal rights in the management of Partnership business, except where this Agreement provides otherwise.

**4.2 Ordinary Decisions.** Ordinary business decisions may be made by majority vote of the Partners.

**4.3 Major Decisions.** The following decisions require unanimous written consent of all Partners: (a) admitting a new partner; (b) dissolving the Partnership; (c) making capital expenditures above the threshold in Schedule B; (d) incurring debt above the threshold in Schedule B; (e) entering into contracts outside the ordinary course of business; and (f) amending this Agreement.

**4.4 Designated Roles.** Each Partner's designated role and responsibilities are set out in Schedule A.

## 5. PARTNER DUTIES

**5.1 Fiduciary Duties.** Each Partner owes fiduciary duties to the Partnership and to each other Partner, including duties of loyalty, good faith, and fair dealing.

**5.2 Time Commitment.** Each Partner shall devote the time and attention to Partnership business as specified in Schedule A.

**5.3 Non-Compete.** During the term of this Agreement and for twelve (12) months following dissolution, no Partner shall engage in any business that directly competes with the Partnership without the written consent of all other Partners.

## 6. BANKING AND ACCOUNTS

All Partnership funds shall be deposited in a bank account opened in the Partnership's name. Withdrawals shall require the signature of both Partners or as otherwise specified in Schedule B.

## 7. BOOKS AND RECORDS

The Partners shall maintain complete and accurate books of account in accordance with applicable accounting standards. Each Partner shall have full access to the Partnership's books and records at all times.

## 8. ADMISSION OF NEW PARTNERS

No new partner may be admitted to the Partnership without the unanimous written consent of all existing Partners and the execution of an amendment to this Agreement.

## 9. WITHDRAWAL AND DISSOLUTION

**9.1 Voluntary Withdrawal.** A Partner may withdraw from the Partnership upon ninety (90) days' written notice to the other Partners.

**9.2 Buyout.** Upon withdrawal, the remaining Partners have the option to purchase the withdrawing Partner's interest at fair market value as determined by an independent valuer.

**9.3 Dissolution.** The Partnership shall be dissolved: (a) by unanimous written agreement of all Partners; (b) upon the death, bankruptcy, or legal incapacity of a Partner where the remaining Partners elect not to continue; or (c) as required by law.

**9.4 Winding Up.** Upon dissolution, the Partnership's assets shall be liquidated and applied in the following order: (i) payment of Partnership debts; (ii) repayment of Capital Contributions; (iii) distribution of remaining assets in proportion to profit-sharing ratios.

## 10. GENERAL PROVISIONS

**10.1 Governing Law.** This Agreement is governed by applicable law.

**10.2 Entire Agreement.** This Agreement constitutes the entire agreement between the Partners and supersedes all prior agreements.

**10.3 Amendment.** Amendments require unanimous written agreement of all Partners.

**10.4 Severability.** If any provision is held invalid, the remaining provisions continue in full force.

---

## SIGNATURES

IN WITNESS WHEREOF, the Partners have executed this Partnership Agreement as of the date first written above.

**{pa}** (Partner A)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________


**{pb}** (Partner B)

Signature: ___________________________

Name: _______________________________

Title: ________________________________

Date: ________________________________
"""


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
