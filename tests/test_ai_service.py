"""
test_ai_service.py
Complete white-box + requirements test suite for ai_service.py
FR-ACA-01–07, FR-RSA-01–03, FR-CAS-04, FR-CCM-01–03
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import json
import app.services.ai_service as ai_module


def make_contract(title="NDA", parties=None, tags=None):
    return {"_id": ObjectId(), "title": title, "contract_type": "nda", "description": "Standard NDA", "status": "active", "start_date": datetime(2025,1,1), "end_date": datetime(2026,1,1), "value": 50000.0, "payment_terms": "Net 30", "parties": parties or [{"name": "Acme Corp", "role": "client"}], "tags": tags or ["legal"], "created_by": "user_001", "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()}


def ai_json(risk_score=35.0, risk_level="low"):
    return json.dumps({"summary": "A standard NDA.", "extracted_clauses": [{"clause_type": "confidentiality", "text": "Both parties agree..."}], "key_information": {"parties": ["Acme"], "duration": "12 months", "payment_terms": "Net 30"}, "risk_score": risk_score, "risk_level": risk_level, "risk_factors": ["Short notice period"], "recommendations": ["Extend notice to 30 days"]})


class TestAnalyzeContractText:

    @pytest.mark.asyncio
    async def test_no_api_key_returns_mock_analysis(self):
        with patch.object(ai_module, "GEMINI_API_KEY", ""):
            result = await ai_module.analyze_contract_text("some text")
        assert "summary" in result and result["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_placeholder_key_returns_mock_analysis(self):
        with patch.object(ai_module, "GEMINI_API_KEY", "your_gemini_api_key_here"):
            result = await ai_module.analyze_contract_text("some text")
        assert "summary" in result and result["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_real_key_calls_gemini_and_parses_json(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json(35.0, "low"))
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("Contract text")
        assert result["risk_score"] == 35.0 and result["risk_level"] == "low" and "analyzed_at" in result

    @pytest.mark.asyncio
    async def test_gemini_exception_returns_error_dict(self):
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API timeout")
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert "error" in result and result["risk_score"] is None and len(str(result["error"])) > 0

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped_before_parse(self):
        fenced = f"```json\n{ai_json(50.0)}\n```"
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=fenced)
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert result["risk_score"] == 50.0

    @pytest.mark.asyncio
    async def test_response_contains_extracted_clauses(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json())
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert "extracted_clauses" in result and isinstance(result["extracted_clauses"], list)

    @pytest.mark.asyncio
    async def test_response_contains_key_information(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json())
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        ki = result.get("key_information", {})
        assert "parties" in ki and "payment_terms" in ki

    @pytest.mark.asyncio
    async def test_response_contains_risk_factors(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json())
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert "risk_factors" in result and isinstance(result["risk_factors"], list)

    @pytest.mark.asyncio
    async def test_response_contains_recommendations(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json())
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert "recommendations" in result and isinstance(result["recommendations"], list)

    @pytest.mark.asyncio
    async def test_risk_score_within_0_to_100(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json(75.0, "high"))
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert 0 <= result["risk_score"] <= 100

    @pytest.mark.asyncio
    async def test_low_risk_level_returned(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json(20.0, "low"))
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert result["risk_level"] == "low"

    @pytest.mark.asyncio
    async def test_medium_risk_level_returned(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json(55.0, "medium"))
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert result["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_high_risk_level_returned(self):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=ai_json(85.0, "high"))
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")
        assert result["risk_level"] == "high"


class TestAnalyzeContractById:

    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self):
        with patch.object(ai_module, "contracts_collection") as mock_col:
            result = await ai_module.analyze_contract_by_id("not-valid-id")
        assert result is None
        mock_col.find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_contract_not_found_returns_none(self):
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = None
            assert await ai_module.analyze_contract_by_id(str(ObjectId())) is None

    @pytest.mark.asyncio
    async def test_contract_found_analysis_stored(self):
        contract = make_contract()
        with patch.object(ai_module, "GEMINI_API_KEY", ""), patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = contract
            mock_col.update_one.return_value = MagicMock()
            result = await ai_module.analyze_contract_by_id(str(contract["_id"]))
        assert result is not None and "contract_id" in result
        mock_col.update_one.assert_called_once()
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "ai_analysis" in payload and "updated_at" in payload


class TestDetectConflicts:

    @pytest.mark.asyncio
    async def test_fewer_than_2_contracts_returns_error(self):
        contract = make_contract()
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = contract
            result = await ai_module.detect_conflicts([str(contract["_id"])])
        assert "error" in result and result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_invalid_ids_skipped(self):
        with patch.object(ai_module, "contracts_collection") as mock_col:
            result = await ai_module.detect_conflicts(["bad-1", "bad-2"])
        assert "error" in result
        mock_col.find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_api_key_returns_mock_conflicts(self):
        c1, c2 = make_contract("NDA"), make_contract("SLA")
        with patch.object(ai_module, "GEMINI_API_KEY", ""), patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.side_effect = [c1, c2]
            result = await ai_module.detect_conflicts([str(c1["_id"]), str(c2["_id"])])
        assert result["total_conflicts"] > 0 and "conflicts" in result

    @pytest.mark.asyncio
    async def test_conflict_count_matches_list_length(self):
        c1, c2 = make_contract("NDA"), make_contract("SLA")
        with patch.object(ai_module, "GEMINI_API_KEY", ""), patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.side_effect = [c1, c2]
            result = await ai_module.detect_conflicts([str(c1["_id"]), str(c2["_id"])])
        assert result["total_conflicts"] == len(result["conflicts"])

    @pytest.mark.asyncio
    async def test_real_api_conflict_result_parsed(self):
        c1, c2 = make_contract("NDA"), make_contract("SLA")
        conflict_json = json.dumps({"total_conflicts": 1, "conflicts": [{"conflict_type": "termination_clause", "severity": "high", "description": "Contradictory periods"}], "summary": "1 conflict."})
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=conflict_json)
        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), patch.object(ai_module, "_get_model", return_value=mock_model), patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.side_effect = [c1, c2]
            result = await ai_module.detect_conflicts([str(c1["_id"]), str(c2["_id"])])
        assert result["conflicts"][0]["severity"] == "high"


class TestBuildContractText:

    def test_basic_fields_included(self):
        assert "Service Agreement" in ai_module._build_contract_text(make_contract(title="Service Agreement"))

    def test_parties_included_when_present(self):
        contract = make_contract()
        contract["parties"] = [{"name": "Acme Corp", "role": "client"}, {"name": "DevCo", "role": "vendor"}]
        assert "Acme Corp" in ai_module._build_contract_text(contract)

    def test_parties_omitted_when_empty(self):
        contract = make_contract()
        contract["parties"] = []
        assert "Parties:" not in ai_module._build_contract_text(contract)

    def test_tags_included_when_present(self):
        contract = make_contract(tags=["legal", "nda", "priority"])
        assert "legal" in ai_module._build_contract_text(contract)

    def test_tags_omitted_when_empty(self):
        contract = make_contract(tags=[])
        assert "Tags:" not in ai_module._build_contract_text(contract)

    def test_payment_terms_included(self):
        contract = make_contract()
        contract["payment_terms"] = "Net 60"
        assert "Net 60" in ai_module._build_contract_text(contract)

    def test_dates_included(self):
        result = ai_module._build_contract_text(make_contract())
        assert "2025" in result and "2026" in result


class TestScanContractAgainstExisting:

    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_error(self):
        result = await ai_module.scan_contract_against_existing("not-valid")
        assert "error" in result and result["total_conflicts"] == 0 and result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_no_other_contracts_returns_conflict_free(self):
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find.return_value.sort.return_value.limit.return_value = iter([])
            result = await ai_module.scan_contract_against_existing(str(ObjectId()))
        assert result["total_conflicts"] == 0 and "summary" in result