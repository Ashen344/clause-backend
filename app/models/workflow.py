from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class WorkflowStatus(str, Enum):
    active = "active"
    completed = "completed"
    cancelled = "cancelled"
    paused = "paused"


class StepType(str, Enum):
    review = "review"
    approval = "approval"
    signing = "signing"
    notification = "notification"
    ai_analysis = "ai_analysis"


class StepStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    rejected = "rejected"
    skipped = "skipped"


class WorkflowStep(BaseModel):
    step_number: int
    name: str
    step_type: StepType
    status: StepStatus = StepStatus.pending
    assigned_to: Optional[str] = None
    completed_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    comments: Optional[str] = None
    due_date: Optional[datetime] = None


class WorkflowCreate(BaseModel):
    contract_id: str
    name: str = "Standard Contract Workflow"
    steps: List[WorkflowStep] = []


class WorkflowInDB(BaseModel):
    contract_id: str
    name: str
    status: WorkflowStatus = WorkflowStatus.active
    steps: List[WorkflowStep] = []
    current_step: int = 1
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class WorkflowResponse(BaseModel):
    id: str
    contract_id: str
    name: str
    status: WorkflowStatus
    steps: List[WorkflowStep]
    current_step: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


# Default workflow steps for standard contract processing
DEFAULT_WORKFLOW_STEPS = [
    WorkflowStep(step_number=1, name="Request & Initiation", step_type=StepType.review),
    WorkflowStep(step_number=2, name="Authoring & Drafting", step_type=StepType.review),
    WorkflowStep(step_number=3, name="AI Risk Analysis", step_type=StepType.ai_analysis),
    WorkflowStep(step_number=4, name="Review & Negotiation", step_type=StepType.review),
    WorkflowStep(step_number=5, name="Approval", step_type=StepType.approval),
    WorkflowStep(step_number=6, name="Execution & Signing", step_type=StepType.signing),
    WorkflowStep(step_number=7, name="Storage & Repository", step_type=StepType.notification),
    WorkflowStep(step_number=8, name="Monitoring & Obligations", step_type=StepType.review),
    WorkflowStep(step_number=9, name="Renewal / Expiration", step_type=StepType.review),
]
