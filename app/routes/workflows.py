from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from app.middleware.auth import get_current_user_with_role
from app.models.workflow import WorkflowCreate
from app.services.workflow_service import (
    create_workflow,
    get_workflow,
    get_workflows_by_contract,
    get_all_workflows,
    advance_workflow,
    reject_workflow,
)
from pydantic import BaseModel

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


class AdvanceRequest(BaseModel):
    comments: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None


def _require_admin_or_manager(current_user: dict):
    if current_user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required")


@router.get("/list")
async def list_all_workflows(
    current_user: dict = Depends(get_current_user_with_role),
):
    """List workflows. Admins/managers see all; regular users see only their own."""
    is_admin = current_user.get("role") in ("admin", "manager")
    return await get_all_workflows(user_id=current_user["user_id"], is_admin=is_admin)


@router.post("/")
async def create_new_workflow(
    workflow_data: WorkflowCreate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Create a new workflow for a contract."""
    result = await create_workflow(workflow_data, user_id=current_user["user_id"])
    if not result:
        raise HTTPException(status_code=404, detail="Contract not found")
    return result


@router.get("/{workflow_id}")
async def get_workflow_details(
    workflow_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Get workflow details. Users can only view workflows for their own contracts."""
    workflow = await get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    is_admin = current_user.get("role") in ("admin", "manager")
    if not is_admin:
        # Verify the linked contract belongs to this user
        from app.config import contracts_collection
        from bson import ObjectId
        contract_id = workflow.get("contract_id")
        if contract_id and ObjectId.is_valid(contract_id):
            contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
            if not contract or contract.get("created_by") != current_user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")

    return workflow


@router.get("/contract/{contract_id}")
async def get_contract_workflows(
    contract_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Get all workflows for a specific contract."""
    is_admin = current_user.get("role") in ("admin", "manager")
    if not is_admin:
        from app.config import contracts_collection
        from bson import ObjectId
        if ObjectId.is_valid(contract_id):
            contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
            if not contract or contract.get("created_by") != current_user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")

    workflows = await get_workflows_by_contract(contract_id)
    return {"workflows": workflows}


@router.post("/{workflow_id}/advance")
async def advance_workflow_step(
    workflow_id: str,
    request: AdvanceRequest = None,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Advance the workflow to the next step. Admin/manager only."""
    _require_admin_or_manager(current_user)
    comments = request.comments if request else None
    result = await advance_workflow(workflow_id, user_id=current_user["user_id"], comments=comments)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot advance workflow. It may be completed or cancelled.")
    return result


@router.post("/{workflow_id}/reject")
async def reject_workflow_step(
    workflow_id: str,
    request: RejectRequest = None,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Reject the workflow at the current step. Admin/manager only."""
    _require_admin_or_manager(current_user)
    reason = request.reason if request else None
    result = await reject_workflow(workflow_id, user_id=current_user["user_id"], reason=reason)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot reject workflow. It may already be completed or cancelled.")
    return result
