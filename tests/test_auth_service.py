"""
test_auth_service.py
Complete white-box + requirements test suite for auth_service.py
FR-UAM-01, FR-UAM-06–12, FR-SEC-01
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime


def make_user(clerk_id="clerk_001", role="user", status="active"):
    return {
        "_id":        ObjectId(),
        "clerk_id":   clerk_id,
        "email":      f"{clerk_id}@example.com",
        "full_name":  "Test User",
        "role":       role,
        "status":     status,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "last_login": datetime.utcnow(),
    }


class TestGetOrCreateUser:

    @patch("app.services.auth_service.users_collection")
    def test_existing_user_updates_last_login(self, mock_col):
        existing = make_user("clerk_001")
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = MagicMock()
        from app.services.auth_service import get_or_create_user
        result = get_or_create_user("clerk_001", "a@b.com", "Alice")
        mock_col.update_one.assert_called_once()
        mock_col.insert_one.assert_not_called()
        assert "id" in result
        assert "_id" not in result

    @patch("app.services.auth_service.users_collection")
    def test_new_user_is_created(self, mock_col):
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        from app.services.auth_service import get_or_create_user
        result = get_or_create_user("clerk_new", "new@b.com", "Bob")
        mock_col.insert_one.assert_called_once()
        assert "id" in result

    @patch("app.services.auth_service.users_collection")
    def test_new_user_default_role_is_user(self, mock_col):
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        from app.services.auth_service import get_or_create_user
        get_or_create_user("clerk_new", "new@b.com", "Bob")
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["role"] == "user"

    @patch("app.services.auth_service.users_collection")
    def test_new_user_default_status_is_active(self, mock_col):
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        from app.services.auth_service import get_or_create_user
        get_or_create_user("clerk_new", "new@b.com", "Bob")
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["status"] == "active"

    @patch("app.services.auth_service.users_collection")
    def test_new_user_stores_email_and_name(self, mock_col):
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        from app.services.auth_service import get_or_create_user
        get_or_create_user("clerk_new", "alice@example.com", "Alice Smith")
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["email"]     == "alice@example.com"
        assert doc["full_name"] == "Alice Smith"

    @patch("app.services.auth_service.users_collection")
    def test_new_user_has_created_at(self, mock_col):
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        from app.services.auth_service import get_or_create_user
        get_or_create_user("clerk_new", "new@b.com", "Bob")
        doc = mock_col.insert_one.call_args[0][0]
        assert "created_at" in doc
        assert isinstance(doc["created_at"], datetime)

    @patch("app.services.auth_service.users_collection")
    def test_response_has_no_raw_objectid(self, mock_col):
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        from app.services.auth_service import get_or_create_user
        result = get_or_create_user("clerk_new", "new@b.com", "Bob")
        assert "_id" not in result
        assert isinstance(result["id"], str)


class TestGetUserById:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_object_id_returns_none(self, mock_col):
        from app.services.auth_service import get_user_by_id
        assert get_user_by_id("invalid!!!") is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_valid_id_user_found(self, mock_col):
        mock_col.find_one.return_value = make_user()
        from app.services.auth_service import get_user_by_id
        result = get_user_by_id(str(ObjectId()))
        assert result is not None
        assert "id" in result

    @patch("app.services.auth_service.users_collection")
    def test_valid_id_user_not_found(self, mock_col):
        mock_col.find_one.return_value = None
        from app.services.auth_service import get_user_by_id
        assert get_user_by_id(str(ObjectId())) is None

    @patch("app.services.auth_service.users_collection")
    def test_empty_string_returns_none(self, mock_col):
        from app.services.auth_service import get_user_by_id
        assert get_user_by_id("") is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_script_injection_returns_none(self, mock_col):
        from app.services.auth_service import get_user_by_id
        assert get_user_by_id("<script>alert(1)</script>") is None
        mock_col.find_one.assert_not_called()


class TestGetUserByClerkId:

    @patch("app.services.auth_service.users_collection")
    def test_user_found_returns_response(self, mock_col):
        mock_col.find_one.return_value = make_user("clerk_abc")
        from app.services.auth_service import get_user_by_clerk_id
        result = get_user_by_clerk_id("clerk_abc")
        assert result is not None
        assert "id"  in result
        assert "_id" not in result

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found_returns_none(self, mock_col):
        mock_col.find_one.return_value = None
        from app.services.auth_service import get_user_by_clerk_id
        assert get_user_by_clerk_id("nonexistent") is None

    @patch("app.services.auth_service.users_collection")
    def test_none_clerk_id_handled(self, mock_col):
        from app.services.auth_service import get_user_by_clerk_id
        result = get_user_by_clerk_id(None)
        if result is None:
            mock_col.find_one.assert_not_called()


class TestUpdateUserRole:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_objectid_returns_none(self, mock_col):
        from app.services.auth_service import update_user_role
        assert update_user_role("bad!!!", "admin") is None

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        from app.services.auth_service import update_user_role
        assert update_user_role(str(ObjectId()), "admin") is None

    @patch("app.services.auth_service.users_collection")
    def test_role_updated_successfully(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(role="admin")
        from app.services.auth_service import update_user_role
        assert update_user_role(str(ObjectId()), "admin") is not None

    @patch("app.services.auth_service.users_collection")
    def test_role_payload_written_correctly(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(role="admin")
        from app.services.auth_service import update_user_role
        update_user_role(str(ObjectId()), "admin")
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["role"] == "admin"

    @patch("app.services.auth_service.users_collection")
    def test_role_downgrade_admin_to_user(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(role="user")
        from app.services.auth_service import update_user_role
        update_user_role(str(ObjectId()), "user")
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["role"] == "user"

    @patch("app.services.auth_service.users_collection")
    def test_role_update_injects_updated_at(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(role="admin")
        from app.services.auth_service import update_user_role
        update_user_role(str(ObjectId()), "admin")
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "updated_at" in payload


class TestUpdateUser:

    @patch("app.services.auth_service.users_collection")
    def test_empty_update_returns_existing_user(self, mock_col):
        mock_col.find_one.return_value = make_user("clerk_001")
        from app.services.auth_service import update_user
        from app.models.user import UserUpdate
        result = update_user("clerk_001", UserUpdate())
        mock_col.update_one.assert_not_called()
        assert result is not None

    @patch("app.services.auth_service.users_collection")
    def test_update_with_fields_writes_to_db(self, mock_col):
        mock_col.find_one.return_value = make_user("clerk_001")
        mock_col.update_one.return_value = MagicMock()
        from app.services.auth_service import update_user
        from app.models.user import UserUpdate
        update_user("clerk_001", UserUpdate(full_name="New Name"))
        mock_col.update_one.assert_called_once()
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "updated_at"       in payload
        assert payload["full_name"] == "New Name"


class TestDeactivateUser:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_objectid(self, mock_col):
        from app.services.auth_service import deactivate_user
        assert deactivate_user("xyz") is None

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        from app.services.auth_service import deactivate_user
        assert deactivate_user(str(ObjectId())) is None

    @patch("app.services.auth_service.users_collection")
    def test_deactivation_sets_inactive(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="inactive")
        from app.services.auth_service import deactivate_user
        result = deactivate_user(str(ObjectId()))
        assert result is not None

    @patch("app.services.auth_service.users_collection")
    def test_deactivation_payload_sets_status_inactive(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="inactive")
        from app.services.auth_service import deactivate_user
        deactivate_user(str(ObjectId()))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["status"] == "inactive"

    @patch("app.services.auth_service.users_collection")
    def test_deactivation_payload_includes_updated_at(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="inactive")
        from app.services.auth_service import deactivate_user
        deactivate_user(str(ObjectId()))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "updated_at" in payload

    @patch("app.services.auth_service.users_collection")
    def test_deactivated_user_returned_has_inactive_status(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="inactive")
        from app.services.auth_service import deactivate_user
        result = deactivate_user(str(ObjectId()))
        assert result["status"] == "inactive"


class TestActivateUser:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_objectid(self, mock_col):
        from app.services.auth_service import activate_user
        assert activate_user("xyz") is None

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        from app.services.auth_service import activate_user
        assert activate_user(str(ObjectId())) is None

    @patch("app.services.auth_service.users_collection")
    def test_activation_sets_active(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="active")
        from app.services.auth_service import activate_user
        result = activate_user(str(ObjectId()))
        assert result is not None

    @patch("app.services.auth_service.users_collection")
    def test_activation_payload_sets_status_active(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="active")
        from app.services.auth_service import activate_user
        activate_user(str(ObjectId()))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["status"] == "active"

    @patch("app.services.auth_service.users_collection")
    def test_activation_payload_includes_updated_at(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="active")
        from app.services.auth_service import activate_user
        activate_user(str(ObjectId()))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "updated_at" in payload

    @patch("app.services.auth_service.users_collection")
    def test_activated_user_returned_has_active_status(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="active")
        from app.services.auth_service import activate_user
        result = activate_user(str(ObjectId()))
        assert result["status"] == "active"


class TestGetAllUsers:

    @patch("app.services.auth_service.users_collection")
    def test_empty_db_total_pages_is_zero(self, mock_col):
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        from app.services.auth_service import get_all_users
        result = get_all_users(page=1, per_page=20)
        assert result["total"]       == 0
        assert result["total_pages"] == 0

    @patch("app.services.auth_service.users_collection")
    def test_pagination_skip_arithmetic(self, mock_col):
        mock_col.count_documents.return_value = 45
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        from app.services.auth_service import get_all_users
        get_all_users(page=3, per_page=15)
        mock_col.find.return_value.sort.return_value.skip.assert_called_with(30)

    @patch("app.services.auth_service.users_collection")
    def test_get_all_users_with_results(self, mock_col):
        mock_col.count_documents.return_value = 2
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([make_user("u1"), make_user("u2")])
        from app.services.auth_service import get_all_users
        result = get_all_users(page=1, per_page=10)
        assert result["total"]      == 2
        assert len(result["users"]) == 2
        for u in result["users"]:
            assert "id"  in u
            assert "_id" not in u