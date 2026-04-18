from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse
from typing import Optional

from app.services.calendar_service import (
    get_auth_url,
    handle_oauth_callback,
    sync_contract_to_calendar,
    list_calendar_events,
    delete_calendar_event,
    disconnect_calendar,
    get_connection_status,
)
from app.services.contract_service import get_contract
from app.middleware.auth import get_current_user
from app.config import FRONTEND_URL

router = APIRouter(prefix="/api/calendar", tags=["Google Calendar"])


# GET /api/calendar/status  — uses JWT to identify the calling user
@router.get("/status")
async def calendar_status(current_user: dict = Depends(get_current_user)):
    return get_connection_status(current_user["user_id"])


# GET /api/calendar/auth  — returns Google OAuth URL for the current user
@router.get("/auth")
async def calendar_auth(current_user: dict = Depends(get_current_user)):
    try:
        url = get_auth_url(current_user["user_id"])
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate auth URL: {str(e)}")


# GET /api/calendar/contract-dates  — contract start/end dates for the calendar grid
@router.get("/contract-dates")
async def contract_dates(current_user: dict = Depends(get_current_user)):
    """Return all contract start & end dates for the current user so the frontend
    can render a calendar grid without needing Google Calendar to be connected."""
    from app.config import contracts_collection
    from app.middleware.auth import get_current_user as _gcu
    is_admin = current_user.get("role") in ("admin", "manager")
    query = {} if is_admin else {"created_by": current_user["user_id"]}
    contracts = list(contracts_collection.find(
        query,
        {"_id": 1, "title": 1, "start_date": 1, "end_date": 1, "contract_type": 1, "status": 1}
    ).sort("end_date", 1))

    events = []
    for c in contracts:
        cid = str(c["_id"])
        title = c.get("title", "Contract")
        if c.get("start_date"):
            events.append({"id": f"{cid}_start", "contract_id": cid, "title": title,
                           "date": str(c["start_date"])[:10], "kind": "start",
                           "contract_type": c.get("contract_type", "other")})
        if c.get("end_date"):
            events.append({"id": f"{cid}_end", "contract_id": cid, "title": title,
                           "date": str(c["end_date"])[:10], "kind": "expiry",
                           "contract_type": c.get("contract_type", "other")})
    return {"events": events, "count": len(events)}


# GET /api/calendar/callback?code=xxx&state=user_id
# Google redirects here after the user grants permission — redirect back to the frontend
@router.get("/callback")
async def calendar_callback(
    code: str = Query(None),
    state: str = Query(None, description="User ID passed as OAuth state"),
    error: Optional[str] = Query(None),
):
    if error or not code or not state:
        return RedirectResponse(url=f"{FRONTEND_URL}/calendar?connected=false&error={error or 'missing_params'}")
    try:
        handle_oauth_callback(code=code, user_id=state)
        return RedirectResponse(url=f"{FRONTEND_URL}/calendar?connected=true")
    except Exception as e:
        return RedirectResponse(url=f"{FRONTEND_URL}/calendar?connected=false&error=callback_failed")


# POST /api/calendar/sync/{contract_id}
@router.post("/sync/{contract_id}")
async def sync_contract(
    contract_id: str,
    current_user: dict = Depends(get_current_user),
):
    is_admin = current_user.get("role") in ("admin", "manager")
    contract = await get_contract(contract_id, user_id=current_user["user_id"], is_admin=is_admin)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    status = get_connection_status(current_user["user_id"])
    if not status["connected"]:
        raise HTTPException(status_code=400, detail="Google Calendar not connected. Connect first via /api/calendar/auth")

    try:
        return sync_contract_to_calendar(contract, current_user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync: {str(e)}")


# POST /api/calendar/sync-all  — sync every contract the user can see
@router.post("/sync-all")
async def sync_all_contracts(current_user: dict = Depends(get_current_user)):
    status = get_connection_status(current_user["user_id"])
    if not status["connected"]:
        raise HTTPException(status_code=400, detail="Google Calendar not connected.")

    from app.config import contracts_collection
    from bson import ObjectId
    is_admin = current_user.get("role") in ("admin", "manager")
    query    = {} if is_admin else {"created_by": current_user["user_id"]}
    contracts = list(contracts_collection.find(query, {"_id": 1, "title": 1, "start_date": 1, "end_date": 1, "parties": 1, "contract_type": 1, "value": 1}))

    synced = 0
    failed = 0
    for c in contracts:
        try:
            c["id"] = str(c.pop("_id"))
            sync_contract_to_calendar(c, current_user["user_id"])
            synced += 1
        except Exception:
            failed += 1

    return {"synced": synced, "failed": failed, "total": len(contracts)}


# GET /api/calendar/events
@router.get("/events")
async def get_events(
    max_results: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    status = get_connection_status(current_user["user_id"])
    if not status["connected"]:
        raise HTTPException(status_code=400, detail="Google Calendar not connected.")
    try:
        events = list_calendar_events(current_user["user_id"], max_results)
        return {"events": events, "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch events: {str(e)}")


# DELETE /api/calendar/events/{event_id}
@router.delete("/events/{event_id}")
async def remove_event(event_id: str, current_user: dict = Depends(get_current_user)):
    status = get_connection_status(current_user["user_id"])
    if not status["connected"]:
        raise HTTPException(status_code=400, detail="Google Calendar not connected.")
    try:
        return delete_calendar_event(current_user["user_id"], event_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete event: {str(e)}")


# DELETE /api/calendar/disconnect
@router.delete("/disconnect")
async def disconnect(current_user: dict = Depends(get_current_user)):
    try:
        return disconnect_calendar(current_user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to disconnect: {str(e)}")
