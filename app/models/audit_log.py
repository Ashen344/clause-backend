from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class AuditAction(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"
    status_change = "status_change"
    approval_vote = "approval_vote"
    workflow_start = "workflow_start"
    workflow_complete = "workflow_complete"
    file_upload = "file_upload"
    file_download = "file_download"
    ai_analysis = "ai_analysis"
    login = "login"
    export = "export"


class AuditLogCreate(BaseModel):
    action: AuditAction
    resource_type: str  # "contract", "workflow", "approval", etc.
    resource_id: str
    user_id: str
    user_email: Optional[str] = None
    details: Optional[str] = None
    changes: Optional[dict] = None  # {"field": {"old": x, "new": y}}
    ip_address: Optional[str] = None


class AuditLogInDB(BaseModel):
    action: AuditAction
    resource_type: str
    resource_id: str
    user_id: str
    user_email: Optional[str] = None
    details: Optional[str] = None
    changes: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLogResponse(BaseModel):
    id: str
    action: AuditAction
    resource_type: str
    resource_id: str
    user_id: str
    user_email: Optional[str] = None
    details: Optional[str] = None
    changes: Optional[dict] = None
    created_at: datetime
