from datetime import datetime
from typing import Optional
from bson import ObjectId
from app.config import contracts_collection, GEMINI_API_KEY, GEMINI_MODEL

# Lazy-load Gemini to avoid import errors if not installed
_model = None


def _get_model():
    global _model
    if _model is None:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _model = genai.GenerativeModel(GEMINI_MODEL)
    return _model


async def analyze_contract_text(contract_text: str) -> dict:
    """Use Gemini AI to analyze contract text and extract key information."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return _mock_analysis()

    try:
        model = _get_model()

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

Contract text:
{contract_text}"""

        response = model.generate_content(prompt)
        response_text = response.text.strip()

        # Try to parse JSON from the response
        import json
        # Handle markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        analysis = json.loads(response_text)
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

    # Build text from contract fields
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
    """Use AI to generate a contract draft based on parameters."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return _mock_draft(contract_type, parties)

    try:
        model = _get_model()

        parties_str = ", ".join([p.get("name", "Party") for p in parties]) if parties else "Party A, Party B"
        terms_str = "\n".join([f"- {k}: {v}" for k, v in key_terms.items()]) if key_terms else "Standard terms"

        prompt = f"""Generate a professional {contract_type} contract between {parties_str}.

Key terms:
{terms_str}

Generate a complete, professional contract with standard legal clauses.
Include sections for: Parties, Scope, Term, Payment, Confidentiality, Termination, Governing Law, and Signatures.
Return the contract as plain text."""

        response = model.generate_content(prompt)
        return {
            "contract_type": contract_type,
            "content": response.text,
            "generated_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        return {
            "error": str(e),
            "content": "AI draft generation failed. Please try again.",
            "generated_at": datetime.utcnow().isoformat(),
        }


async def ai_chat(contract_id: str, question: str) -> dict:
    """Ask AI a question about a specific contract."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return {
            "answer": "AI service is not configured. Please set your GEMINI_API_KEY in .env",
            "contract_id": contract_id,
        }

    contract = None
    if contract_id and ObjectId.is_valid(contract_id):
        contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})

    try:
        model = _get_model()

        context = ""
        if contract:
            context = f"Contract context:\n{_build_contract_text(contract)}\n\n"

        prompt = f"""{context}You are a legal AI assistant for a Contract Lifecycle Management system.
Answer the following question clearly and professionally:

{question}"""

        response = model.generate_content(prompt)
        return {
            "answer": response.text,
            "contract_id": contract_id,
        }

    except Exception as e:
        return {
            "answer": f"Error: {str(e)}",
            "contract_id": contract_id,
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


def _mock_analysis() -> dict:
    """Return mock analysis when Gemini API key is not configured."""
    return {
        "summary": "This is a mock analysis. Configure GEMINI_API_KEY for real AI analysis.",
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
    """Return a mock draft when Gemini API key is not configured."""
    return {
        "contract_type": contract_type,
        "content": f"[Mock {contract_type} contract draft]\n\nConfigure GEMINI_API_KEY for AI-generated drafts.",
        "generated_at": datetime.utcnow().isoformat(),
    }
