import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import app.services.auth_service as auth_module


def make_user(clerk_id="clerk_123", role="user", status="active"):
    return {
        "_id": ObjectId(),
        "clerk_id": clerk_id,
        "email": "test@example.com",
        "full_name": "Test User",
        "role": role,
        "status": status,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "last_login": datetime.utcnow(),
    }


class TestGetOrCreateUser:

    @patch.object(auth_module, "users_collection")
    def test_existing_user_updates_last_login(self, mock_col):
        """FR-UAM-01: User authentication via Clerk ID"""
        existing = make_user()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = MagicMock()
        
        result = auth_module.get_or_create_user("clerk_123", "test@example.com", "Test User")
        
        assert result is not None
        assert "id" in result
        mock_col.update_one.assert_called_once()

    @patch.object(auth_module, "users_collection")
    def test_new_user_is_created(self, mock_col):
        """FR-UAM-06: New user creation with default role"""
        mock_col.find_one.return_value = None
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        mock_col.find_one.side_effect = [None, make_user()]
        
        result = auth_module.get_or_create_user("clerk_new", "new@example.com", "New User")
        
        assert result is not None
        mock_col.insert_one.assert_called_once()


class TestGetUserById:

    @patch.object(auth_module, "users_collection")
    def test_invalid_objectid_returns_none(self, mock_col):
        """NFR-RB-06: Input validation"""
        assert auth_module.get_user_by_id("invalid!!!") is None
        mock_col.find_one.assert_not_called()

    @patch.object(auth_module, "users_collection")
    def test_valid_id_user_found(self, mock_col):
        """FR-UAM-07: User lookup by ID"""
        mock_col.find_one.return_value = make_user()
        result = auth_module.get_user_by_id(str(ObjectId()))
        assert result is not None
        assert "id" in result

    @patch.object(auth_module, "users_collection")
    def test_valid_id_user_not_found(self, mock_col):
        mock_col.find_one.return_value = None
        assert auth_module.get_user_by_id(str(ObjectId())) is None


class TestGetUserByClerkId:

    @patch.object(auth_module, "users_collection")
    def test_user_found_returns_response(self, mock_col):
        """FR-UAM-08: Lookup by Clerk ID"""
        mock_col.find_one.return_value = make_user()
        result = auth_module.get_user_by_clerk_id("clerk_123")
        assert result is not None

    @patch.object(auth_module, "users_collection")
    def test_user_not_found_returns_none(self, mock_col):
        mock_col.find_one.return_value = None
        assert auth_module.get_user_by_clerk_id("nonexistent") is None


class TestUpdateUserRole:

    @patch.object(auth_module, "users_collection")
    def test_invalid_objectid_returns_none(self, mock_col):
        """NFR-RB-06: Input validation for role update"""
        assert auth_module.update_user_role("bad!!!", "admin") is None

    @patch.object(auth_module, "users_collection")
    def test_user_not_found(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        assert auth_module.update_user_role(str(ObjectId()), "admin") is None

    @patch.object(auth_module, "users_collection")
    def test_role_updated_successfully(self, mock_col):
        """FR-UAM-09: Role update (admin action)"""
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(role="admin")
        result = auth_module.update_user_role(str(ObjectId()), "admin")
        assert result is not None


class TestUpdateUser:

    @patch.object(auth_module, "users_collection")
    def test_empty_update_returns_existing_user(self, mock_col):
        """Edge case: No fields to update"""
        from app.models.user import UserUpdate
        mock_col.find_one.return_value = make_user()
        result = auth_module.update_user("clerk_123", UserUpdate())
        mock_col.update_one.assert_not_called()

    @patch.object(auth_module, "users_collection")
    def test_update_with_fields_writes_to_db(self, mock_col):
        """FR-UAM-10: User profile update"""
        from app.models.user import UserUpdate
        mock_col.update_one.return_value = MagicMock()
        mock_col.find_one.return_value = make_user()
        auth_module.update_user("clerk_123", UserUpdate(full_name="New Name"))
        mock_col.update_one.assert_called_once()


class TestDeactivateUser:

    @patch.object(auth_module, "users_collection")
    def test_invalid_objectid(self, mock_col):
        assert auth_module.deactivate_user("xyz") is None

    @patch.object(auth_module, "users_collection")
    def test_user_not_found(self, mock_col):
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        assert auth_module.deactivate_user(str(ObjectId())) is None

    @patch.object(auth_module, "users_collection")
    def test_deactivation_sets_inactive(self, mock_col):
        """FR-UAM-11: User deactivation"""
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="inactive")
        result = auth_module.deactivate_user(str(ObjectId()))
        assert result["status"] == "inactive"


class TestGetAllUsers:

    @patch.object(auth_module, "users_collection")
    def test_pagination_arithmetic(self, mock_col):
        """FR-UAM-12: Pagination"""
        mock_col.count_documents.return_value = 50
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        result = auth_module.get_all_users(page=3, per_page=15)
        mock_col.find.return_value.sort.return_value.skip.assert_called_with(30)

class TestActivateUser:

    @patch.object(auth_module, "users_collection")
    def test_invalid_objectid(self, mock_col):
        """NFR-RB-06: Input validation"""
        assert auth_module.activate_user("bad-id") is None

    @patch.object(auth_module, "users_collection")
    def test_activation_sets_active(self, mock_col):
        """FR-UAM-13: User activation"""
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_user(status="active")
        result = auth_module.activate_user(str(ObjectId()))
        assert result["status"] == "active"