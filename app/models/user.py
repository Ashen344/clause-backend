from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# Define the allowed roles as an Enum
# This ensures only valid roles can be assigned (FR-UAM06)
class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    user = "user"
    viewer = "viewer"


# Define possible account statuses
class AccountStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    suspended = "suspended"


# Schema for creating a new user (what the API receives)
class UserCreate(BaseModel):
    email: EmailStr                          # Validates proper email format automatically
    full_name: str = Field(min_length=2, max_length=100)  # Must be 2-100 characters
    role: UserRole = UserRole.user           # Defaults to "user" if not specified
    organization: Optional[str] = None       # Optional company name


# Schema for how a user is stored in MongoDB
class UserInDB(BaseModel):
    clerk_id: str                            # ID from Clerk authentication
    email: str
    full_name: str
    role: UserRole = UserRole.user
    organization: Optional[str] = None
    status: AccountStatus = AccountStatus.active
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None


# Schema for what the API sends back (never expose internal fields)
class UserResponse(BaseModel):
    id: str                                  # MongoDB's _id converted to string
    email: str
    full_name: str
    role: UserRole
    organization: Optional[str] = None
    status: AccountStatus
    created_at: datetime


# Schema for updating user profile (FR-UAM05)
class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    organization: Optional[str] = None
    role: Optional[UserRole] = None          # Only admins should be able to change this


# ─── Dashboard Customisation Preferences ─────────────────────────────────────

# Available accent colors the user can pick
class AccentColor(str, Enum):
    indigo  = "indigo"   # default
    violet  = "violet"
    cyan    = "cyan"
    emerald = "emerald"
    rose    = "rose"
    amber   = "amber"


# Available theme presets
class ThemePreset(str, Enum):
    dark_navy  = "dark_navy"   # default — current look
    oled       = "oled"        # pure black
    soft_dark  = "soft_dark"   # grey-toned dark
    light      = "light"       # white / light mode


# Available dashboard stat widgets
class DashboardWidget(str, Enum):
    total_contracts   = "total_contracts"
    active_contracts  = "active_contracts"
    expiring_soon     = "expiring_soon"
    high_risk         = "high_risk"
    draft_contracts   = "draft_contracts"
    pending_approvals = "pending_approvals"


# The full preferences object stored per user
class UserPreferences(BaseModel):
    # Which stat cards are visible on the dashboard (all shown by default)
    visible_widgets: List[DashboardWidget] = [
        DashboardWidget.total_contracts,
        DashboardWidget.active_contracts,
        DashboardWidget.expiring_soon,
        DashboardWidget.high_risk,
    ]

    # Default status filter on the contracts list page
    # None means "show all" (the default)
    default_contract_filter: Optional[str] = None   # e.g. "active", "draft", "expired"

    # Pinned contract IDs — shown as quick-access at top of dashboard (max 5)
    pinned_contracts: List[str] = []

    # UI theme
    accent_color: AccentColor = AccentColor.indigo
    theme: ThemePreset = ThemePreset.dark_navy