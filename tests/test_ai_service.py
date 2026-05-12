import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import json
import app.services.ai_service as ai_module


def make_contract(title="NDA", tags=None, parties=None):
    return {
        "_id": ObjectId(),
        "title": title,
        "contract_type": "nda",
        "status": "active",
        "start_date": datetime(2025, 1, 1),
        "end_date": datetime(2026, 1, 1),
        "parties": parties if parties is not None else [{"name": "Acme"}],
        "tags": tags if tags is not None else ["legal"],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


def ai_json(risk_score=35.0):
    return json.dumps({
        "summary": "A standard NDA.",
        "extracted_clauses": [],
        "key_information": {},
        "risk_score": risk_score,
        "risk_level": "low",
        "risk_factors": [],
        "recommendations": [],
    })


class TestAnalyzeContractText:

    @pytest.mark.asyncio
    async def test_no_api_key_returns_mock_analysis(self):
        """TC-AI-01: Mock analysis when no API key"""
        with patch.object(ai_module, "GEMINI_API_KEY", ""):
            result = await ai_module.analyze_contract_text("some text")
        assert "summary" in result
        assert result["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_placeholder_key_returns_mock_analysis(self):
        """TC-AI-02: Mock analysis when placeholder API key is used"""
        with patch.object(ai_module, "GEMINI_API_KEY", "your_gemini_api_key_here"):
            result = await ai_module.analyze_contract_text("some text")
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_real_key_calls_gemini_and_parses_json(self):
        """TC-AI-03: Real Gemini API call"""
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json(35.0))
        
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), \
             patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("Contract text")
        
        assert result["risk_score"] == 35.0
        assert "analyzed_at" in result

    @pytest.mark.asyncio
    async def test_gemini_exception_returns_error_dict(self):
        """TC-AI-04: Error handling"""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API timeout")
        
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), \
             patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        
        assert "error" in result
        assert result["risk_score"] is None

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped_before_parse(self):
        """TC-AI-05: JSON fence stripping"""
        fenced = f"```json\n{ai_json(50.0)}\n```"
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=fenced)
        
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), \
             patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        
        assert result["risk_score"] == 50.0


class TestAnalyzeContractById:

    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self):
        """TC-AI-06: Input validation"""
        with patch.object(ai_module, "contracts_collection") as mock_col:
            result = await ai_module.analyze_contract_by_id("not-valid-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_contract_not_found_returns_none(self):
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = None
            result = await ai_module.analyze_contract_by_id(str(ObjectId()))
        assert result is None

    @pytest.mark.asyncio
    async def test_contract_found_analysis_stored(self):
        """TC-AI-08: Analysis stored on contract"""
        contract = make_contract()
        with patch.object(ai_module, "GEMINI_API_KEY", ""), \
             patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = contract
            mock_col.update_one.return_value = MagicMock()
            result = await ai_module.analyze_contract_by_id(str(contract["_id"]))
        
        assert result is not None
        mock_col.update_one.assert_called_once()


class TestDetectConflicts:

    @pytest.mark.asyncio
    async def test_fewer_than_2_contracts_returns_error(self):
        """TC-AI-09: Require 2+ contracts"""
        contract = make_contract()
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = contract
            result = await ai_module.detect_conflicts([str(contract["_id"])])
        
        assert "error" in result
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_invalid_ids_skipped(self):
        """TC-AI-10: Invalid IDs silently skipped"""
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = None
            result = await ai_module.detect_conflicts(["bad-1", "bad-2"])
        
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_api_key_returns_mock_conflicts(self):
        """TC-AI-11: Mock conflicts when no API key"""
        c1, c2 = make_contract("NDA"), make_contract("SLA")
        with patch.object(ai_module, "GEMINI_API_KEY", ""), \
             patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.side_effect = [c1, c2]
            result = await ai_module.detect_conflicts([str(c1["_id"]), str(c2["_id"])])
        
        assert result["total_conflicts"] > 0
        assert len(result["conflicts"]) > 0


class TestBuildContractText:

    def test_basic_fields_included(self):
        """TC-AI-12: Contract text building"""
        contract = make_contract(title="Service Agreement")
        result = ai_module._build_contract_text(contract)
        assert "Service Agreement" in result

    def test_parties_included_when_present(self):
        contract = make_contract(parties=[{"name": "Acme Corp", "role": "Vendor"}])
        result = ai_module._build_contract_text(contract)
        assert "Acme Corp" in result

    def test_parties_omitted_when_empty(self):
        contract = make_contract(parties=[])
        result = ai_module._build_contract_text(contract)
        assert "Parties:" not in result

    def test_tags_included_when_present(self):
        contract = make_contract(tags=["legal", "priority"])
        result = ai_module._build_contract_text(contract)
        assert "legal" in result

    def test_tags_omitted_when_empty(self):
        """Tags not shown when empty list"""
        contract = make_contract(tags=[])
        result = ai_module._build_contract_text(contract)
        assert "Tags:" not in result


class TestScanContractAgainstExisting:

    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_error(self):
        """TC-AI-17: Input validation"""
        result = await ai_module.scan_contract_against_existing("not-valid")
        assert "error" in result
        assert result["total_conflicts"] == 0

    @pytest.mark.asyncio
    async def test_no_other_contracts_returns_conflict_free(self):
        """TC-AI-18: No conflicts when alone"""
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find.return_value.sort.return_value.limit.return_value = iter([])
            result = await ai_module.scan_contract_against_existing(str(ObjectId()))
        
        assert result["total_conflicts"] == 0
        assert "conflict-free" in result["summary"]