from datetime import datetime
from bson import ObjectId
from app.config import audit_logs_collection
from app.models.audit_log import AuditAction


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
        logs.append(log)

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }
