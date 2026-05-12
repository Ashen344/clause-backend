from datetime import datetime, timezone
from bson import ObjectId
from app.config import audit_logs_collection, users_collection
from app.models.audit_log import AuditAction

# Cache clerk_id → display name so we don't hit MongoDB on every row
_user_cache: dict = {}


def create_audit_log(
    action: AuditAction,
    resource_type: str,
    resource_id: str,
    user_id: str,
    user_email: str = None,
    details: str = None,
    changes: dict = None,
    ip_address: str = None,
):
    """Create an audit log entry."""
    log = {
        "action": action.value,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "user_id": user_id,
        "user_email": user_email,
        "details": details,
        "changes": changes,
        "ip_address": ip_address,
        "created_at": datetime.utcnow(),
    }
    audit_logs_collection.insert_one(log)


def get_audit_logs(
    resource_type: str = None,
    resource_id: str = None,
    user_id: str = None,
    action: str = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Get audit logs with optional filters."""
    query = {}

    if resource_type:
        query["resource_type"] = resource_type
    if resource_id:
        query["resource_id"] = resource_id
    if user_id:
        query["user_id"] = user_id
    if action:
        query["action"] = action

    skip = (page - 1) * per_page
    total = audit_logs_collection.count_documents(query)

    logs_cursor = (
        audit_logs_collection
        .find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(per_page)
    )

    logs = []
    for log in logs_cursor:
        log["id"] = str(log["_id"])
        del log["_id"]

        # Ensure created_at is a UTC ISO string with Z so browsers parse it correctly
        ts = log.get("created_at")
        if isinstance(ts, datetime):
            log["created_at"] = ts.replace(tzinfo=timezone.utc).isoformat()

        # Resolve user display name when user_email is missing
        if not log.get("user_email") and log.get("user_id"):
            clerk_id = log["user_id"]
            if clerk_id not in _user_cache:
                db_user = users_collection.find_one(
                    {"clerk_id": clerk_id}, {"full_name": 1, "email": 1}
                )
                _user_cache[clerk_id] = (
                    db_user.get("full_name") or db_user.get("email") or clerk_id
                    if db_user else clerk_id
                )
            log["user_email"] = _user_cache[clerk_id]

        logs.append(log)

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }
