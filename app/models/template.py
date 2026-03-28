from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
from app.models.contract import ContractType


class TemplateField(BaseModel):
    field_name: str
    field_type: str = "text"  # text, date, number, select
    required: bool = False
    default_value: Optional[str] = None
    options: Optional[List[str]] = None  # for select type


class TemplateCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: Optional[str] = None
    contract_type: ContractType
    content: str  # HTML or markdown template content
    fields: List[TemplateField] = []
    tags: Optional[List[str]] = None


class TemplateInDB(BaseModel):
    name: str
    description: Optional[str] = None
    contract_type: ContractType
    content: str
    fields: List[TemplateField] = []
    tags: Optional[List[str]] = None
    version: int = 1
    is_active: bool = True
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    contract_type: ContractType
    content: str
    fields: List[TemplateField] = []
    tags: Optional[List[str]] = None
    version: int
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    contract_type: Optional[ContractType] = None
    content: Optional[str] = None
    fields: Optional[List[TemplateField]] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None
