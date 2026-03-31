from fastapi import APIRouter, HTTPException, Query
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

router = APIRouter(prefix="/api/calendar", tags=["Google Calendar"])


# GET /api/calendar/status?user_id=xxx
# Check whether the user has connected Google Calendar
@router.get("/status")
async def calendar_status(user_id: str = Query(..., description="User ID")):
    return get_connection_status(user_id)


# GET /api/calendar/auth?user_id=xxx
# Returns the Google OAuth URL the frontend should redirect the user to
@router.get("/auth")
async def calendar_auth(user_id: str = Query(..., description="User ID")):
    try:
        url = get_auth_url(user_id)
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate auth URL: {str(e)}")


# GET /api/calendar/callback?code=xxx&state=user_id
# Google redirects here after the user grants permission
@router.get("/callback")
async def calendar_callback(
    code: str = Query(...),
    state: str = Query(..., description="User ID passed as OAuth state"),
    error: Optional[str] = Query(None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    try:
        result = handle_oauth_callback(code=code, user_id=state)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth callback failed: {str(e)}")


# POST /api/calendar/sync/{contract_id}?user_id=xxx
# Create Google Calendar events for a contract's start and end dates
@router.post("/sync/{contract_id}")
async def sync_contract(
    contract_id: str,
    user_id: str = Query(..., description="User ID"),
):
    contract = await get_contract(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    status = get_connection_status(user_id)
    if not status["connected"]:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not connected. Visit /api/calendar/auth first.",
        )

    try:
        result = sync_contract_to_calendar(contract, user_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync contract: {str(e)}")


# GET /api/calendar/events?user_id=xxx&max_results=20
# List upcoming contract calendar events
@router.get("/events")
async def get_events(
    user_id: str = Query(..., description="User ID"),
    max_results: int = Query(20, ge=1, le=100),
):
    status = get_connection_status(user_id)
    if not status["connected"]:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not connected. Visit /api/calendar/auth first.",
        )

    try:
        events = list_calendar_events(user_id, max_results)
        return {"events": events, "count": len(events)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch events: {str(e)}")


# DELETE /api/calendar/events/{event_id}?user_id=xxx
# Delete a specific calendar event
@router.delete("/events/{event_id}")
async def remove_event(
    event_id: str,
    user_id: str = Query(..., description="User ID"),
):
    status = get_connection_status(user_id)
    if not status["connected"]:
        raise HTTPException(status_code=400, detail="Google Calendar not connected.")

    try:
        return delete_calendar_event(user_id, event_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete event: {str(e)}")


# DELETE /api/calendar/disconnect?user_id=xxx
# Remove stored credentials and disconnect Google Calendar
@router.delete("/disconnect")
async def disconnect(user_id: str = Query(..., description="User ID")):
    try:
        return disconnect_calendar(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to disconnect: {str(e)}")
