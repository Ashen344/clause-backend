from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"


class ApprovalType(str, Enum):
    majority = "majority"
    first_person = "first_person"
    all_required = "all_required"


class ApprovalDecision(str, Enum):
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"


class ApproverVote(BaseModel):
    user_id: str
    user_email: Optional[str] = None
    decision: Optional[ApprovalDecision] = None
    comments: Optional[str] = None
    decided_at: Optional[datetime] = None


class ApprovalCreate(BaseModel):
    contract_id: str
    workflow_id: Optional[str] = None
    approval_type: ApprovalType = ApprovalType.all_required
    approver_ids: List[str]
    due_date: Optional[datetime] = None


class ApprovalInDB(BaseModel):
    contract_id: str
    workflow_id: Optional[str] = None
    approval_type: ApprovalType
    status: ApprovalStatus = ApprovalStatus.pending
    approvers: List[ApproverVote] = []
    due_date: Optional[datetime] = None
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None


class ApprovalResponse(BaseModel):
    id: str
    contract_id: str
    workflow_id: Optional[str] = None
    approval_type: ApprovalType
    status: ApprovalStatus
    approvers: List[ApproverVote]
    due_date: Optional[datetime] = None
    created_by: str
    created_at: datetime
    decided_at: Optional[datetime] = None


class VoteRequest(BaseModel):
    decision: ApprovalDecision
    comments: Optional[str] = None
