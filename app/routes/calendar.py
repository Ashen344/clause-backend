from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import RedirectResponse
from typing import Optional
from app.middleware.auth import get_current_user
from app.models.calendar import EventCreate, EventUpdate, EventResponse
from app.services import calendar_service

router = APIRouter(prefix="/api/calendar", tags=["Calendar"])


@router.get("/connect")
async def connect_google_calendar(current_user: dict = Depends(get_current_user)):
    """Generate Google OAuth2 URL for the user to authorize calendar access."""
    try:
        auth_url = calendar_service.get_auth_url(current_user["user_id"])
        return {"auth_url": auth_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate auth URL: {str(e)}")


@router.get("/callback")
async def google_calendar_callback(code: str, state: str):
    """OAuth2 callback — exchanges the code for tokens and redirects to frontend."""
    try:
        calendar_service.exchange_code(code, user_id=state)
        # Redirect to frontend after successful connection
        return RedirectResponse(url="http://localhost:5173/calendar?connected=true")
    except Exception as e:
        return RedirectResponse(url=f"http://localhost:5173/calendar?error={str(e)}")


@router.get("/status")
async def calendar_status(current_user: dict = Depends(get_current_user)):
    """Check if the user has connected their Google Calendar."""
    connected = calendar_service.is_connected(current_user["user_id"])
    return {"connected": connected}


@router.post("/disconnect")
async def disconnect_google_calendar(current_user: dict = Depends(get_current_user)):
    """Remove stored Google Calendar tokens for the user."""
    removed = calendar_service.disconnect(current_user["user_id"])
    if not removed:
        raise HTTPException(status_code=404, detail="No Google Calendar connection found.")
    return {"message": "Google Calendar disconnected successfully."}


@router.get("/events")
async def list_events(
    time_min: Optional[str] = Query(None, description="Start time (ISO 8601)"),
    time_max: Optional[str] = Query(None, description="End time (ISO 8601)"),
    max_results: int = Query(50, ge=1, le=250),
    current_user: dict = Depends(get_current_user),
):
    """List upcoming Google Calendar events."""
    events = calendar_service.list_events(
        current_user["user_id"], time_min=time_min, time_max=time_max, max_results=max_results
    )
    if events is None:
        raise HTTPException(status_code=401, detail="Google Calendar not connected. Use /api/calendar/connect first.")
    return {"events": events, "count": len(events)}


@router.get("/events/{event_id}")
async def get_event(event_id: str, current_user: dict = Depends(get_current_user)):
    """Get a single calendar event by ID."""
    event = calendar_service.get_event(current_user["user_id"], event_id)
    if event is None:
        raise HTTPException(status_code=401, detail="Google Calendar not connected.")
    return event


@router.post("/events")
async def create_event(
    event: EventCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new Google Calendar event."""
    result = calendar_service.create_event(current_user["user_id"], event.model_dump())
    if result is None:
        raise HTTPException(status_code=401, detail="Google Calendar not connected.")
    return result


@router.put("/events/{event_id}")
async def update_event(
    event_id: str,
    event: EventUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update an existing Google Calendar event."""
    result = calendar_service.update_event(
        current_user["user_id"], event_id, event.model_dump(exclude_unset=True)
    )
    if result is None:
        raise HTTPException(status_code=401, detail="Google Calendar not connected.")
    return result


@router.delete("/events/{event_id}")
async def delete_event(event_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a Google Calendar event."""
    success = calendar_service.delete_event(current_user["user_id"], event_id)
    if not success:
        raise HTTPException(status_code=401, detail="Google Calendar not connected.")
    return {"message": "Event deleted successfully."}
