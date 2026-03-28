from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# Contract types your system supports
class ContractType(str, Enum):
    service_agreement = "service_agreement"
    nda = "nda"
    employment = "employment"
    vendor = "vendor"
    licensing = "licensing"
    partnership = "partnership"
    other = "other"


# Contract status tracks the overall state
class ContractStatus(str, Enum):
    draft = "draft"
    active = "active"
    expired = "expired"
    terminated = "terminated"
    renewed = "renewed"


# Workflow stages from your workflow document
# Maps directly to the 9 stages defined in workflow_document.docx
class WorkflowStage(str, Enum):
    request = "request"                  # 1. Request / Initiation
    authoring = "authoring"              # 2. Authoring / Drafting
    review = "review"                    # 3. Review & Negotiation
    approval = "approval"                # 4. Approval
    execution = "execution"              # 5. Execution (Signing)
    storage = "storage"                  # 6. Storage / Repository
    monitoring = "monitoring"            # 7. Monitoring / Obligation Management
    renewal = "renewal"                  # 8. Renewal / Amendment
    expired = "expired"                  # 9. Expiration / Termination


# Risk levels for AI-generated risk scores (FR-RSA-01)
class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# Approval types from your workflow document
class ApprovalType(str, Enum):
    majority = "majority"                # Majority approval
    first_person = "first_person"        # First person approval
    all_required = "all_required"        # All approval


# Workflow trigger types from your workflow document
class WorkflowTrigger(str, Enum):
    creation = "creation"
    modification = "modification"
    renewal = "renewal"


# Stores information about each party involved in a contract
class ContractParty(BaseModel):
    name: str
    role: str                            # e.g., "client", "vendor", "partner"
    email: Optional[str] = None
    organization: Optional[str] = None


# Tracks each version of a contract (FR-CVC-01, FR-CVC-02)
class ContractVersion(BaseModel):
    version_number: int
    file_url: str                        # Path to the stored PDF
    uploaded_by: str                     # User ID who uploaded this version
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    change_notes: Optional[str] = None   # What changed in this version


# AI analysis results stored with each contract
class AIAnalysisResult(BaseModel):
    summary: Optional[str] = None                    # AI-generated summary (FR-ACA-06)
    extracted_clauses: Optional[List[str]] = None     # Key clauses found (FR-ACA-07)
    key_information: Optional[dict] = None            # Parties, duration, payment terms
    risk_score: Optional[float] = None                # 0-100 score (FR-RSA-03)
    risk_level: Optional[RiskLevel] = None            # Low/Medium/High (FR-CAS-04)
    analyzed_at: Optional[datetime] = None


# Schema for creating a new contract (what the API receives)
class ContractCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    contract_type: ContractType
    description: Optional[str] = None
    parties: List[ContractParty] = []                 # Who's involved
    start_date: datetime
    end_date: datetime
    value: Optional[float] = None                     # Contract monetary value
    payment_terms: Optional[str] = None
    approval_type: ApprovalType = ApprovalType.all_required
    workflow_trigger: WorkflowTrigger = WorkflowTrigger.creation
    tags: Optional[List[str]] = None                  # For categorization (FR-CM-08)
    template_id: Optional[str] = None                 # If created from a template


# Schema for how a contract is stored in MongoDB
class ContractInDB(BaseModel):
    title: str
    contract_type: ContractType
    description: Optional[str] = None
    parties: List[ContractParty] = []
    start_date: datetime
    end_date: datetime
    value: Optional[float] = None
    payment_terms: Optional[str] = None

    # Status and workflow
    status: ContractStatus = ContractStatus.draft
    workflow_stage: WorkflowStage = WorkflowStage.request
    approval_type: ApprovalType = ApprovalType.all_required
    workflow_trigger: WorkflowTrigger = WorkflowTrigger.creation

    # File and versioning
    file_url: Optional[str] = None                    # Current PDF file path
    versions: List[ContractVersion] = []              # Version history
    current_version: int = 1

    # AI Analysis
    ai_analysis: Optional[AIAnalysisResult] = None

    # Metadata
    created_by: str                                   # User ID of creator
    organization_id: Optional[str] = None
    tags: Optional[List[str]] = None
    template_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Schema for API responses
class ContractResponse(BaseModel):
    id: str
    title: str
    contract_type: ContractType
    description: Optional[str] = None
    parties: List[ContractParty] = []
    start_date: datetime
    end_date: datetime
    value: Optional[float] = None
    status: ContractStatus
    workflow_stage: WorkflowStage
    risk_score: Optional[float] = None
    risk_level: Optional[RiskLevel] = None
    current_version: int
    created_by: str
    tags: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime


# Schema for updating a contract
class ContractUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    contract_type: Optional[ContractType] = None
    parties: Optional[List[ContractParty]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    value: Optional[float] = None
    payment_terms: Optional[str] = None
    status: Optional[ContractStatus] = None
    workflow_stage: Optional[WorkflowStage] = None
    tags: Optional[List[str]] = None


# Schema for contract search/filtering (FR-CM-02, FR-CM-03)
class ContractFilter(BaseModel):
    search: Optional[str] = None                      # Search by name/keyword
    contract_type: Optional[ContractType] = None      # Filter by type
    status: Optional[ContractStatus] = None           # Filter by status
    workflow_stage: Optional[WorkflowStage] = None    # Filter by workflow stage
    risk_level: Optional[RiskLevel] = None            # Filter by risk
    start_date_from: Optional[datetime] = None        # Date range filters
    start_date_to: Optional[datetime] = None
    page: int = 1                                     # Pagination
    per_page: int = 20