import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from conftest import make_user


# ══════════════════════════════════════════════════════════════════════
# get_or_create_user()
# PATHS: P1 = user exists | P2 = new user
# ══════════════════════════════════════════════════════════════════════
class TestGetOrCreateUser:

    @patch("app.services.auth_service.users_collection")
    def test_existing_user_updates_last_login(self, mock_col):
        existing = make_user("clerk_001")
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = MagicMock()

        from app.services.auth_service import get_or_create_user

        result = get_or_create_user("clerk_001", "a@b.com", "Alice")

        mock_col.update_one.assert_called_once()
        assert "id" in result
        assert "_id" not in result
        mock_col.insert_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_new_user_is_created(self, mock_col):
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())

        from app.services.auth_service import get_or_create_user

        result = get_or_create_user("clerk_new", "new@b.com", "Bob")

        mock_col.insert_one.assert_called_once()
        assert "id" in result


# ══════════════════════════════════════════════════════════════════════
# get_user_by_id()
# PATHS: P1 = invalid id | P2 = found | P3 = not found
# ══════════════════════════════════════════════════════════════════════
class TestGetUserById:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_object_id_returns_none(self, mock_col):
        from app.services.auth_service import get_user_by_id

        result = get_user_by_id("invalid!!!")
        assert result is None
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

        result = get_user_by_id(str(ObjectId()))
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# update_user_role()
# PATHS: P1 = invalid id | P2 = not found | P3 = success
# ══════════════════════════════════════════════════════════════════════
class TestUpdateUserRole:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_objectid_returns_none(self, mock_col):
        from app.services.auth_service import update_user_role

        result = update_user_role("bad!!!", "admin")
        assert result is None

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)

        from app.services.auth_service import update_user_role

        result = update_user_role(str(ObjectId()), "admin")
        assert result is None

    @patch("app.services.auth_service.users_collection")
    def test_role_updated_successfully(self, mock_col):
        user = make_user()
        user["role"] = "admin"

        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = user

        from app.services.auth_service import update_user_role

        result = update_user_role(str(ObjectId()), "admin")
        assert result is not None


# ══════════════════════════════════════════════════════════════════════
# deactivate_user()
# ══════════════════════════════════════════════════════════════════════
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
        user = make_user(status="inactive")

        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = user

        from app.services.auth_service import deactivate_user

        result = deactivate_user(str(ObjectId()))
        assert result is not None


# ══════════════════════════════════════════════════════════════════════
# activate_user()
# ══════════════════════════════════════════════════════════════════════
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
        user = make_user(status="active")

        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = user

        from app.services.auth_service import activate_user

        result = activate_user(str(ObjectId()))
        assert result is not None


# ══════════════════════════════════════════════════════════════════════
# get_all_users() — pagination
# ══════════════════════════════════════════════════════════════════════
class TestGetAllUsers:

    @patch("app.services.auth_service.users_collection")
    def test_empty_db_total_pages_is_zero(self, mock_col):
        mock_col.count_documents.return_value = 0

        mock_col.find.return_value \
            .sort.return_value \
            .skip.return_value \
            .limit.return_value = iter([])

        from app.services.auth_service import get_all_users

        result = get_all_users(page=1, per_page=20)

        assert result["total"] == 0
        assert result["total_pages"] == 0

    @patch("app.services.auth_service.users_collection")
    def test_pagination_skip_arithmetic(self, mock_col):
        mock_col.count_documents.return_value = 45

        mock_col.find.return_value \
            .sort.return_value \
            .skip.return_value \
            .limit.return_value = iter([])

        from app.services.auth_service import get_all_users

        get_all_users(page=3, per_page=15)

        skip_call = mock_col.find.return_value.sort.return_value.skip
        skip_call.assert_called_with(30)

    # ✅ ✅ THIS IS THE MISSING WHITE-BOX TEST
    @patch("app.services.auth_service.users_collection")
    def test_get_all_users_with_results(self, mock_col):
        mock_col.count_documents.return_value = 2

        users = [make_user("u1"), make_user("u2")]

        mock_col.find.return_value \
            .sort.return_value \
            .skip.return_value \
            .limit.return_value = iter(users)

        from app.services.auth_service import get_all_users

        result = get_all_users(page=1, per_page=10)

        assert result["total"] == 2
        assert result["total_pages"] == 1
        assert len(result["users"]) == 2

        for user in result["users"]:
            assert "id" in user
            assert "_id" not in user