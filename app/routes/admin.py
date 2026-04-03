from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta
from app.config import (
    contracts_collection,
    workflows_collection,
    approvals_collection,
    users_collection,
    templates_collection,
    audit_logs_collection,
    notifications_collection,
)
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["Admin Dashboard"])


def _require_admin(current_user: dict):
    """Check if user has admin role."""
    user = users_collection.find_one({"clerk_id": current_user["user_id"]})
    if not user or user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required.")
    return user


# ─── Overview Stats ──────────────────────────────────────

@router.get("/stats")
async def admin_stats(current_user: dict = Depends(get_current_user)):
    """Comprehensive admin overview stats."""
    _require_admin(current_user)
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    thirty_days_later = now + timedelta(days=30)

    # Users
    total_users = users_collection.count_documents({})
    active_users = users_collection.count_documents({"status": "active"})
    inactive_users = users_collection.count_documents({"status": {"$in": ["inactive", "suspended"]}})
    users_by_role = list(users_collection.aggregate([
        {"$group": {"_id": "$role", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]))

    # Contracts
    total_contracts = contracts_collection.count_documents({})
    active_contracts = contracts_collection.count_documents({"status": "active"})
    draft_contracts = contracts_collection.count_documents({"status": "draft"})
    expired_contracts = contracts_collection.count_documents({"status": "expired"})
    terminated_contracts = contracts_collection.count_documents({"status": "terminated"})
    contracts_this_month = contracts_collection.count_documents({
        "created_at": {"$gte": thirty_days_ago}
    })

    # Contract value
    value_pipeline = [
        {"$match": {"value": {"$ne": None}}},
        {"$group": {
            "_id": None,
            "total_value": {"$sum": "$value"},
            "avg_value": {"$avg": "$value"},
            "max_value": {"$max": "$value"},
        }},
    ]
    value_result = list(contracts_collection.aggregate(value_pipeline))
    contract_values = value_result[0] if value_result else {"total_value": 0, "avg_value": 0, "max_value": 0}

    # Risk
    high_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "high"})
    medium_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "medium"})
    low_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "low"})

    # Expiring soon
    expiring_soon = contracts_collection.count_documents({
        "status": "active",
        "end_date": {"$gte": now, "$lte": thirty_days_later},
    })

    # Approvals
    pending_approvals = approvals_collection.count_documents({"status": "pending"})
    total_approvals = approvals_collection.count_documents({})
    approved_count = approvals_collection.count_documents({"status": "approved"})
    rejected_count = approvals_collection.count_documents({"status": "rejected"})

    # Workflows
    active_workflows = workflows_collection.count_documents({"status": "active"})
    completed_workflows = workflows_collection.count_documents({"status": "completed"})

    # Templates
    total_templates = templates_collection.count_documents({})
    active_templates = templates_collection.count_documents({"is_active": True})

    # Audit logs (last 30 days)
    recent_audit_count = audit_logs_collection.count_documents({
        "created_at": {"$gte": thirty_days_ago}
    })

    # Unread notifications system-wide
    unread_notifications = notifications_collection.count_documents({"is_read": False})

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "inactive": inactive_users,
            "by_role": [{"role": r["_id"], "count": r["count"]} for r in users_by_role],
        },
        "contracts": {
            "total": total_contracts,
            "active": active_contracts,
            "draft": draft_contracts,
            "expired": expired_contracts,
            "terminated": terminated_contracts,
            "created_this_month": contracts_this_month,
            "expiring_soon": expiring_soon,
        },
        "contract_values": {
            "total_value": round(contract_values.get("total_value", 0), 2),
            "avg_value": round(contract_values.get("avg_value", 0), 2),
            "max_value": round(contract_values.get("max_value", 0), 2),
        },
        "risk": {
            "high": high_risk,
            "medium": medium_risk,
            "low": low_risk,
        },
        "approvals": {
            "pending": pending_approvals,
            "total": total_approvals,
            "approved": approved_count,
            "rejected": rejected_count,
        },
        "workflows": {
            "active": active_workflows,
            "completed": completed_workflows,
        },
        "templates": {
            "total": total_templates,
            "active": active_templates,
        },
        "system": {
            "recent_audit_actions": recent_audit_count,
            "unread_notifications": unread_notifications,
        },
    }


# ─── User Activity ───────────────────────────────────────

@router.get("/user-activity")
async def user_activity(current_user: dict = Depends(get_current_user)):
    """Get recent user activity from audit logs."""
    _require_admin(current_user)

    pipeline = [
        {"$sort": {"created_at": -1}},
        {"$limit": 20},
        {"$project": {
            "_id": 0,
            "id": {"$toString": "$_id"},
            "action": 1,
            "resource_type": 1,
            "user_email": 1,
            "details": 1,
            "created_at": 1,
        }},
    ]
    logs = list(audit_logs_collection.aggregate(pipeline))
    return logs


# ─── Contracts by Workflow Stage ─────────────────────────

@router.get("/contracts-by-stage")
async def contracts_by_stage(current_user: dict = Depends(get_current_user)):
    """Get contract count by workflow stage (for funnel/pipeline view)."""
    _require_admin(current_user)

    pipeline = [
        {"$group": {"_id": "$workflow_stage", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    results = list(contracts_collection.aggregate(pipeline))
    return [{"stage": r["_id"], "count": r["count"]} for r in results]


# ─── Contract Value by Type ──────────────────────────────

@router.get("/value-by-type")
async def contract_value_by_type(current_user: dict = Depends(get_current_user)):
    """Get total contract value grouped by contract type."""
    _require_admin(current_user)

    pipeline = [
        {"$match": {"value": {"$ne": None}}},
        {"$group": {
            "_id": "$contract_type",
            "total_value": {"$sum": "$value"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total_value": -1}},
    ]
    results = list(contracts_collection.aggregate(pipeline))
    return [
        {"type": r["_id"], "total_value": round(r["total_value"], 2), "count": r["count"]}
        for r in results
    ]


# ─── Approval Turnaround ────────────────────────────────

@router.get("/approval-stats")
async def approval_stats(current_user: dict = Depends(get_current_user)):
    """Get approval status breakdown."""
    _require_admin(current_user)

    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    results = list(approvals_collection.aggregate(pipeline))
    return [{"status": r["_id"], "count": r["count"]} for r in results]


# ─── Recent Users ────────────────────────────────────────

@router.get("/recent-users")
async def recent_users(current_user: dict = Depends(get_current_user)):
    """Get recently joined users."""
    _require_admin(current_user)

    users = (
        users_collection.find()
        .sort("created_at", -1)
        .limit(10)
    )
    results = []
    for u in users:
        results.append({
            "id": str(u["_id"]),
            "full_name": u.get("full_name"),
            "email": u.get("email"),
            "role": u.get("role"),
            "status": u.get("status"),
            "created_at": u.get("created_at"),
            "last_login": u.get("last_login"),
        })
    return results
