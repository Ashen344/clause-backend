from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class NotificationType(str, Enum):
    approval_required = "approval_required"
    approval_decision = "approval_decision"
    contract_expiring = "contract_expiring"
    obligation_due = "obligation_due"
    workflow_update = "workflow_update"
    status_change = "status_change"
    escalation = "escalation"
    system = "system"


class NotificationCreate(BaseModel):
    user_id: str
    notification_type: NotificationType
    title: str
    message: str
    contract_id: Optional[str] = None
    workflow_id: Optional[str] = None
    link: Optional[str] = None


class NotificationInDB(BaseModel):
    user_id: str
    notification_type: NotificationType
    title: str
    message: str
    contract_id: Optional[str] = None
    workflow_id: Optional[str] = None
    link: Optional[str] = None
    is_read: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NotificationResponse(BaseModel):
    id: str
    notification_type: NotificationType
    title: str
    message: str
    contract_id: Optional[str] = None
    link: Optional[str] = None
    is_read: bool
    created_at: datetime
