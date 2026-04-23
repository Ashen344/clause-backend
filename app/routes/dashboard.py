from fastapi import APIRouter, Depends
from datetime import datetime, timedelta
from app.config import (
    contracts_collection,
    workflows_collection,
    approvals_collection,
    users_collection,
)
from app.middleware.auth import get_current_user_with_role

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _is_privileged(current_user: dict) -> bool:
    """Returns True if user is admin or manager (sees org-wide data)."""
    return current_user.get("role") in ("admin", "manager")


@router.get("/stats")
async def get_dashboard_stats(
    current_user: dict = Depends(get_current_user_with_role),
):
    """Get dashboard statistics.
    Admins/managers see org-wide stats.
    Regular users see only their own contracts.
    """
    now = datetime.utcnow()
    thirty_days_later = now + timedelta(days=30)
    privileged = _is_privileged(current_user)

    # Base filter — admin/manager sees all, user sees own
    base = {} if privileged else {"created_by": current_user["user_id"]}

    total     = contracts_collection.count_documents(base)
    active    = contracts_collection.count_documents({**base, "status": "active"})
    draft     = contracts_collection.count_documents({**base, "status": "draft"})
    expired   = contracts_collection.count_documents({**base, "status": "expired"})
    terminated = contracts_collection.count_documents({**base, "status": "terminated"})

    expiring_soon = contracts_collection.count_documents({
        **base,
        "status": "active",
        "end_date": {"$gte": now, "$lte": thirty_days_later},
    })

    high_risk   = contracts_collection.count_documents({**base, "ai_analysis.risk_level": "high"})
    medium_risk = contracts_collection.count_documents({**base, "ai_analysis.risk_level": "medium"})
    low_risk    = contracts_collection.count_documents({**base, "ai_analysis.risk_level": "low"})

    # Pending approvals for this user
    approval_filter = (
        {"status": "pending"}
        if privileged
        else {"status": "pending", "approver_id": current_user["user_id"]}
    )
    pending_approvals = approvals_collection.count_documents(approval_filter)

    # Active workflows
    workflow_filter = (
        {"status": "active"}
        if privileged
        else {"status": "active", "created_by": current_user["user_id"]}
    )
    active_workflows = workflows_collection.count_documents(workflow_filter)

    result = {
        "total_contracts": total,
        "active_contracts": active,
        "draft_contracts": draft,
        "expired_contracts": expired,
        "terminated_contracts": terminated,
        "expiring_soon": expiring_soon,
        "pending_approvals": pending_approvals,
        "active_workflows": active_workflows,
        "risk_summary": {
            "high": high_risk,
            "medium": medium_risk,
            "low": low_risk,
        },
    }

    # Only admins/managers see total_users
    if privileged:
        result["total_users"] = users_collection.count_documents({})

    return result


@router.get("/contracts-by-type")
async def contracts_by_type(
    current_user: dict = Depends(get_current_user_with_role),
):
    """Contract count by type. Filtered by user for non-admins."""
    privileged = _is_privileged(current_user)
    match_stage = {} if privileged else {"$match": {"created_by": current_user["user_id"]}}

    pipeline = []
    if not privileged:
        pipeline.append({"$match": {"created_by": current_user["user_id"]}})
    pipeline += [
        {"$group": {"_id": "$contract_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]

    results = list(contracts_collection.aggregate(pipeline))
    return [{"type": r["_id"], "count": r["count"]} for r in results]


@router.get("/contracts-by-status")
async def contracts_by_status(
    current_user: dict = Depends(get_current_user_with_role),
):
    """Contract count by status. Filtered by user for non-admins."""
    privileged = _is_privileged(current_user)

    pipeline = []
    if not privileged:
        pipeline.append({"$match": {"created_by": current_user["user_id"]}})
    pipeline += [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]

    results = list(contracts_collection.aggregate(pipeline))
    return [{"status": r["_id"], "count": r["count"]} for r in results]


@router.get("/expiring-soon")
async def expiring_soon_contracts(
    current_user: dict = Depends(get_current_user_with_role),
):
    """Contracts expiring in next 30 days. Filtered by user for non-admins."""
    now = datetime.utcnow()
    thirty_days_later = now + timedelta(days=30)
    privileged = _is_privileged(current_user)

    query = {
        "status": "active",
        "end_date": {"$gte": now, "$lte": thirty_days_later},
    }
    if not privileged:
        query["created_by"] = current_user["user_id"]

    contracts = contracts_collection.find(query).sort("end_date", 1).limit(20)

    results = []
    for c in contracts:
        days_remaining = (c["end_date"] - now).days
        results.append({
            "id": str(c["_id"]),
            "title": c.get("title"),
            "contract_type": c.get("contract_type"),
            "end_date": c["end_date"].isoformat(),
            "days_remaining": days_remaining,
        })

    return results


@router.get("/recent-activity")
async def recent_activity(
    current_user: dict = Depends(get_current_user_with_role),
):
    """Recently updated contracts. Filtered by user for non-admins."""
    privileged = _is_privileged(current_user)

    query = {} if privileged else {"created_by": current_user["user_id"]}

    contracts = (
        contracts_collection
        .find(query)
        .sort("updated_at", -1)
        .limit(10)
    )

    results = []
    for c in contracts:
        results.append({
            "id": str(c["_id"]),
            "title": c.get("title"),
            "status": c.get("status"),
            "workflow_stage": c.get("workflow_stage"),
            "updated_at": c.get("updated_at", c.get("created_at")),
        })

    return results


@router.get("/monthly-stats")
async def monthly_contract_stats(
    current_user: dict = Depends(get_current_user_with_role),
):
    """Contract creation by month. Filtered by user for non-admins."""
    privileged = _is_privileged(current_user)

    pipeline = []
    if not privileged:
        pipeline.append({"$match": {"created_by": current_user["user_id"]}})
    pipeline += [
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$created_at"},
                    "month": {"$month": "$created_at"},
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id.year": 1, "_id.month": 1}},
        {"$limit": 12},
    ]

    results = list(contracts_collection.aggregate(pipeline))
    return [
        {
            "year": r["_id"]["year"],
            "month": r["_id"]["month"],
            "count": r["count"],
        }
        for r in results
    ]