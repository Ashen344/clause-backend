from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from app.middleware.auth import get_current_user
from app.models.template import TemplateCreate, TemplateUpdate
from app.models.contract import ContractType
from app.services.template_service import (
    create_template,
    get_template,
    get_templates,
    update_template,
    delete_template,
)
from app.services.audit_service import create_audit_log
from app.models.audit_log import AuditAction

router = APIRouter(prefix="/api/templates", tags=["Templates"])


@router.post("/")
async def create_new_template(
    template_data: TemplateCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new contract template."""
    result = await create_template(template_data, user_id=current_user["user_id"])

    create_audit_log(
        action=AuditAction.create,
        resource_type="template",
        resource_id=result["id"],
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Created template: {template_data.name}",
    )

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
async def update_existing_template(
    template_id: str,
    update_data: TemplateUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update a template."""
    template = await update_template(template_id, update_data)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    create_audit_log(
        action=AuditAction.update,
        resource_type="template",
        resource_id=template_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Updated template: {template.get('name', template_id)}",
    )

    return template


@router.delete("/{template_id}")
async def delete_existing_template(
    template_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Deactivate a template (soft delete)."""
    success = await delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")

    create_audit_log(
        action=AuditAction.delete,
        resource_type="template",
        resource_id=template_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details="Deactivated template",
    )

    return {"message": "Template deactivated successfully"}
