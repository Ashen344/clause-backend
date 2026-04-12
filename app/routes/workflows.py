from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from app.middleware.auth import get_current_user, get_optional_user
from app.models.workflow import WorkflowCreate
from app.services.workflow_service import (
    create_workflow,
    get_workflow,
    get_workflows_by_contract,
    advance_workflow,
    reject_workflow,
)
from pydantic import BaseModel

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


class AdvanceRequest(BaseModel):
    comments: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/")
async def create_new_workflow(workflow_data: WorkflowCreate):
    """Create a new workflow for a contract."""
    result = await create_workflow(workflow_data, user_id="temp_user")
    if not result:
        raise HTTPException(status_code=404, detail="Contract not found")
    return result


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
    return workflows


@router.post("/{workflow_id}/advance")
async def advance_workflow_step(workflow_id: str, request: AdvanceRequest = None):
    """Complete the current step and advance to the next one."""
    comments = request.comments if request else None
    result = await advance_workflow(workflow_id, user_id="temp_user", comments=comments)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot advance workflow. It may be completed or cancelled.")
    return result


@router.post("/{workflow_id}/reject")
async def reject_workflow_step(workflow_id: str, request: RejectRequest = None):
    """Reject the workflow at the current step."""
    reason = request.reason if request else None
    result = await reject_workflow(workflow_id, user_id="temp_user", reason=reason)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot reject workflow. It may already be completed or cancelled.")
    return result
