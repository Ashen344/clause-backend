import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime, timedelta
import app.utils.helpers as helpers_module


class TestToObjectId:

    def test_valid_string_returns_objectid(self):
        """NFR-MB-01: ObjectId conversion"""
        oid_str = str(ObjectId())
        result = helpers_module.to_object_id(oid_str)
        assert isinstance(result, ObjectId)

    def test_invalid_string_returns_none(self):
        assert helpers_module.to_object_id("not-valid") is None

    def test_none_input_returns_none(self):
        assert helpers_module.to_object_id(None) is None


class TestSerializeDoc:

    def test_none_input_returns_none(self):
        assert helpers_module.serialize_doc(None) is None

    def test_objectid_fields_converted_to_strings(self):
        """NFR-MB-02: Document serialization"""
        doc = {"_id": ObjectId(), "ref": ObjectId()}
        result = helpers_module.serialize_doc(doc)
        assert "id" in result
        assert isinstance(result["id"], str)
        assert isinstance(result["ref"], str)

    def test_datetime_fields_converted_to_iso(self):
        doc = {"_id": ObjectId(), "created_at": datetime(2025, 6, 1, 12, 0, 0)}
        result = helpers_module.serialize_doc(doc)
        assert isinstance(result["created_at"], str)
        assert "2025-06-01" in result["created_at"]

    def test_plain_string_fields_unchanged(self):
        doc = {"_id": ObjectId(), "title": "My Contract"}
        result = helpers_module.serialize_doc(doc)
        assert result["title"] == "My Contract"


class TestDaysUntil:

    def test_future_date_returns_positive(self):
        """NFR-MB-03: Date calculations"""
        future = datetime.utcnow() + timedelta(days=30)
        assert helpers_module.days_until(future) == 30

    def test_past_date_returns_zero_not_negative(self):
        """Boundary: Past dates return 0, not negative"""
        past = datetime.utcnow() - timedelta(days=10)
        assert helpers_module.days_until(past) == 0

    def test_today_returns_zero(self):
        assert helpers_module.days_until(datetime.utcnow()) == 0


class TestPaginateQuery:

    def test_pagination_mechanics(self):
        """NFR-MB-05: Pagination helper"""
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 50
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        result = helpers_module.paginate_query(mock_col, {}, page=2, per_page=20)
        
        assert result["total"] == 50
        assert result["page"] == 2
        mock_col.find.return_value.sort.return_value.skip.assert_called_with(20)

    def test_empty_collection_total_pages_zero(self):
        """Edge case: Empty collection"""
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        result = helpers_module.paginate_query(mock_col, {}, page=1, per_page=20)
        
        assert result["total_pages"] == 0