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


def _user_filter(current_user: dict) -> dict:
    """Return a MongoDB filter that scopes queries to the current user unless they are admin/manager."""
    role = current_user.get("role", "user")
    if role in ("admin", "manager"):
        return {}
    return {"created_by": current_user["user_id"]}


@router.get("/stats")
async def get_dashboard_stats(current_user: dict = Depends(get_current_user_with_role)):
    """Get overview statistics for the dashboard, scoped to the current user's contracts."""
    now = datetime.utcnow()
    thirty_days_later = now + timedelta(days=30)
    uf = _user_filter(current_user)

    total = contracts_collection.count_documents(uf)
    active = contracts_collection.count_documents({**uf, "status": "active"})
    draft = contracts_collection.count_documents({**uf, "status": "draft"})
    expired = contracts_collection.count_documents({**uf, "status": "expired"})
    terminated = contracts_collection.count_documents({**uf, "status": "terminated"})

    expiring_soon = contracts_collection.count_documents({
        **uf,
        "status": "active",
        "end_date": {"$gte": now, "$lte": thirty_days_later},
    })

    high_risk = contracts_collection.count_documents({**uf, "risk_level": "high"})
    medium_risk = contracts_collection.count_documents({**uf, "risk_level": "medium"})
    low_risk = contracts_collection.count_documents({**uf, "risk_level": "low"})

    # Pending approvals scoped to user's contracts
    if uf:
        user_contract_ids = [
            str(c["_id"]) for c in contracts_collection.find(uf, {"_id": 1})
        ]
        pending_approvals = approvals_collection.count_documents({
            "status": "pending",
            "contract_id": {"$in": user_contract_ids},
        })
        active_workflows = workflows_collection.count_documents({
            "status": "active",
            "contract_id": {"$in": user_contract_ids},
        })
    else:
        pending_approvals = approvals_collection.count_documents({"status": "pending"})
        active_workflows = workflows_collection.count_documents({"status": "active"})

    total_users = users_collection.count_documents({})

    return {
        "total_contracts": total,
        "active_contracts": active,
        "draft_contracts": draft,
        "expired_contracts": expired,
        "terminated_contracts": terminated,
        "expiring_soon": expiring_soon,
        "pending_approvals": pending_approvals,
        "active_workflows": active_workflows,
        "total_users": total_users,
        "risk_summary": {
            "high": high_risk,
            "medium": medium_risk,
            "low": low_risk,
        },
    }


@router.get("/contracts-by-type")
async def contracts_by_type(current_user: dict = Depends(get_current_user_with_role)):
    """Get contract count grouped by type, scoped to the current user."""
    uf = _user_filter(current_user)
    pipeline = [
        *([ {"$match": uf} ] if uf else []),
        {"$group": {"_id": "$contract_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    results = list(contracts_collection.aggregate(pipeline))
    return [{"type": r["_id"], "count": r["count"]} for r in results]


@router.get("/contracts-by-status")
async def contracts_by_status(current_user: dict = Depends(get_current_user_with_role)):
    """Get contract count grouped by status, scoped to the current user."""
    uf = _user_filter(current_user)
    pipeline = [
        *([ {"$match": uf} ] if uf else []),
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    results = list(contracts_collection.aggregate(pipeline))
    return [{"status": r["_id"], "count": r["count"]} for r in results]


@router.get("/expiring-soon")
async def expiring_soon_contracts(current_user: dict = Depends(get_current_user_with_role)):
    """Get contracts expiring within the next 30 days, scoped to the current user."""
    now = datetime.utcnow()
    thirty_days_later = now + timedelta(days=30)
    uf = _user_filter(current_user)

    contracts = contracts_collection.find({
        **uf,
        "status": "active",
        "end_date": {"$gte": now, "$lte": thirty_days_later},
    }).sort("end_date", 1).limit(20)

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
async def recent_activity(current_user: dict = Depends(get_current_user_with_role)):
    """Get recently updated contracts, scoped to the current user."""
    uf = _user_filter(current_user)

    contracts = (
        contracts_collection
        .find(uf)
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
async def monthly_contract_stats(current_user: dict = Depends(get_current_user_with_role)):
    """Get contract creation stats by month, scoped to the current user."""
    uf = _user_filter(current_user)
    pipeline = [
        *([ {"$match": uf} ] if uf else []),
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
