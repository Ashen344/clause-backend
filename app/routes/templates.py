from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from app.middleware.auth import get_current_user_with_role
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


def _require_admin_or_manager(current_user: dict):
    if current_user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required")


@router.post("/")
async def create_new_template(
    template_data: TemplateCreate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Create a new contract template (admin / manager only)."""
    _require_admin_or_manager(current_user)
    result = await create_template(template_data, user_id=current_user["user_id"])
    return result


@router.get("/")
async def list_templates(
    contract_type: Optional[ContractType] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _current_user: dict = Depends(get_current_user_with_role),
):
    """List all active templates with optional filters."""
    return await get_templates(
        contract_type=contract_type.value if contract_type else None,
        search=search,
        page=page,
        per_page=per_page,
    )


@router.get("/{template_id}")
async def get_template_details(
    template_id: str,
    _current_user: dict = Depends(get_current_user_with_role),
):
    """Get a template by ID."""
    template = await get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/{template_id}")
async def update_existing_template(
    template_id: str,
    update_data: TemplateUpdate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Update a template (admin / manager only)."""
    _require_admin_or_manager(current_user)
    template = await update_template(template_id, update_data)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/{template_id}")
async def delete_existing_template(
    template_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Deactivate a template (admin / manager only)."""
    _require_admin_or_manager(current_user)
    success = await delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"message": "Template deactivated successfully"}
