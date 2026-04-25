from datetime import datetime
from unittest.mock import MagicMock, patch

from app.services.auth_service import get_or_create_user, user_to_response


def make_user(clerk_id="clerk_123", email="test@example.com", full_name="Test User"):
    return {
        "_id": "mongo_id_1",
        "clerk_id": clerk_id,
        "email": email,
        "full_name": full_name,
        "role": "user",
        "organization": None,
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "last_login": datetime.utcnow(),
    }


def test_user_to_response_converts_id():
    user = make_user()
    result = user_to_response(user)
    assert "id" in result
    assert "_id" not in result
    assert result["id"] == "mongo_id_1"


@patch("app.services.auth_service.users_collection")
def test_get_or_create_user_returns_existing(mock_col):
    existing = make_user()
    mock_col.find_one.return_value = existing
    mock_col.update_one.return_value = MagicMock()

    result = get_or_create_user("clerk_123", "test@example.com", "Test User")

    mock_col.find_one.assert_called_once_with({"clerk_id": "clerk_123"})
    mock_col.update_one.assert_called_once()
    assert result["clerk_id"] == "clerk_123"


@patch("app.services.auth_service.users_collection")
def test_get_or_create_user_creates_new(mock_col):
    new_user = make_user(clerk_id="clerk_new")
    mock_col.find_one.side_effect = [None, new_user]
    insert_result = MagicMock()
    insert_result.inserted_id = "mongo_id_1"
    mock_col.insert_one.return_value = insert_result

    result = get_or_create_user("clerk_new", "new@example.com", "New User")

    mock_col.insert_one.assert_called_once()
    assert result["clerk_id"] == "clerk_new"
