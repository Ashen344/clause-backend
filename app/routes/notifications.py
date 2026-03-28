from fastapi import APIRouter, HTTPException, Depends, Query
from app.middleware.auth import get_current_user
from app.services.notification_service import (
    get_user_notifications,
    mark_as_read,
    mark_all_as_read,
    get_unread_count,
)

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


@router.get("/")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Get notifications for the current user."""
    notifications = get_user_notifications(
        user_id=current_user["user_id"],
        unread_only=unread_only,
        limit=limit,
    )
    return {
        "notifications": notifications,
        "count": len(notifications),
    }


@router.get("/unread-count")
async def unread_notification_count(
    current_user: dict = Depends(get_current_user),
):
    """Get count of unread notifications."""
    count = get_unread_count(current_user["user_id"])
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    """Mark a single notification as read."""
    success = mark_as_read(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Notification marked as read"}


@router.patch("/read-all")
async def mark_all_notifications_read(
    current_user: dict = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    count = mark_all_as_read(current_user["user_id"])
    return {"message": f"Marked {count} notifications as read"}
