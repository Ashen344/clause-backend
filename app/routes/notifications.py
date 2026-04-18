from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from app.middleware.auth import get_current_user
from app.services.notification_service import (
    get_user_notifications,
    mark_as_read,
    mark_all_as_read,
    get_unread_count,
)
from app.services.email_service import send_test_email, scan_and_send_expiry_alerts
from app.config import SMTP_EMAIL

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


class TestEmailRequest(BaseModel):
    to_email: str


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


# ── Email endpoints ───────────────────────────────────────────────────────────

@router.get("/email-config")
async def get_email_config(current_user: dict = Depends(get_current_user)):
    """Return whether SMTP email is configured (never expose the password)."""
    return {
        "configured": bool(SMTP_EMAIL),
        "smtp_email": SMTP_EMAIL if SMTP_EMAIL else None,
    }


@router.post("/send-test-email")
async def send_test_email_endpoint(
    body: TestEmailRequest,
    current_user: dict = Depends(get_current_user),
):
    """Send a test email to verify SMTP configuration."""
    if not body.to_email:
        raise HTTPException(status_code=400, detail="to_email is required")
    ok = send_test_email(body.to_email)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="Failed to send email. Check SMTP_EMAIL and SMTP_PASSWORD in your .env file.",
        )
    return {"message": f"Test email sent to {body.to_email}"}


@router.post("/send-expiry-alerts")
async def trigger_expiry_alerts(
    dry_run: bool = Query(False, description="If true, count only — do not send"),
    current_user: dict = Depends(get_current_user),
):
    """Scan all contracts and send expiry alert emails (admin/manager only)."""
    if current_user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required")
    result = scan_and_send_expiry_alerts(dry_run=dry_run)
    return result
