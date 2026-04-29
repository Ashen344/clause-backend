import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime

# ── Fix: explicitly import the module first so @patch can find it ─────────────
import app.services.notification_service as notif_module


def make_notification(user_id="user_001", is_read=False):
    return {
        "_id":               ObjectId(),
        "user_id":           user_id,
        "notification_type": "approval_required",
        "title":             "Approval Needed",
        "message":           "Please review the contract.",
        "contract_id":       str(ObjectId()),
        "workflow_id":       str(ObjectId()),
        "link":              "/contracts/123",
        "is_read":           is_read,
        "created_at":        datetime.utcnow(),
    }


# ══════════════════════════════════════════════════════════════════════
# notification_to_response()
# ══════════════════════════════════════════════════════════════════════
class TestNotificationToResponse:

    def test_converts_id_to_string(self):
        from app.services.notification_service import notification_to_response
        notif = make_notification()
        result = notification_to_response(notif)
        assert "id"  in result
        assert "_id" not in result
        assert isinstance(result["id"], str)

    def test_other_fields_preserved(self):
        from app.services.notification_service import notification_to_response
        notif = make_notification(user_id="user_abc", is_read=True)
        result = notification_to_response(notif)
        assert result["user_id"] == "user_abc"
        assert result["is_read"] is True
        assert result["title"]   == "Approval Needed"


# ══════════════════════════════════════════════════════════════════════
# get_user_notifications()
# PATHS: P1 = all notifications | P2 = unread_only filter applied
# ══════════════════════════════════════════════════════════════════════
class TestGetUserNotifications:

    @patch.object(notif_module, "notifications_collection")
    def test_all_notifications_no_filter(self, mock_col):
        """
        PATH P1 — unread_only=False (default).
        Query must NOT include is_read filter.
        Branch: unread_only FALSE side
        """
        notif = make_notification()
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([notif])

        result = notif_module.get_user_notifications("user_001", unread_only=False)

        query = mock_col.find.call_args[0][0]
        assert query == {"user_id": "user_001"}
        assert "is_read" not in query
        assert len(result) == 1

    @patch.object(notif_module, "notifications_collection")
    def test_unread_only_filter_applied(self, mock_col):
        """
        PATH P2 — unread_only=True.
        Query must include is_read=False.
        Branch: unread_only TRUE side
        """
        notif = make_notification(is_read=False)
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([notif])

        result = notif_module.get_user_notifications("user_001", unread_only=True)

        query = mock_col.find.call_args[0][0]
        assert query["is_read"] is False
        assert len(result) == 1

    @patch.object(notif_module, "notifications_collection")
    def test_empty_result_returns_empty_list(self, mock_col):
        """No notifications → empty list."""
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([])

        result = notif_module.get_user_notifications("user_nobody")
        assert result == []

    @patch.object(notif_module, "notifications_collection")
    def test_custom_limit_passed_to_query(self, mock_col):
        """limit parameter must be forwarded to DB."""
        mock_col.find.return_value.sort.return_value.limit.return_value = iter([])

        notif_module.get_user_notifications("user_001", limit=10)

        limit_call = mock_col.find.return_value.sort.return_value.limit
        limit_call.assert_called_with(10)


# ══════════════════════════════════════════════════════════════════════
# mark_as_read()
# PATHS: P1 = invalid ObjectId | P2 = not found | P3 = success
# ══════════════════════════════════════════════════════════════════════
class TestMarkAsRead:

    @patch.object(notif_module, "notifications_collection")
    def test_invalid_objectid_returns_false(self, mock_col):
        """
        PATH P1 — Bad ObjectId → False, DB never touched.
        Branch: guard TRUE side
        """
        result = notif_module.mark_as_read("not-valid-id")
        assert result is False
        mock_col.update_one.assert_not_called()

    @patch.object(notif_module, "notifications_collection")
    def test_not_found_returns_false(self, mock_col):
        """
        PATH P2 — Valid ObjectId, matched_count=0.
        Branch: matched_count == 0
        """
        mock_col.update_one.return_value = MagicMock(matched_count=0)

        result = notif_module.mark_as_read(str(ObjectId()))
        assert result is False

    @patch.object(notif_module, "notifications_collection")
    def test_mark_as_read_success(self, mock_col):
        """
        PATH P3 — Valid ObjectId, matched_count=1 → True.
        Branch: matched_count > 0
        """
        mock_col.update_one.return_value = MagicMock(matched_count=1)

        result = notif_module.mark_as_read(str(ObjectId()))
        assert result is True
        payload = mock_col.update_one.call_args[0][1]
        assert payload["$set"]["is_read"] is True


# ══════════════════════════════════════════════════════════════════════
# mark_all_as_read()
# PATHS: P1 = some updated | P2 = none updated
# ══════════════════════════════════════════════════════════════════════
class TestMarkAllAsRead:

    @patch.object(notif_module, "notifications_collection")
    def test_returns_modified_count(self, mock_col):
        """PATH P1 — Some notifications marked as read."""
        mock_col.update_many.return_value = MagicMock(modified_count=5)

        result = notif_module.mark_all_as_read("user_001")

        assert result == 5
        query = mock_col.update_many.call_args[0][0]
        assert query["user_id"] == "user_001"
        assert query["is_read"] is False

    @patch.object(notif_module, "notifications_collection")
    def test_returns_zero_when_none_updated(self, mock_col):
        """PATH P2 — All already read → modified_count=0."""
        mock_col.update_many.return_value = MagicMock(modified_count=0)

        result = notif_module.mark_all_as_read("user_001")
        assert result == 0


# ══════════════════════════════════════════════════════════════════════
# get_unread_count()
# ══════════════════════════════════════════════════════════════════════
class TestGetUnreadCount:

    @patch.object(notif_module, "notifications_collection")
    def test_returns_correct_count(self, mock_col):
        """count_documents called with correct query."""
        mock_col.count_documents.return_value = 7

        result = notif_module.get_unread_count("user_001")

        assert result == 7
        query = mock_col.count_documents.call_args[0][0]
        assert query["user_id"] == "user_001"
        assert query["is_read"] is False

    @patch.object(notif_module, "notifications_collection")
    def test_returns_zero_when_all_read(self, mock_col):
        """Zero unread → returns 0."""
        mock_col.count_documents.return_value = 0

        result = notif_module.get_unread_count("user_001")
        assert result == 0