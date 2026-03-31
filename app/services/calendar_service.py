import os
import json
from datetime import datetime, timezone
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import calendar_tokens_collection, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

CLIENT_CONFIG = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uris": [GOOGLE_REDIRECT_URI],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def get_auth_url(user_id: str) -> str:
    """Generate the Google OAuth2 authorization URL for the given user."""
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=user_id,          # We pass user_id as state so the callback knows who to store tokens for
        prompt="consent",       # Force consent screen so we always get a refresh token
    )
    return auth_url


def handle_oauth_callback(code: str, user_id: str) -> dict:
    """Exchange the authorization code for tokens and store them in MongoDB."""
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)

    creds = flow.credentials
    token_data = {
        "user_id": user_id,
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
        "connected_at": datetime.now(timezone.utc),
    }

    # Upsert — replace any existing token for this user
    calendar_tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": token_data},
        upsert=True,
    )

    return {"message": "Google Calendar connected successfully", "user_id": user_id}


def _get_credentials(user_id: str) -> Optional[Credentials]:
    """Load stored credentials for a user, refreshing the token if expired."""
    record = calendar_tokens_collection.find_one({"user_id": user_id})
    if not record:
        return None

    creds = Credentials(
        token=record["token"],
        refresh_token=record.get("refresh_token"),
        token_uri=record.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=record.get("client_id", GOOGLE_CLIENT_ID),
        client_secret=record.get("client_secret", GOOGLE_CLIENT_SECRET),
        scopes=record.get("scopes", SCOPES),
    )

    # Refresh the access token if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Persist the refreshed token
        calendar_tokens_collection.update_one(
            {"user_id": user_id},
            {"$set": {"token": creds.token}},
        )

    return creds


def _build_service(user_id: str):
    """Build and return an authenticated Google Calendar API client."""
    creds = _get_credentials(user_id)
    if not creds:
        raise ValueError("Google Calendar not connected for this user")
    return build("calendar", "v3", credentials=creds)


def sync_contract_to_calendar(contract: dict, user_id: str) -> dict:
    """
    Create two Google Calendar events for a contract:
    - A start-date event marking when the contract begins
    - An end-date event (reminder) marking when the contract expires
    Returns the created event IDs.
    """
    service = _build_service(user_id)

    contract_id = contract.get("id", "")
    title = contract.get("title", "Contract")
    parties = contract.get("parties", [])
    party_names = ", ".join(p.get("name", "") for p in parties) if parties else "N/A"
    contract_type = contract.get("contract_type", "").replace("_", " ").title()
    value = contract.get("value")
    value_str = f"${value:,.2f}" if value else "N/A"

    description = (
        f"Contract: {title}\n"
        f"Type: {contract_type}\n"
        f"Parties: {party_names}\n"
        f"Value: {value_str}\n"
        f"Contract ID: {contract_id}"
    )

    def _to_date_str(dt) -> str:
        """Convert a datetime (or ISO string) to a YYYY-MM-DD date string."""
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")

    start_date_str = _to_date_str(contract["start_date"])
    end_date_str = _to_date_str(contract["end_date"])

    # Event 1 — Contract start
    start_event = {
        "summary": f"[CONTRACT START] {title}",
        "description": description,
        "start": {"date": start_date_str},
        "end": {"date": start_date_str},
        "colorId": "2",  # Sage green
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "email", "minutes": 24 * 60}],
        },
    }

    # Event 2 — Contract expiry (with a 7-day advance reminder)
    end_event = {
        "summary": f"[CONTRACT EXPIRY] {title}",
        "description": description,
        "start": {"date": end_date_str},
        "end": {"date": end_date_str},
        "colorId": "11",  # Tomato red
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 7 * 24 * 60},   # 7 days before
                {"method": "popup", "minutes": 24 * 60},        # 1 day before
            ],
        },
    }

    created_start = service.events().insert(calendarId="primary", body=start_event).execute()
    created_end = service.events().insert(calendarId="primary", body=end_event).execute()

    return {
        "message": "Contract synced to Google Calendar",
        "contract_id": contract_id,
        "start_event_id": created_start["id"],
        "end_event_id": created_end["id"],
        "start_event_link": created_start.get("htmlLink"),
        "end_event_link": created_end.get("htmlLink"),
    }


def list_calendar_events(user_id: str, max_results: int = 20) -> list:
    """Return upcoming Google Calendar events for the user (clause-created events only)."""
    service = _build_service(user_id)

    now = datetime.now(timezone.utc).isoformat()
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
            q="[CONTRACT",           # Only fetch events created by Clause
        )
        .execute()
    )

    events = events_result.get("items", [])
    return [
        {
            "id": e["id"],
            "summary": e.get("summary", ""),
            "description": e.get("description", ""),
            "start": e.get("start", {}).get("date") or e.get("start", {}).get("dateTime"),
            "end": e.get("end", {}).get("date") or e.get("end", {}).get("dateTime"),
            "html_link": e.get("htmlLink"),
        }
        for e in events
    ]


def delete_calendar_event(user_id: str, event_id: str) -> dict:
    """Delete a specific Google Calendar event."""
    service = _build_service(user_id)
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"message": "Event deleted successfully", "event_id": event_id}


def disconnect_calendar(user_id: str) -> dict:
    """Remove stored Google Calendar credentials for the user."""
    result = calendar_tokens_collection.delete_one({"user_id": user_id})
    if result.deleted_count == 0:
        raise ValueError("No Google Calendar connection found for this user")
    return {"message": "Google Calendar disconnected successfully"}


def get_connection_status(user_id: str) -> dict:
    """Check whether a user has connected their Google Calendar."""
    record = calendar_tokens_collection.find_one({"user_id": user_id}, {"_id": 0, "connected_at": 1})
    if record:
        return {"connected": True, "connected_at": record.get("connected_at")}
    return {"connected": False}
