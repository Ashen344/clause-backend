"""
test_audit_service.py
Complete white-box + requirements test suite for audit_service.py
NFR-SC-06, NFR-SC-07, FR-WP-05, FR-UAM-06
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import app.services.audit_service as audit_module


def make_log(action="create"):
    return {"_id": ObjectId(), "action": action, "resource_type": "contract", "resource_id": str(ObjectId()), "user_id": "user_001", "user_email": "user@example.com", "details": "Test", "changes": None, "ip_address": "127.0.0.1", "created_at": datetime.utcnow()}


def setup_mock(mock_col, docs=None, total=0):
    if docs is None:
        docs = []
    mock_col.count_documents.return_value = total
    mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter(docs)


class TestCreateAuditLog:

    @patch.object(audit_module, "audit_logs_collection")
    def test_log_inserted_with_correct_fields(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        audit_module.create_audit_log(action=AuditAction.create, resource_type="contract", resource_id="contract_abc", user_id="user_001", user_email="user@example.com", details="Created", changes={"title": "NDA"}, ip_address="127.0.0.1")
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["action"] == AuditAction.create.value
        assert doc["resource_type"] == "contract"
        assert doc["user_id"] == "user_001"
        assert doc["ip_address"] == "127.0.0.1"
        assert "created_at" in doc

    @patch.object(audit_module, "audit_logs_collection")
    def test_optional_fields_default_to_none(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        audit_module.create_audit_log(action=AuditAction.login, resource_type="user", resource_id="user_001", user_id="admin_001")
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["user_email"] is None and doc["details"] is None and doc["ip_address"] is None

    @patch.object(audit_module, "audit_logs_collection")
    def test_created_at_is_datetime(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        audit_module.create_audit_log(action=AuditAction.update, resource_type="contract", resource_id="abc", user_id="user_001")
        assert isinstance(mock_col.insert_one.call_args[0][0]["created_at"], datetime)

    @patch.object(audit_module, "audit_logs_collection")
    def test_all_action_types_accepted(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        for action in AuditAction:
            audit_module.create_audit_log(action=action, resource_type="contract", resource_id="abc", user_id="user_001")
        assert mock_col.insert_one.call_count == len(AuditAction)

    @patch.object(audit_module, "audit_logs_collection")
    def test_login_logged_with_ip(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        audit_module.create_audit_log(action=AuditAction.login, resource_type="user", resource_id="user_001", user_id="user_001", ip_address="192.168.1.1")
        assert mock_col.insert_one.call_args[0][0]["ip_address"] == "192.168.1.1"

    @patch.object(audit_module, "audit_logs_collection")
    def test_role_change_logged_with_changes(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        audit_module.create_audit_log(action=AuditAction.update, resource_type="user", resource_id="user_001", user_id="admin_001", changes={"role": {"from": "user", "to": "admin"}})
        assert mock_col.insert_one.call_args[0][0]["changes"]["role"]["to"] == "admin"

    @patch.object(audit_module, "audit_logs_collection")
    def test_no_update_audit_log_function_exists(self, mock_col):
        """Immutability: update function must not exist. NFR-SC-07"""
        assert not hasattr(audit_module, "update_audit_log")

    @patch.object(audit_module, "audit_logs_collection")
    def test_no_delete_audit_log_function_exists(self, mock_col):
        """Immutability: delete function must not exist. NFR-SC-07"""
        assert not hasattr(audit_module, "delete_audit_log")

    @patch.object(audit_module, "audit_logs_collection")
    def test_create_uses_insert_not_upsert(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        audit_module.create_audit_log(action=AuditAction.create, resource_type="contract", resource_id="abc", user_id="user_001")
        mock_col.insert_one.assert_called_once()
        mock_col.update_one.assert_not_called()
        mock_col.replace_one.assert_not_called()

    @patch.object(audit_module, "audit_logs_collection")
    def test_two_logs_get_separate_created_at(self, mock_col):
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        for action in [AuditAction.create, AuditAction.update]:
            audit_module.create_audit_log(action=action, resource_type="contract", resource_id="abc", user_id="user_001")
        doc1 = mock_col.insert_one.call_args_list[0][0][0]
        doc2 = mock_col.insert_one.call_args_list[1][0][0]
        assert doc1["created_at"] is not doc2["created_at"]


class TestGetAuditLogs:

    @patch.object(audit_module, "audit_logs_collection")
    def test_no_filters_empty_query(self, mock_col):
        setup_mock(mock_col)
        audit_module.get_audit_logs()
        assert mock_col.count_documents.call_args[0][0] == {}

    @patch.object(audit_module, "audit_logs_collection")
    def test_resource_type_filter(self, mock_col):
        setup_mock(mock_col)
        audit_module.get_audit_logs(resource_type="contract")
        assert mock_col.count_documents.call_args[0][0]["resource_type"] == "contract"

    @patch.object(audit_module, "audit_logs_collection")
    def test_resource_id_filter(self, mock_col):
        setup_mock(mock_col)
        audit_module.get_audit_logs(resource_id="contract_abc")
        assert mock_col.count_documents.call_args[0][0]["resource_id"] == "contract_abc"

    @patch.object(audit_module, "audit_logs_collection")
    def test_user_id_filter(self, mock_col):
        setup_mock(mock_col)
        audit_module.get_audit_logs(user_id="user_001")
        assert mock_col.count_documents.call_args[0][0]["user_id"] == "user_001"

    @patch.object(audit_module, "audit_logs_collection")
    def test_action_filter(self, mock_col):
        setup_mock(mock_col)
        audit_module.get_audit_logs(action="create")
        assert mock_col.count_documents.call_args[0][0]["action"] == "create"

    @patch.object(audit_module, "audit_logs_collection")
    def test_action_filter_absent_when_none(self, mock_col):
        setup_mock(mock_col)
        audit_module.get_audit_logs()
        assert "action" not in mock_col.count_documents.call_args[0][0]

    @patch.object(audit_module, "audit_logs_collection")
    def test_all_filters_combined(self, mock_col):
        setup_mock(mock_col)
        audit_module.get_audit_logs(resource_type="contract", resource_id="abc", user_id="user_001", action="create")
        query = mock_col.count_documents.call_args[0][0]
        assert query["resource_type"] == "contract" and query["action"] == "create"

    @patch.object(audit_module, "audit_logs_collection")
    def test_log_id_converted_to_string(self, mock_col):
        setup_mock(mock_col, docs=[make_log()], total=1)
        result = audit_module.get_audit_logs()
        assert "id" in result["logs"][0] and "_id" not in result["logs"][0]

    @patch.object(audit_module, "audit_logs_collection")
    def test_multiple_logs_all_converted(self, mock_col):
        setup_mock(mock_col, docs=[make_log(), make_log(), make_log()], total=3)
        result = audit_module.get_audit_logs()
        assert len(result["logs"]) == 3
        for entry in result["logs"]:
            assert "id" in entry and "_id" not in entry

    @patch.object(audit_module, "audit_logs_collection")
    def test_empty_result_total_pages_zero(self, mock_col):
        setup_mock(mock_col, total=0)
        result = audit_module.get_audit_logs()
        assert result["total"] == 0 and result["total_pages"] == 0

    @patch.object(audit_module, "audit_logs_collection")
    def test_pagination_skip_arithmetic(self, mock_col):
        setup_mock(mock_col, total=100)
        audit_module.get_audit_logs(page=2, per_page=50)
        mock_col.find.return_value.sort.return_value.skip.assert_called_with(50)

    @patch.object(audit_module, "audit_logs_collection")
    def test_response_has_correct_keys(self, mock_col):
        setup_mock(mock_col, total=0)
        result = audit_module.get_audit_logs()
        for key in ["logs", "total", "page", "per_page", "total_pages"]:
            assert key in result