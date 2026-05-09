"""
test_notification_service.py
Complete white-box + requirements test suite for notification_service.py
FR-NA-05, FR-UAM-13, NFR-RB-01, NFR-RB-06
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import app.services.notification_service as notif_module


def make_notification(user_id="user_001", is_read=False):
    return {"_id": ObjectId(), "user_id": user_id, "notification_type": "approval_required", "title": "Approval Needed", "message": "Please review.", "contract_id": str(ObjectId()), "is_read": is_read, "created_at": datetime.utcnow()}


class TestNotificationToResponse:

    def test_converts_id_to_string(self):
        from app.services.notification_service import notification_to_response
        result = notification_to_response(make_notification())
        assert "id" in result and "_id" not in result and isinstance(result["id"], str)

    def test_other_fields_preserved(self):
        from app.services.notification_service import notification_to_response
        result = notification_to_response(make_notification(user_id="user_abc", is_read=True))
        assert result["user_id"] == "user_abc" and result["is_read"] is True


class TestGetUserNotifications:

    @patch.object(notif_module, "notifications_collection")
    def test_all_notifications_no_filter(self, mock_col):
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([make_notification()])
        result = notif_module.get_user_notifications("user_001", unread_only=False)
        query = mock_col.find.call_args[0][0]
        assert query == {"user_id": "user_001"} and len(result) == 1

    @patch.object(notif_module, "notifications_collection")
    def test_unread_only_filter_applied(self, mock_col):
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([make_notification()])
        notif_module.get_user_notifications("user_001", unread_only=True)
        assert mock_col.find.call_args[0][0]["is_read"] is False

    @patch.object(notif_module, "notifications_collection")
    def test_empty_result_returns_empty_list(self, mock_col):
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([])
        assert notif_module.get_user_notifications("nobody") == []

    @patch.object(notif_module, "notifications_collection")
    def test_custom_limit_passed_to_query(self, mock_col):
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([])
        notif_module.get_user_notifications("user_001", limit=10)
        mock_col.find.return_value.sort.return_value.limit.assert_called_with(10)


class TestCreateNotification:

    @patch.object(notif_module, "notifications_collection")
    def test_expiry_notification_inserted_with_correct_type(self, mock_col):
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        notif_module.create_notification(user_id="user_001", notification_type="contract_expiring", title="Expiring", message="Expires soon.", contract_id=str(ObjectId()))
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["notification_type"] == "contract_expiring" and doc["user_id"] == "user_001"

    @patch.object(notif_module, "notifications_collection")
    def test_notification_has_created_at(self, mock_col):
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        notif_module.create_notification(user_id="user_001", notification_type="contract_expiring", title="Expiring", message="Expires soon.", contract_id=str(ObjectId()))
        doc = mock_col.insert_one.call_args[0][0]
        assert "created_at" in doc and isinstance(doc["created_at"], datetime)

    @patch.object(notif_module, "notifications_collection")
    def test_notification_defaults_to_unread(self, mock_col):
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        notif_module.create_notification(user_id="user_001", notification_type="contract_expiring", title="Expiring", message="Expires soon.", contract_id=str(ObjectId()))
        assert mock_col.insert_one.call_args[0][0].get("is_read") is False

    @patch.object(notif_module, "notifications_collection")
    def test_notification_links_contract_id(self, mock_col):
        cid = str(ObjectId())
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        notif_module.create_notification(user_id="user_001", notification_type="contract_expiring", title="Expiring", message="Expires.", contract_id=cid)
        assert mock_col.insert_one.call_args[0][0]["contract_id"] == cid

    @patch.object(notif_module, "notifications_collection")
    def test_empty_user_id_rejected(self, mock_col):
        result = notif_module.create_notification(user_id="", notification_type="general", title="Test", message="Msg")
        assert result is None
        mock_col.insert_one.assert_not_called()

    @patch.object(notif_module, "notifications_collection")
    def test_none_user_id_rejected(self, mock_col):
        result = notif_module.create_notification(user_id=None, notification_type="general", title="Test", message="Msg")
        assert result is None
        mock_col.insert_one.assert_not_called()


class TestMarkAsRead:

    @patch.object(notif_module, "notifications_collection")
    def test_invalid_objectid_returns_false(self, mock_col):
        assert notif_module.mark_as_read("not-valid-id") is False
        mock_col.update_one.assert_not_called()

    @patch.object(notif_module, "notifications_collection")
    def test_not_found_returns_false(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        assert notif_module.mark_as_read(str(ObjectId())) is False

    @patch.object(notif_module, "notifications_collection")
    def test_mark_as_read_success(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        assert notif_module.mark_as_read(str(ObjectId())) is True
        assert mock_col.update_one.call_args[0][1]["$set"]["is_read"] is True

    @patch.object(notif_module, "notifications_collection")
    def test_unicode_garbage_rejected(self, mock_col):
        assert notif_module.mark_as_read("⚠️🔥💀") is False
        mock_col.update_one.assert_not_called()


class TestMarkAllAsRead:

    @patch.object(notif_module, "notifications_collection")
    def test_returns_modified_count(self, mock_col):
        mock_col.update_many.return_value = MagicMock(modified_count=5)
        assert notif_module.mark_all_as_read("user_001") == 5

    @patch.object(notif_module, "notifications_collection")
    def test_returns_zero_when_none_updated(self, mock_col):
        mock_col.update_many.return_value = MagicMock(modified_count=0)
        assert notif_module.mark_all_as_read("user_001") == 0

    @patch.object(notif_module, "notifications_collection")
    def test_payload_sets_is_read_true(self, mock_col):
        mock_col.update_many.return_value = MagicMock(modified_count=3)
        notif_module.mark_all_as_read("user_001")
        assert mock_col.update_many.call_args[0][1]["$set"]["is_read"] is True

    @patch.object(notif_module, "notifications_collection")
    def test_query_scoped_to_user_only(self, mock_col):
        mock_col.update_many.return_value = MagicMock(modified_count=2)
        notif_module.mark_all_as_read("user_001")
        query = mock_col.update_many.call_args[0][0]
        assert query["user_id"] == "user_001" and query.get("is_read") is False


class TestGetUnreadCount:

    @patch.object(notif_module, "notifications_collection")
    def test_returns_correct_count(self, mock_col):
        mock_col.count_documents.return_value = 7
        assert notif_module.get_unread_count("user_001") == 7

    @patch.object(notif_module, "notifications_collection")
    def test_returns_zero_when_all_read(self, mock_col):
        mock_col.count_documents.return_value = 0
        assert notif_module.get_unread_count("user_001") == 0