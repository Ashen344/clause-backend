from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from app.middleware.auth import get_current_user
from app.models.workflow import WorkflowCreate
from app.services.workflow_service import (
    create_workflow,
    get_workflow,
    get_all_workflows,
    get_workflows_by_contract,
    advance_workflow,
    reject_workflow,
)
from app.services.audit_service import create_audit_log
from app.services.notification_service import create_notification
from app.models.audit_log import AuditAction
from app.models.notification import NotificationCreate, NotificationType
from pydantic import BaseModel

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


class AdvanceRequest(BaseModel):
    comments: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/")
async def create_new_workflow(
    workflow_data: WorkflowCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new workflow for a contract."""
    result = await create_workflow(workflow_data, user_id=current_user["user_id"])
    if not result:
        raise HTTPException(status_code=404, detail="Contract not found")

    create_audit_log(
        action=AuditAction.workflow_start,
        resource_type="workflow",
        resource_id=result["id"],
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Started workflow: {workflow_data.name}",
    )

    return result


@router.get("/list")
async def list_all_workflows():
    """List all workflows."""
    return await get_all_workflows()


@router.get("/{workflow_id}")
async def get_workflow_details(workflow_id: str):
    """Get workflow details by ID."""
    workflow = await get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.get("/contract/{contract_id}")
async def get_contract_workflows(contract_id: str):
    """Get all workflows for a specific contract."""
    workflows = await get_workflows_by_contract(contract_id)
    return {"workflows": workflows}


@router.post("/{workflow_id}/advance")
async def advance_workflow_step(
    workflow_id: str,
    request: AdvanceRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """Complete the current step and advance to the next one."""
    comments = request.comments if request else None
    result = await advance_workflow(workflow_id, user_id=current_user["user_id"], comments=comments)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot advance workflow. It may be completed or cancelled.")

    create_audit_log(
        action=AuditAction.update,
        resource_type="workflow",
        resource_id=workflow_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Advanced workflow to step {result.get('current_step', '?')}",
    )

    # Notify about workflow update
    if result.get("contract_id"):
        create_notification(NotificationCreate(
            user_id=current_user["user_id"],
            notification_type=NotificationType.workflow_update,
            title="Workflow Advanced",
            message=f"Workflow '{result.get('name', '')}' advanced to step {result.get('current_step', '?')}.",
            contract_id=result.get("contract_id"),
            workflow_id=workflow_id,
        ))

    return result


@router.post("/{workflow_id}/reject")
async def reject_workflow_step(
    workflow_id: str,
    request: RejectRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """Reject the workflow at the current step."""
    reason = request.reason if request else None
    result = await reject_workflow(workflow_id, user_id=current_user["user_id"], reason=reason)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot reject workflow. It may already be completed or cancelled.")

    create_audit_log(
        action=AuditAction.status_change,
        resource_type="workflow",
        resource_id=workflow_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Rejected workflow. Reason: {reason or 'No reason provided'}",
    )

    if result.get("contract_id"):
        create_notification(NotificationCreate(
            user_id=current_user["user_id"],
            notification_type=NotificationType.workflow_update,
            title="Workflow Rejected",
            message=f"Workflow '{result.get('name', '')}' was rejected. {reason or ''}".strip(),
            contract_id=result.get("contract_id"),
            workflow_id=workflow_id,
        ))

    return result
