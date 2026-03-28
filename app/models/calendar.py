from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class EventDateTime(BaseModel):
    date_time: Optional[str] = None  # ISO format for timed events
    date: Optional[str] = None  # YYYY-MM-DD for all-day events
    time_zone: Optional[str] = "UTC"


class EventCreate(BaseModel):
    summary: str
    description: Optional[str] = None
    location: Optional[str] = None
    start: EventDateTime
    end: EventDateTime
    attendees: Optional[list[str]] = None  # list of emails
    contract_id: Optional[str] = None  # link event to a contract


class EventUpdate(BaseModel):
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start: Optional[EventDateTime] = None
    end: Optional[EventDateTime] = None
    attendees: Optional[list[str]] = None


class EventResponse(BaseModel):
    id: str
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start: Optional[dict] = None
    end: Optional[dict] = None
    html_link: Optional[str] = None
    status: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    attendees: Optional[list[dict]] = None
    contract_id: Optional[str] = None
