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
        # Update last login
        users_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {"last_login": datetime.utcnow()}}
        )
        existing["last_login"] = datetime.utcnow()
        return user_to_response(existing)

    # Create new user
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
