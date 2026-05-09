"""
test_helpers.py
Complete white-box + requirements test suite for helpers.py
NFR-RB-06, NFR-MB-01
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime, timedelta
import app.utils.helpers as helpers_module


class TestToObjectId:

    def test_valid_string_returns_objectid(self):
        result = helpers_module.to_object_id(str(ObjectId()))
        assert isinstance(result, ObjectId)

    def test_invalid_string_returns_none(self):
        for bad in ["not-valid", "", "123"]:
            assert helpers_module.to_object_id(bad) is None

    def test_none_input_returns_none(self):
        assert helpers_module.to_object_id(None) is None

    def test_sql_injection_returns_none(self):
        assert helpers_module.to_object_id("' OR '1'='1") is None

    def test_script_tag_returns_none(self):
        assert helpers_module.to_object_id("<script>alert(1)</script>") is None

    def test_path_traversal_returns_none(self):
        assert helpers_module.to_object_id("../../etc/passwd") is None


class TestSerializeDoc:

    def test_none_input_returns_none(self):
        assert helpers_module.serialize_doc(None) is None

    def test_objectid_fields_converted_to_strings(self):
        result = helpers_module.serialize_doc({"_id": ObjectId(), "ref": ObjectId()})
        assert "id" in result and isinstance(result["id"], str)

    def test_datetime_fields_converted_to_iso(self):
        result = helpers_module.serialize_doc({"_id": ObjectId(), "created_at": datetime(2025,6,1,12,0,0)})
        assert isinstance(result["created_at"], str) and "2025" in result["created_at"]

    def test_plain_string_fields_unchanged(self):
        result = helpers_module.serialize_doc({"_id": ObjectId(), "title": "My Contract"})
        assert result["title"] == "My Contract"

    def test_raw_objectid_not_in_result(self):
        result = helpers_module.serialize_doc({"_id": ObjectId(), "name": "Test"})
        assert "_id" not in result


class TestDaysUntil:

    def test_future_date_returns_positive(self):
        assert helpers_module.days_until(datetime.utcnow() + timedelta(days=30)) == 30

    def test_past_date_returns_zero_not_negative(self):
        assert helpers_module.days_until(datetime.utcnow() - timedelta(days=10)) == 0

    def test_today_returns_zero(self):
        assert helpers_module.days_until(datetime.utcnow()) == 0

    def test_one_day_future(self):
        assert helpers_module.days_until(datetime.utcnow() + timedelta(days=1)) == 1

    def test_365_days_future(self):
        assert helpers_module.days_until(datetime.utcnow() + timedelta(days=365)) == 365


class TestPaginate:

    def test_empty_collection_total_pages_zero(self):
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.skip.return_value.limit.return_value = iter([])
        result = helpers_module.paginate(mock_col, {}, page=1, per_page=20)
        assert result["total"] == 0 and result["total_pages"] == 0

    def test_page_one_skip_is_zero(self):
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 5
        mock_col.find.return_value.skip.return_value.limit.return_value = iter([])
        helpers_module.paginate(mock_col, {}, page=1, per_page=20)
        mock_col.find.return_value.skip.assert_called_with(0)

    def test_page_three_skip_arithmetic(self):
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 30
        mock_col.find.return_value.skip.return_value.limit.return_value = iter([])
        helpers_module.paginate(mock_col, {}, page=3, per_page=10)
        mock_col.find.return_value.skip.assert_called_with(20)

    def test_total_pages_ceiling(self):
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 45
        mock_col.find.return_value.skip.return_value.limit.return_value = iter([])
        result = helpers_module.paginate(mock_col, {}, page=1, per_page=20)
        assert result["total_pages"] == 3


class TestGenerateContractNumber:

    @patch.object(helpers_module, "contracts_collection")
    def test_first_contract_of_year(self, mock_col):
        mock_col.count_documents.return_value = 0
        result = helpers_module.generate_contract_number()
        assert result.startswith("CLM-") and result.endswith("0001")

    @patch.object(helpers_module, "contracts_collection")
    def test_tenth_contract_of_year(self, mock_col):
        mock_col.count_documents.return_value = 9
        assert helpers_module.generate_contract_number().endswith("0010")

    @patch.object(helpers_module, "contracts_collection")
    def test_query_scoped_to_current_year(self, mock_col):
        mock_col.count_documents.return_value = 0
        helpers_module.generate_contract_number()
        query = mock_col.count_documents.call_args[0][0]
        assert "$gte" in query.get("created_at", {}) and "$lt" in query.get("created_at", {})

    @patch.object(helpers_module, "contracts_collection")
    def test_number_has_four_digit_padding(self, mock_col):
        mock_col.count_documents.return_value = 0
        result = helpers_module.generate_contract_number()
        assert len(result.split("-")[-1]) == 4