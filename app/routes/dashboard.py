from fastapi import APIRouter, Depends
from datetime import datetime, timedelta
from app.config import (
    contracts_collection,
    workflows_collection,
    approvals_collection,
    users_collection,
)
from app.middleware.auth import get_optional_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats():
    """Get overview statistics for the dashboard."""
    now = datetime.utcnow()
    thirty_days_later = now + timedelta(days=30)

    # Contract counts by status
    total = contracts_collection.count_documents({})
    active = contracts_collection.count_documents({"status": "active"})
    draft = contracts_collection.count_documents({"status": "draft"})
    expired = contracts_collection.count_documents({"status": "expired"})
    terminated = contracts_collection.count_documents({"status": "terminated"})

    # Contracts expiring soon (next 30 days)
    expiring_soon = contracts_collection.count_documents({
        "status": "active",
        "end_date": {"$gte": now, "$lte": thirty_days_later},
    })

    # Risk summary
    high_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "high"})
    medium_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "medium"})
    low_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "low"})

    # Pending approvals
    pending_approvals = approvals_collection.count_documents({"status": "pending"})

    # Active workflows
    active_workflows = workflows_collection.count_documents({"status": "active"})

    # Total users
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
async def contracts_by_type():
    """Get contract count grouped by type (for pie chart)."""
    pipeline = [
        {"$group": {"_id": "$contract_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    results = list(contracts_collection.aggregate(pipeline))
    return [{"type": r["_id"], "count": r["count"]} for r in results]


@router.get("/contracts-by-status")
async def contracts_by_status():
    """Get contract count grouped by status (for bar chart)."""
    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    results = list(contracts_collection.aggregate(pipeline))
    return [{"status": r["_id"], "count": r["count"]} for r in results]


@router.get("/expiring-soon")
async def expiring_soon_contracts():
    """Get contracts expiring within the next 30 days."""
    now = datetime.utcnow()
    thirty_days_later = now + timedelta(days=30)

    contracts = contracts_collection.find({
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
async def recent_activity():
    """Get recently updated contracts."""
    contracts = (
        contracts_collection
        .find()
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
async def monthly_contract_stats():
    """Get contract creation stats by month (for charts)."""
    pipeline = [
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
