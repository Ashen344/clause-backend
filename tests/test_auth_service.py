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
        """
        PATH P1 — User already exists in DB.
        Expects: update_one called, insert_one NOT called, id returned as string.
        Statement: L17, L19(T), L21, L24, L25
        Branch:    L19 TRUE side
        """
        existing = make_user("clerk_001")
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = MagicMock()

        from app.services.auth_service import get_or_create_user
        result = get_or_create_user("clerk_001", "a@b.com", "Alice")

        mock_col.update_one.assert_called_once()
        args = mock_col.update_one.call_args[0][1]
        assert "last_login" in args["$set"]
        assert "id"  in result
        assert "_id" not in result
        mock_col.insert_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_new_user_is_created(self, mock_col):
        """
        PATH P2 — User does NOT exist in DB.
        Expects: insert_one called with role=user, status=active.
        Statement: L17, L19(F), L28, L38, L39, L40
        Branch:    L19 FALSE side
        """
        mock_col.find_one.side_effect = [None, make_user("clerk_new")]
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())

        from app.services.auth_service import get_or_create_user
        result = get_or_create_user("clerk_new", "new@b.com", "Bob")

        mock_col.insert_one.assert_called_once()
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["role"]     == "user"
        assert doc["status"]   == "active"
        assert doc["clerk_id"] == "clerk_new"
        assert "id" in result


# ══════════════════════════════════════════════════════════════════════
# get_user_by_id()
# PATHS: P1 = invalid id | P2 = found | P3 = not found
# ══════════════════════════════════════════════════════════════════════
class TestGetUserById:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_object_id_returns_none(self, mock_col):
        """
        PATH P1 — Bad ObjectId string.
        Expects: returns None immediately, DB never queried.
        Statement: L51(T), L52
        Branch:    L51 TRUE side
        """
        from app.services.auth_service import get_user_by_id
        result = get_user_by_id("not-a-valid-objectid!!!")

        assert result is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_valid_id_user_found(self, mock_col):
        """
        PATH P2 — Valid ObjectId, user exists in DB.
        Expects: returns dict with id as string, no _id key.
        Statement: L51(F), L53, L54(T), L55
        Branch:    L51 FALSE, L54 TRUE
        """
        mock_col.find_one.return_value = make_user()

        from app.services.auth_service import get_user_by_id
        result = get_user_by_id(str(ObjectId()))

        assert result is not None
        assert "id"  in result
        assert "_id" not in result

    @patch("app.services.auth_service.users_collection")
    def test_valid_id_user_not_found(self, mock_col):
        """
        PATH P3 — Valid ObjectId but user not in DB.
        Expects: returns None.
        Statement: L51(F), L53, L54(F), L56
        Branch:    L51 FALSE, L54 FALSE
        """
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
        """
        PATH P1 — Bad ObjectId.
        Expects: None returned, update_one never called.
        Statement: L98(T), L99
        Branch:    L98 TRUE side
        """
        from app.services.auth_service import update_user_role
        result = update_user_role("bad!!!", "admin")

        assert result is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found(self, mock_col):
        """
        PATH P2 — Valid ObjectId but matched_count=0.
        Expects: None returned.
        Statement: L98(F), L101, L104(T), L105
        Branch:    L98 FALSE, L104 TRUE
        """
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        mock_col.find_one.return_value = None

        from app.services.auth_service import update_user_role
        result = update_user_role(str(ObjectId()), "admin")

        assert result is None

    @patch("app.services.auth_service.users_collection")
    def test_role_updated_successfully(self, mock_col):
        """
        PATH P3 — Valid ObjectId, user updated.
        Expects: role written to DB, updated user returned.
        Statement: L98(F), L101, L104(F), L107
        Branch:    L98 FALSE, L104 FALSE
        """
        user = make_user()
        user["role"] = "admin"
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = user

        from app.services.auth_service import update_user_role
        result = update_user_role(str(ObjectId()), "admin")

        assert result is not None
        payload = mock_col.update_one.call_args[0][1]
        assert payload["$set"]["role"] == "admin"


# ══════════════════════════════════════════════════════════════════════
# deactivate_user()
# PATHS: P1 = invalid id | P2 = not found | P3 = deactivated
# ══════════════════════════════════════════════════════════════════════
class TestDeactivateUser:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_objectid(self, mock_col):
        """
        PATH P1 — Bad ObjectId.
        Statement: L111(T), L112
        Branch:    L111 TRUE side
        """
        from app.services.auth_service import deactivate_user
        assert deactivate_user("xyz") is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found(self, mock_col):
        """
        PATH P2 — Valid id, matched_count=0.
        Statement: L111(F), L114, L118(T), L119
        Branch:    L111 FALSE, L118 TRUE
        """
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        mock_col.find_one.return_value = None

        from app.services.auth_service import deactivate_user
        assert deactivate_user(str(ObjectId())) is None

    @patch("app.services.auth_service.users_collection")
    def test_deactivation_sets_inactive(self, mock_col):
        """
        PATH P3 — User found and deactivated.
        Statement: L111(F), L114, L118(F), L121
        Branch:    L111 FALSE, L118 FALSE
        """
        user = make_user(status="inactive")
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = user

        from app.services.auth_service import deactivate_user
        result = deactivate_user(str(ObjectId()))

        payload = mock_col.update_one.call_args[0][1]
        assert payload["$set"]["status"] == "inactive"
        assert result is not None


# ══════════════════════════════════════════════════════════════════════
# activate_user()
# PATHS: P1 = invalid id | P2 = not found | P3 = activated
# ══════════════════════════════════════════════════════════════════════
class TestActivateUser:

    @patch("app.services.auth_service.users_collection")
    def test_invalid_objectid(self, mock_col):
        from app.services.auth_service import activate_user
        assert activate_user("xyz") is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.auth_service.users_collection")
    def test_user_not_found(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        mock_col.find_one.return_value = None

        from app.services.auth_service import activate_user
        assert activate_user(str(ObjectId())) is None

    @patch("app.services.auth_service.users_collection")
    def test_activation_sets_active(self, mock_col):
        """User successfully reactivated — status must be active."""
        user = make_user(status="active")
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = user

        from app.services.auth_service import activate_user
        result = activate_user(str(ObjectId()))

        payload = mock_col.update_one.call_args[0][1]
        assert payload["$set"]["status"] == "active"
        assert result is not None


# ══════════════════════════════════════════════════════════════════════
# get_all_users() — pagination
# ══════════════════════════════════════════════════════════════════════
class TestGetAllUsers:

    @patch("app.services.auth_service.users_collection")
    def test_empty_db_total_pages_is_zero(self, mock_col):
        """
        When total=0, total_pages must be 0.
        The real code: (total + per_page - 1) // per_page if total > 0 else 0
        """
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value \
               .sort.return_value \
               .skip.return_value \
               .limit.return_value = iter([])

        from app.services.auth_service import get_all_users
        result = get_all_users(page=1, per_page=20)

        assert result["total"]       == 0
        assert result["total_pages"] == 0

    @patch("app.services.auth_service.users_collection")
    def test_pagination_skip_arithmetic(self, mock_col):
        """
        page=3, per_page=15 → skip must equal 30.
        Formula: (page - 1) * per_page = (3-1)*15 = 30
        """
        mock_col.count_documents.return_value = 45
        mock_col.find.return_value \
               .sort.return_value \
               .skip.return_value \
               .limit.return_value = iter([])

        from app.services.auth_service import get_all_users
        get_all_users(page=3, per_page=15)

        skip_call = mock_col.find.return_value.sort.return_value.skip
        skip_call.assert_called_with(30)