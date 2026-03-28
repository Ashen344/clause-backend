from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from app.middleware.auth import get_current_user, get_optional_user
from app.models.template import TemplateCreate, TemplateUpdate
from app.models.contract import ContractType
from app.services.template_service import (
    create_template,
    get_template,
    get_templates,
    update_template,
    delete_template,
)

router = APIRouter(prefix="/api/templates", tags=["Templates"])


@router.post("/")
async def create_new_template(template_data: TemplateCreate):
    """Create a new contract template."""
    result = await create_template(template_data, user_id="temp_user")
    return result


@router.get("/")
async def list_templates(
    contract_type: Optional[ContractType] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List all active templates with optional filters."""
    return await get_templates(
        contract_type=contract_type.value if contract_type else None,
        search=search,
        page=page,
        per_page=per_page,
    )


@router.get("/{template_id}")
async def get_template_details(template_id: str):
    """Get a template by ID."""
    template = await get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/{template_id}")
async def update_existing_template(template_id: str, update_data: TemplateUpdate):
    """Update a template."""
    template = await update_template(template_id, update_data)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/{template_id}")
async def delete_existing_template(template_id: str):
    """Deactivate a template (soft delete)."""
    success = await delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"message": "Template deactivated successfully"}
