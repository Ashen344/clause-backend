import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import app.services.notification_service as notif_module


def make_notification(user_id="user_001", is_read=False):
    return {
        "_id": ObjectId(),
        "user_id": user_id,
        "notification_type": "approval_required",
        "title": "Approval Needed",
        "message": "Please review.",
        "contract_id": str(ObjectId()),
        "is_read": is_read,
        "created_at": datetime.utcnow(),
    }


class TestNotificationToResponse:

    def test_converts_id_to_string(self):
        """TC-NOT-01: ID conversion"""
        result = notif_module.notification_to_response(make_notification())
        assert "id" in result
        assert "_id" not in result

    def test_other_fields_preserved(self):
        result = notif_module.notification_to_response(make_notification(user_id="user_abc", is_read=True))
        assert result["user_id"] == "user_abc"
        assert result["is_read"] is True


class TestGetUserNotifications:

    @patch.object(notif_module, "notifications_collection")
    def test_all_notifications_no_filter(self, mock_col):
        """TC-NOT-03: Get all notifications"""
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([make_notification()])
        result = notif_module.get_user_notifications("user_001", unread_only=False)
        assert len(result) == 1

    @patch.object(notif_module, "notifications_collection")
    def test_unread_only_filter_applied(self, mock_col):
        """TC-NOT-04: Filter unread notifications"""
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([make_notification()])
        notif_module.get_user_notifications("user_001", unread_only=True)
        query = mock_col.find.call_args[0][0]
        assert query["is_read"] is False

    @patch.object(notif_module, "notifications_collection")
    def test_empty_result_returns_empty_list(self, mock_col):
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([])
        assert notif_module.get_user_notifications("nobody") == []

    @patch.object(notif_module, "notifications_collection")
    def test_custom_limit_passed_to_query(self, mock_col):
        """TC-NOT-06: Custom limit"""
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([])
        notif_module.get_user_notifications("user_001", limit=10)
        mock_col.find.return_value.sort.return_value.limit.assert_called_with(10)


class TestMarkAsRead:

    @patch.object(notif_module, "notifications_collection")
    def test_invalid_objectid_returns_false(self, mock_col):
        """TC-NOT-07: Input validation"""
        assert notif_module.mark_as_read("not-valid-id") is False

    @patch.object(notif_module, "notifications_collection")
    def test_not_found_returns_false(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        assert notif_module.mark_as_read(str(ObjectId())) is False

    @patch.object(notif_module, "notifications_collection")
    def test_mark_as_read_success(self, mock_col):
        """TC-NOT-09: Mark notification as read"""
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        assert notif_module.mark_as_read(str(ObjectId())) is True


class TestMarkAllAsRead:

    @patch.object(notif_module, "notifications_collection")
    def test_returns_modified_count(self, mock_col):
        """TC-NOT-10: Mark all as read"""
        mock_col.update_many.return_value = MagicMock(modified_count=5)
        assert notif_module.mark_all_as_read("user_001") == 5

    @patch.object(notif_module, "notifications_collection")
    def test_returns_zero_when_none_updated(self, mock_col):
        mock_col.update_many.return_value = MagicMock(modified_count=0)
        assert notif_module.mark_all_as_read("user_001") == 0


class TestGetUnreadCount:

    @patch.object(notif_module, "notifications_collection")
    def test_returns_correct_count(self, mock_col):
        """TC-NOT-12: Get unread count"""
        mock_col.count_documents.return_value = 7
        assert notif_module.get_unread_count("user_001") == 7

    @patch.object(notif_module, "notifications_collection")
    def test_returns_zero_when_all_read(self, mock_col):
        mock_col.count_documents.return_value = 0
        assert notif_module.get_unread_count("user_001") == 0
    
class TestCreateNotification:

    @patch.object(notif_module, "notifications_collection")
    def test_notification_created_successfully(self, mock_col):
        """TC-NOT-14: Create notification"""
        from app.models.notification import NotificationCreate
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        mock_col.find_one.return_value = make_notification()
        
        result = notif_module.create_notification(
            NotificationCreate(
                user_id="user_001",
                notification_type="approval_required",
                title="Test",
                message="Test message"
            )
        )
        
        assert result is not None
        assert "id" in result