from pydantic import BaseModel, EmailStr, Field
from typing import Optional
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