import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime

import app.services.audit_service as audit_module


class TestCreateAuditLog:

    @patch.object(audit_module, "audit_logs_collection")
    def test_log_inserted_with_correct_fields(self, mock_col):
        """All fields must be stored correctly in the inserted document."""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()

        audit_module.create_audit_log(
            action=AuditAction.create,
            resource_type="contract",
            resource_id="contract_abc",
            user_id="user_001",
            user_email="user@example.com",
            details="Contract created",
            changes={"title": "NDA"},
            ip_address="127.0.0.1",
        )

        mock_col.insert_one.assert_called_once()
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["action"]        == AuditAction.create.value
        assert doc["resource_type"] == "contract"
        assert doc["resource_id"]   == "contract_abc"
        assert doc["user_id"]       == "user_001"
        assert doc["user_email"]    == "user@example.com"
        assert doc["details"]       == "Contract created"
        assert doc["changes"]       == {"title": "NDA"}
        assert doc["ip_address"]    == "127.0.0.1"
        assert "created_at"         in doc

    @patch.object(audit_module, "audit_logs_collection")
    def test_log_inserted_with_optional_fields_as_none(self, mock_col):
        """Optional fields default to None when not provided."""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()

        audit_module.create_audit_log(
            action=AuditAction.login,
            resource_type="user",
            resource_id="user_001",
            user_id="admin_001",
        )

        doc = mock_col.insert_one.call_args[0][0]
        assert doc["user_email"]  is None
        assert doc["details"]     is None
        assert doc["changes"]     is None
        assert doc["ip_address"]  is None

    @patch.object(audit_module, "audit_logs_collection")
    def test_created_at_timestamp_is_set(self, mock_col):
        """created_at must be set automatically."""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()

        audit_module.create_audit_log(
            action=AuditAction.update,
            resource_type="contract",
            resource_id="abc",
            user_id="user_001",
        )

        doc = mock_col.insert_one.call_args[0][0]
        assert "created_at" in doc
        assert isinstance(doc["created_at"], datetime)

    @patch.object(audit_module, "audit_logs_collection")
    def test_all_action_types_accepted(self, mock_col):
        """Every AuditAction enum value must be storable."""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()

        for action in AuditAction:
            audit_module.create_audit_log(
                action=action,
                resource_type="contract",
                resource_id="abc",
                user_id="user_001",
            )

        assert mock_col.insert_one.call_count == len(AuditAction)


class TestGetAuditLogs:

    def make_log(self):
        return {
            "_id":           ObjectId(),
            "action":        "create",
            "resource_type": "contract",
            "resource_id":   "abc123",
            "user_id":       "user_001",
            "user_email":    "user@example.com",
            "details":       "Created contract",
            "changes":       None,
            "ip_address":    "127.0.0.1",
            "created_at":    datetime.utcnow(),
        }

    def _setup_mock(self, mock_col, docs=None, total=0):
        if docs is None:
            docs = []
        mock_col.count_documents.return_value = total
        mock_col.find.return_value \
               .sort.return_value \
               .skip.return_value \
               .limit.return_value = iter(docs)

    @patch.object(audit_module, "audit_logs_collection")
    def test_no_filters_empty_query(self, mock_col):
        """
        PATH P1 — No filters → query is {}.
        Branch: all filter conditions FALSE
        """
        self._setup_mock(mock_col)
        audit_module.get_audit_logs()
        query = mock_col.count_documents.call_args[0][0]
        assert query == {}

    @patch.object(audit_module, "audit_logs_collection")
    def test_resource_type_filter(self, mock_col):
        """
        Branch: resource_type TRUE side
        """
        self._setup_mock(mock_col)
        audit_module.get_audit_logs(resource_type="contract")
        query = mock_col.count_documents.call_args[0][0]
        assert query["resource_type"] == "contract"

    @patch.object(audit_module, "audit_logs_collection")
    def test_resource_id_filter(self, mock_col):
        """Branch: resource_id TRUE side"""
        self._setup_mock(mock_col)
        audit_module.get_audit_logs(resource_id="contract_abc")
        query = mock_col.count_documents.call_args[0][0]
        assert query["resource_id"] == "contract_abc"

    @patch.object(audit_module, "audit_logs_collection")
    def test_user_id_filter(self, mock_col):
        """Branch: user_id TRUE side"""
        self._setup_mock(mock_col)
        audit_module.get_audit_logs(user_id="user_001")
        query = mock_col.count_documents.call_args[0][0]
        assert query["user_id"] == "user_001"

    @patch.object(audit_module, "audit_logs_collection")
    def test_action_filter(self, mock_col):
        """Branch: action TRUE side"""
        self._setup_mock(mock_col)
        audit_module.get_audit_logs(action="create")
        query = mock_col.count_documents.call_args[0][0]
        assert query["action"] == "create"

    @patch.object(audit_module, "audit_logs_collection")
    def test_all_filters_combined(self, mock_col):
        """
        PATH P4 — All filters set → all added to query.
        Branch: all filter TRUE sides
        """
        self._setup_mock(mock_col)
        audit_module.get_audit_logs(
            resource_type="contract",
            resource_id="abc",
            user_id="user_001",
            action="create",
        )
        query = mock_col.count_documents.call_args[0][0]
        assert query["resource_type"] == "contract"
        assert query["resource_id"]   == "abc"
        assert query["user_id"]       == "user_001"
        assert query["action"]        == "create"

    @patch.object(audit_module, "audit_logs_collection")
    def test_logs_id_converted_to_string(self, mock_col):
        """Each log _id must become string id key."""
        log = self.make_log()
        self._setup_mock(mock_col, docs=[log], total=1)
        result = audit_module.get_audit_logs()
        assert len(result["logs"]) == 1
        assert "id"  in result["logs"][0]
        assert "_id" not in result["logs"][0]

    @patch.object(audit_module, "audit_logs_collection")
    def test_empty_result_total_pages_zero(self, mock_col):
        """
        PATH P5 — total=0 → total_pages=0.
        Branch: total > 0 FALSE side
        """
        self._setup_mock(mock_col, total=0)
        result = audit_module.get_audit_logs()
        assert result["total"]       == 0
        assert result["total_pages"] == 0

    @patch.object(audit_module, "audit_logs_collection")
    def test_pagination_skip_arithmetic(self, mock_col):
        """page=2, per_page=50 → skip=50."""
        self._setup_mock(mock_col, total=100)
        audit_module.get_audit_logs(page=2, per_page=50)
        skip_call = mock_col.find.return_value.sort.return_value.skip
        skip_call.assert_called_with(50)

    @patch.object(audit_module, "audit_logs_collection")
    def test_response_has_correct_keys(self, mock_col):
        """Response dict must have logs, total, page, per_page, total_pages."""
        self._setup_mock(mock_col, total=0)
        result = audit_module.get_audit_logs()
        for key in ["logs", "total", "page", "per_page", "total_pages"]:
            assert key in result

    @patch.object(audit_module, "audit_logs_collection")
    def test_multiple_logs_all_converted(self, mock_col):
        """Multiple logs — all must have id, none should have _id."""
        logs = [self.make_log(), self.make_log(), self.make_log()]
        self._setup_mock(mock_col, docs=logs, total=3)
        result = audit_module.get_audit_logs()
        assert len(result["logs"]) == 3
        for log in result["logs"]:
            assert "id"  in log
            assert "_id" not in log