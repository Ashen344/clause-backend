from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from app.middleware.auth import get_current_user, get_current_user_with_role
from app.services.notification_service import (
    get_user_notifications,
    mark_as_read,
    mark_all_as_read,
    get_unread_count,
)
from app.services.email_service import send_test_email, scan_and_send_expiry_alerts
from app.config import notification_settings_collection
from app.models.notification_config import NotificationSettingsDoc
import os

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
async def get_email_config(_current_user: dict = Depends(get_current_user)):
    """Return whether SMTP email is configured (never expose the password)."""
    smtp_email = os.getenv("SMTP_EMAIL", "")
    return {
        "configured": bool(smtp_email),
        "smtp_email": smtp_email if smtp_email else None,
    }


@router.post("/send-test-email")
async def send_test_email_endpoint(
    body: TestEmailRequest,
    _current_user: dict = Depends(get_current_user),
):
    """Send a test email to verify SMTP configuration."""
    if not body.to_email:
        raise HTTPException(status_code=400, detail="to_email is required")
    ok, error_msg = send_test_email(body.to_email)
    if not ok:
        raise HTTPException(status_code=503, detail=error_msg or "Failed to send email. Check your SMTP settings.")
    return {"message": f"Test email sent to {body.to_email}"}


@router.post("/send-expiry-alerts")
async def trigger_expiry_alerts(
    dry_run: bool = Query(False, description="If true, count only — do not send"),
    current_user: dict = Depends(get_current_user_with_role),
):
    """Scan all contracts and send expiry alert emails (admin/manager only)."""
    if current_user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required")
    result = scan_and_send_expiry_alerts(dry_run=dry_run)
    return result


# ── Notification settings (admin only) ───────────────────────────────────────

_MASKED = "__set__"

def _mask(doc: dict) -> dict:
    """Return a copy of doc with sensitive fields replaced by _MASKED sentinel."""
    import copy
    d = copy.deepcopy(doc)
    if d.get("email", {}).get("password"):
        d["email"]["password"] = _MASKED
    if d.get("sms", {}).get("auth_token"):
        d["sms"]["auth_token"] = _MASKED
    return d


def _default_settings() -> dict:
    return NotificationSettingsDoc().model_dump()


@router.get("/settings")
async def get_notification_settings(_current_user: dict = Depends(get_current_user)):
    """Return current notification settings (passwords masked)."""
    doc = notification_settings_collection.find_one({}, {"_id": 0})
    return _mask(doc) if doc else _default_settings()


@router.put("/settings")
async def save_notification_settings(
    body: dict,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Persist notification settings (admin/manager only). Masked sentinel preserves stored secrets."""
    if current_user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    existing = notification_settings_collection.find_one({}, {"_id": 0}) or {}

    # Preserve stored secrets when the frontend sends back the masked sentinel
    if body.get("email", {}).get("password") == _MASKED:
        body.setdefault("email", {})["password"] = existing.get("email", {}).get("password", "")
    if body.get("sms", {}).get("auth_token") == _MASKED:
        body.setdefault("sms", {})["auth_token"] = existing.get("sms", {}).get("auth_token", "")

    notification_settings_collection.replace_one({}, body, upsert=True)
    return {"message": "Settings saved"}
