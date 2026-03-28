from bson import ObjectId
from datetime import datetime
from typing import Optional
from app.config import notifications_collection
from app.models.notification import NotificationCreate, NotificationInDB


def notification_to_response(notification: dict) -> dict:
    notification["id"] = str(notification["_id"])
    del notification["_id"]
    return notification


def create_notification(notification_data: NotificationCreate) -> dict:
    """Create a new notification for a user."""
    notif_dict = NotificationInDB(
        **notification_data.model_dump(),
    ).model_dump()

    result = notifications_collection.insert_one(notif_dict)
    created = notifications_collection.find_one({"_id": result.inserted_id})
    return notification_to_response(created)


def get_user_notifications(user_id: str, unread_only: bool = False, limit: int = 50) -> list:
    """Get notifications for a user."""
    query = {"user_id": user_id}
    if unread_only:
        query["is_read"] = False

    notifications = (
        notifications_collection
        .find(query)
        .sort("created_at", -1)
        .limit(limit)
    )
    return [notification_to_response(n) for n in notifications]


def mark_as_read(notification_id: str) -> bool:
    """Mark a notification as read."""
    if not ObjectId.is_valid(notification_id):
        return False
    result = notifications_collection.update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": {"is_read": True}}
    )
    return result.matched_count > 0


def mark_all_as_read(user_id: str) -> int:
    """Mark all notifications as read for a user."""
    result = notifications_collection.update_many(
        {"user_id": user_id, "is_read": False},
        {"$set": {"is_read": True}}
    )
    return result.modified_count


def get_unread_count(user_id: str) -> int:
    """Get the count of unread notifications for a user."""
    return notifications_collection.count_documents({
        "user_id": user_id,
        "is_read": False,
    })
