import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import app.services.audit_service as audit_module


class TestCreateAuditLog:

    @patch.object(audit_module, "audit_logs_collection")
    def test_log_inserted_with_correct_fields(self, mock_col):
        """TC-AU-01: Audit log creation"""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        
        audit_module.create_audit_log(
            action=AuditAction.create,  # Changed from contract_created
            resource_type="contract",
            resource_id="c123",
            user_id="u001",
            user_email="user@test.com",
            details="Created new contract",
            changes={"title": "New Contract"},
            ip_address="192.168.1.1",
        )
        
        call_args = mock_col.insert_one.call_args[0][0]
        assert call_args["action"] == "create"  # Changed
        assert call_args["resource_type"] == "contract"

    @patch.object(audit_module, "audit_logs_collection")
    def test_log_inserted_with_optional_fields_as_none(self, mock_col):
        """TC-AU-02: Optional fields default to None"""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        
        audit_module.create_audit_log(
            action=AuditAction.update,  # Changed
            resource_type="contract",
            resource_id="c123",
            user_id="u001",
        )
        
        call_args = mock_col.insert_one.call_args[0][0]
        assert call_args["user_email"] is None
        assert call_args["details"] is None

    @patch.object(audit_module, "audit_logs_collection")
    def test_created_at_timestamp_is_set(self, mock_col):
        """TC-AU-03: Timestamp on audit logs"""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        
        audit_module.create_audit_log(
            action=AuditAction.delete,  # Changed
            resource_type="contract",
            resource_id="c123",
            user_id="u001",
        )
        
        call_args = mock_col.insert_one.call_args[0][0]
        assert isinstance(call_args["created_at"], datetime)

    @patch.object(audit_module, "audit_logs_collection")
    def test_all_action_types_accepted(self, mock_col):
        """TC-AU-04: All AuditAction enum values work"""
        from app.models.audit_log import AuditAction
        mock_col.insert_one.return_value = MagicMock()
        
        for action in AuditAction:
            audit_module.create_audit_log(
                action=action,
                resource_type="contract",
                resource_id="c123",
                user_id="u001",
            )
        
        # Should have 12 calls (one for each enum value)
        assert mock_col.insert_one.call_count == 12


class TestGetAuditLogs:

    @patch.object(audit_module, "audit_logs_collection")
    def test_no_filters_empty_query(self, mock_col):
        """TC-AU-05: Get audit logs without filters"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        audit_module.get_audit_logs()
        
        query = mock_col.count_documents.call_args[0][0]
        assert query == {}

    @patch.object(audit_module, "audit_logs_collection")
    def test_resource_type_filter(self, mock_col):
        """TC-AU-06: Filter by resource type"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        audit_module.get_audit_logs(resource_type="contract")
        
        query = mock_col.count_documents.call_args[0][0]
        assert query["resource_type"] == "contract"

    @patch.object(audit_module, "audit_logs_collection")
    def test_resource_id_filter(self, mock_col):
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        audit_module.get_audit_logs(resource_id="abc")
        
        query = mock_col.count_documents.call_args[0][0]
        assert query["resource_id"] == "abc"

    @patch.object(audit_module, "audit_logs_collection")
    def test_user_id_filter(self, mock_col):
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        audit_module.get_audit_logs(user_id="user_001")
        
        query = mock_col.count_documents.call_args[0][0]
        assert query["user_id"] == "user_001"

    @patch.object(audit_module, "audit_logs_collection")
    def test_all_filters_combined(self, mock_col):
        """All filters applied together"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        audit_module.get_audit_logs(
            resource_type="contract",
            resource_id="abc",
            user_id="user_001",
            action="create",  # Changed to match your enum
        )
        
        query = mock_col.count_documents.call_args[0][0]
        assert len(query) == 4

    @patch.object(audit_module, "audit_logs_collection")
    def test_empty_result_total_pages_zero(self, mock_col):
        """Edge case: Empty result"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        result = audit_module.get_audit_logs()
        assert result["total_pages"] == 0

    @patch.object(audit_module, "audit_logs_collection")
    def test_pagination_skip_arithmetic(self, mock_col):
        """Pagination arithmetic"""
        mock_col.count_documents.return_value = 100
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        audit_module.get_audit_logs(page=2, per_page=50)
        
        mock_col.find.return_value.sort.return_value.skip.assert_called_with(50)