from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime
from app.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    calendar_tokens_collection,
)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

CLIENT_CONFIG = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [GOOGLE_REDIRECT_URI],
    }
}


def _build_flow(state: str = None) -> Flow:
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def get_auth_url(user_id: str) -> str:
    """Generate Google OAuth2 authorization URL."""
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=user_id,
    )
    return auth_url


def exchange_code(code: str, user_id: str) -> dict:
    """Exchange authorization code for tokens and store them."""
    flow = _build_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials

    token_data = {
        "user_id": user_id,
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
        "updated_at": datetime.utcnow().isoformat(),
    }

    calendar_tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": token_data},
        upsert=True,
    )
    return token_data


def _get_credentials(user_id: str) -> Credentials:
    """Load stored credentials for a user."""
    token_doc = calendar_tokens_collection.find_one({"user_id": user_id})
    if not token_doc:
        return None

    creds = Credentials(
        token=token_doc["token"],
        refresh_token=token_doc.get("refresh_token"),
        token_uri=token_doc.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_doc.get("client_id", GOOGLE_CLIENT_ID),
        client_secret=token_doc.get("client_secret", GOOGLE_CLIENT_SECRET),
        scopes=token_doc.get("scopes", SCOPES),
    )

    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        calendar_tokens_collection.update_one(
            {"user_id": user_id},
            {"$set": {"token": creds.token, "updated_at": datetime.utcnow().isoformat()}},
        )

    return creds


def _get_service(user_id: str):
    """Build an authorized Calendar API service."""
    creds = _get_credentials(user_id)
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)


def is_connected(user_id: str) -> bool:
    """Check if user has stored Google Calendar tokens."""
    return calendar_tokens_collection.find_one({"user_id": user_id}) is not None


def disconnect(user_id: str) -> bool:
    """Remove stored tokens for a user."""
    result = calendar_tokens_collection.delete_one({"user_id": user_id})
    return result.deleted_count > 0


def list_events(user_id: str, time_min: str = None, time_max: str = None, max_results: int = 50) -> list:
    """List upcoming calendar events."""
    service = _get_service(user_id)
    if not service:
        return None

    params = {
        "calendarId": "primary",
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_min:
        params["timeMin"] = time_min
    else:
        params["timeMin"] = datetime.utcnow().isoformat() + "Z"
    if time_max:
        params["timeMax"] = time_max

    result = service.events().list(**params).execute()
    return result.get("items", [])


def get_event(user_id: str, event_id: str) -> dict:
    """Get a single calendar event by ID."""
    service = _get_service(user_id)
    if not service:
        return None
    return service.events().get(calendarId="primary", eventId=event_id).execute()


def create_event(user_id: str, event_data: dict) -> dict:
    """Create a new calendar event."""
    service = _get_service(user_id)
    if not service:
        return None

    body = {
        "summary": event_data["summary"],
        "start": {},
        "end": {},
    }

    if event_data.get("description"):
        body["description"] = event_data["description"]
    if event_data.get("location"):
        body["location"] = event_data["location"]

    # Build start/end
    for field in ("start", "end"):
        dt_info = event_data[field]
        if dt_info.get("date_time"):
            body[field]["dateTime"] = dt_info["date_time"]
            body[field]["timeZone"] = dt_info.get("time_zone", "UTC")
        elif dt_info.get("date"):
            body[field]["date"] = dt_info["date"]

    if event_data.get("attendees"):
        body["attendees"] = [{"email": e} for e in event_data["attendees"]]

    return service.events().insert(calendarId="primary", body=body).execute()


def update_event(user_id: str, event_id: str, event_data: dict) -> dict:
    """Update an existing calendar event."""
    service = _get_service(user_id)
    if not service:
        return None

    existing = service.events().get(calendarId="primary", eventId=event_id).execute()

    if event_data.get("summary") is not None:
        existing["summary"] = event_data["summary"]
    if event_data.get("description") is not None:
        existing["description"] = event_data["description"]
    if event_data.get("location") is not None:
        existing["location"] = event_data["location"]

    for field in ("start", "end"):
        if event_data.get(field):
            dt_info = event_data[field]
            if dt_info.get("date_time"):
                existing[field] = {"dateTime": dt_info["date_time"], "timeZone": dt_info.get("time_zone", "UTC")}
            elif dt_info.get("date"):
                existing[field] = {"date": dt_info["date"]}

    if event_data.get("attendees") is not None:
        existing["attendees"] = [{"email": e} for e in event_data["attendees"]]

    return service.events().update(calendarId="primary", eventId=event_id, body=existing).execute()


def delete_event(user_id: str, event_id: str) -> bool:
    """Delete a calendar event."""
    service = _get_service(user_id)
    if not service:
        return False
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return True
