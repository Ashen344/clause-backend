from datetime import datetime
from typing import Optional
from bson import ObjectId
from app.config import users_collection
from app.models.user import UserCreate, UserUpdate


def user_to_response(user: dict) -> dict:
    """Convert a MongoDB user document to API response format."""
    user["id"] = str(user["_id"])
    del user["_id"]
    return user


def get_or_create_user(clerk_id: str, email: str, full_name: str) -> dict:
    """Find existing user by Clerk ID or create a new one (called on first login)."""
    existing = users_collection.find_one({"clerk_id": clerk_id})

    if existing:
        users_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {"last_login": datetime.utcnow()}}
        )
        existing["last_login"] = datetime.utcnow()
        return user_to_response(existing)

    new_user = {
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

    result = users_collection.insert_one(new_user)
    created = users_collection.find_one({"_id": result.inserted_id})
    return user_to_response(created)


def get_user_by_clerk_id(clerk_id: str) -> Optional[dict]:
    """Look up a user by their Clerk authentication ID."""
    user = users_collection.find_one({"clerk_id": clerk_id})
    if user:
        return user_to_response(user)
    return None


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Look up a user by their MongoDB ID."""
    if not ObjectId.is_valid(user_id):
        return None
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        return user_to_response(user)
    return None


def update_user(clerk_id: str, update_data: UserUpdate) -> Optional[dict]:
    """Update a user's profile information."""
    update_dict = update_data.model_dump(exclude_unset=True)
    if not update_dict:
        return get_user_by_clerk_id(clerk_id)

    update_dict["updated_at"] = datetime.utcnow()
    users_collection.update_one(
        {"clerk_id": clerk_id},
        {"$set": update_dict}
    )
    return get_user_by_clerk_id(clerk_id)


def get_all_users(page: int = 1, per_page: int = 20) -> dict:
    """Get paginated list of all users (admin only)."""
    skip = (page - 1) * per_page
    total = users_collection.count_documents({})

    users_cursor = (
        users_collection
        .find()
        .sort("created_at", -1)
        .skip(skip)
        .limit(per_page)
    )

    users = [user_to_response(u) for u in users_cursor]

    return {
        "users": users,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


def update_user_role(user_id: str, new_role: str) -> Optional[dict]:
    """Update a user's role (admin only)."""
    if not ObjectId.is_valid(user_id):
        return None

    result = users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": new_role, "updated_at": datetime.utcnow()}}
    )

    if result.matched_count == 0:
        return None

    return get_user_by_id(user_id)


def deactivate_user(user_id: str) -> Optional[dict]:
    """Deactivate a user account (admin only)."""
    if not ObjectId.is_valid(user_id):
        return None

    result = users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"status": "inactive", "updated_at": datetime.utcnow()}}
    )

    if result.matched_count == 0:
        return None

    return get_user_by_id(user_id)


def activate_user(user_id: str) -> Optional[dict]:
    """Reactivate a previously deactivated user account (admin only)."""
    if not ObjectId.is_valid(user_id):
        return None

    result = users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"status": "active", "updated_at": datetime.utcnow()}}
    )

    if result.matched_count == 0:
        return None

    return get_user_by_id(user_id)


# ─── Dashboard Preferences ────────────────────────────────────────────

def _default_preferences() -> dict:
    """Returns the default preferences for a new user."""
    return {
        "visible_widgets": [
            "total_contracts",
            "active_contracts",
            "expiring_soon",
            "high_risk",
        ],
        "default_contract_filter": None,
        "pinned_contracts": [],
        "accent_color": "indigo",
        "theme": "light",
    }


def get_preferences(clerk_id: str) -> dict:
    """Get the user's dashboard preferences."""
    user = users_collection.find_one({"clerk_id": clerk_id})
    if not user:
        return _default_preferences()

    stored = user.get("preferences")

    if not stored:
        return _default_preferences()

    merged = {**_default_preferences(), **stored}

    if not merged.get("visible_widgets"):
        merged["visible_widgets"] = _default_preferences()["visible_widgets"]

    return merged


def save_preferences(clerk_id: str, preferences: dict) -> dict:
    """Save the user's dashboard preferences."""

    if "pinned_contracts" in preferences:
        preferences["pinned_contracts"] = preferences["pinned_contracts"][:5]

    if not preferences.get("visible_widgets"):
        preferences["visible_widgets"] = _default_preferences()["visible_widgets"]

    users_collection.update_one(
        {"clerk_id": clerk_id},
        {"$set": {
            "preferences": preferences,
            "updated_at": datetime.utcnow(),
        }}
    )

    return preferences
