import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime

import app.services.ai_service as ai_module


def make_contract(title="NDA", contract_type="nda"):
    return {
        "_id":           ObjectId(),
        "title":         title,
        "contract_type": contract_type,
        "description":   "Standard NDA agreement",
        "status":        "active",
        "start_date":    datetime(2025, 1, 1),
        "end_date":      datetime(2026, 1, 1),
        "value":         50000.0,
        "payment_terms": "Net 30",
        "parties":       [{"name": "Acme Corp", "role": "client"}],
        "tags":          ["legal"],
        "created_by":    "user_001",
        "created_at":    datetime.utcnow(),
        "updated_at":    datetime.utcnow(),
    }


class TestAnalyzeContractText:

    @pytest.mark.asyncio
    async def test_no_api_key_returns_mock_analysis(self):
        """PATH P1 — Empty key → mock returned. Branch: no key TRUE"""
        with patch.object(ai_module, "GEMINI_API_KEY", ""):
            result = await ai_module.analyze_contract_text("some contract text")
        assert "summary"    in result
        assert "risk_score" in result
        assert result["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_placeholder_key_returns_mock_analysis(self):
        """PATH P1b — Placeholder key → mock. Branch: placeholder key TRUE"""
        with patch.object(ai_module, "GEMINI_API_KEY", "your_gemini_api_key_here"):
            result = await ai_module.analyze_contract_text("some contract text")
        assert "summary" in result
        assert result["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_real_key_calls_gemini_and_parses_json(self):
        """PATH P2 — Real key → Gemini called, JSON parsed."""
        import json
        mock_response_text = json.dumps({
            "summary": "A standard NDA.", "extracted_clauses": [],
            "key_information": {}, "risk_score": 35.0,
            "risk_level": "low", "risk_factors": [], "recommendations": [],
        })
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=mock_response_text)

        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), \
             patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("Contract text")

        assert result["risk_score"] == 35.0
        assert result["risk_level"] == "low"
        assert "analyzed_at"        in result

    @pytest.mark.asyncio
    async def test_gemini_exception_returns_error_dict(self):
        """PATH P3 — Exception → error dict, no crash. Branch: except TRUE"""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API timeout")

        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), \
             patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("Contract text")

        assert "error"              in result
        assert result["risk_score"] is None
        assert result["risk_level"] is None

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped_before_parse(self):
        """PATH — ```json fences stripped. Branch: startswith TRUE"""
        import json
        inner = json.dumps({
            "summary": "Test", "extracted_clauses": [], "key_information": {},
            "risk_score": 50.0, "risk_level": "medium",
            "risk_factors": [], "recommendations": [],
        })
        fenced = f"```json\n{inner}\n```"
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=fenced)

        with patch.object(ai_module, "GEMINI_API_KEY", "real-key"), \
             patch.object(ai_module, "_get_model", return_value=mock_model):
            result = await ai_module.analyze_contract_text("text")

        assert result["risk_score"] == 50.0


class TestAnalyzeContractById:

    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self):
        """PATH P1 — Bad ObjectId → None. Branch: guard TRUE"""
        with patch.object(ai_module, "contracts_collection") as mock_col:
            result = await ai_module.analyze_contract_by_id("not-valid-id")
        assert result is None
        mock_col.find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_contract_not_found_returns_none(self):
        """PATH P2 — Contract missing → None. Branch: not contract TRUE"""
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = None
            result = await ai_module.analyze_contract_by_id(str(ObjectId()))
        assert result is None

    @pytest.mark.asyncio
    async def test_contract_found_analysis_stored(self):
        """PATH P3 — Contract found → analyse and persist."""
        contract = make_contract()
        with patch.object(ai_module, "GEMINI_API_KEY", ""), \
             patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = contract
            mock_col.update_one.return_value = MagicMock()
            result = await ai_module.analyze_contract_by_id(str(contract["_id"]))

        assert result is not None
        assert "contract_id" in result
        mock_col.update_one.assert_called_once()
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "ai_analysis" in payload
        assert "updated_at"  in payload


class TestDetectConflicts:

    @pytest.mark.asyncio
    async def test_fewer_than_2_contracts_returns_error(self):
        """PATH P1 — 1 contract → error. Branch: len < 2 TRUE"""
        contract = make_contract()
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.return_value = contract
            result = await ai_module.detect_conflicts([str(contract["_id"])])
        assert "error"             in result
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_invalid_ids_skipped(self):
        """Invalid ObjectIds skipped. Branch: is_valid FALSE → continue"""
        with patch.object(ai_module, "contracts_collection") as mock_col:
            result = await ai_module.detect_conflicts(["bad-1", "bad-2"])
        assert "error" in result
        mock_col.find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_api_key_returns_mock_conflicts(self):
        """PATH P2 — No key + 2 contracts → mock conflicts. Branch: no key TRUE"""
        c1 = make_contract("NDA")
        c2 = make_contract("Service Agreement")
        with patch.object(ai_module, "GEMINI_API_KEY", ""), \
             patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find_one.side_effect = [c1, c2]
            result = await ai_module.detect_conflicts([str(c1["_id"]), str(c2["_id"])])
        assert "total_conflicts"    in result
        assert "conflicts"          in result
        assert result["total_conflicts"] > 0


class TestBuildContractText:

    def test_basic_fields_included(self):
        contract = make_contract(title="Service Agreement")
        result = ai_module._build_contract_text(contract)
        assert "Service Agreement" in result

    def test_parties_included_when_present(self):
        """Branch: if parties TRUE"""
        contract = make_contract()
        contract["parties"] = [
            {"name": "Acme Corp", "role": "client"},
            {"name": "DevCo",     "role": "vendor"},
        ]
        result = ai_module._build_contract_text(contract)
        assert "Acme Corp" in result
        assert "DevCo"     in result

    def test_parties_omitted_when_empty(self):
        """Branch: if parties FALSE"""
        contract = make_contract()
        contract["parties"] = []
        result = ai_module._build_contract_text(contract)
        assert "Parties:" not in result

    def test_tags_included_when_present(self):
        """Branch: if tags TRUE"""
        contract = make_contract()
        contract["tags"] = ["legal", "nda", "priority"]
        result = ai_module._build_contract_text(contract)
        assert "legal"    in result
        assert "priority" in result

    def test_tags_omitted_when_empty(self):
        """Branch: if tags FALSE"""
        contract = make_contract()
        contract["tags"] = []
        result = ai_module._build_contract_text(contract)
        assert "Tags:" not in result


class TestScanContractAgainstExisting:

    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_error(self):
        """PATH P1 — Bad ObjectId → error dict. Branch: guard TRUE"""
        result = await ai_module.scan_contract_against_existing("not-valid")
        assert "error"                   in result
        assert result["total_conflicts"] == 0
        assert result["conflicts"]       == []

    @pytest.mark.asyncio
    async def test_no_other_contracts_returns_conflict_free(self):
        """PATH P2 — No other contracts → conflict-free. Branch: not other_ids TRUE"""
        with patch.object(ai_module, "contracts_collection") as mock_col:
            mock_col.find.return_value \
                   .sort.return_value \
                   .limit.return_value = iter([])
            result = await ai_module.scan_contract_against_existing(str(ObjectId()))
        assert result["total_conflicts"] == 0
        assert result["conflicts"]       == []
        assert "summary"                 in result