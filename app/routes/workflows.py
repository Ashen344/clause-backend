from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from bson import ObjectId
from app.middleware.auth import get_current_user_with_role
from app.models.workflow import WorkflowCreate, WorkflowTemplateCreate, WorkflowTemplateUpdate
from app.services.workflow_service import (
    create_workflow,
    get_workflow,
    get_workflows_by_contract,
    get_all_workflows,
    advance_workflow,
    reject_workflow,
    pause_workflow,
    resume_workflow,
)
from app.config import workflow_templates_collection
from app.services.audit_service import create_audit_log
from app.models.audit_log import AuditAction
from pydantic import BaseModel

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tpl_to_response(doc: dict) -> dict:
    """Convert a MongoDB workflow template document to a JSON-safe dict."""
    doc["id"] = str(doc.pop("_id"))
    return doc


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
    create_audit_log(
        action=AuditAction.workflow_start,
        resource_type="workflow",
        resource_id=result.get("id", ""),
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Workflow started: {workflow_data.name}",
    )
    return result


# ── Workflow Templates CRUD ───────────────────────────────────────────────────
# These routes MUST be above /{workflow_id} to avoid "templates" being captured
# as a workflow ID by FastAPI's path-param matching.

@router.get("/templates")
async def list_workflow_templates(
    current_user: dict = Depends(get_current_user_with_role),
):
    """List all reusable workflow templates (accessible to all authenticated users)."""
    docs = list(workflow_templates_collection.find({}))
    return [_tpl_to_response(d) for d in docs]


@router.post("/templates")
async def create_workflow_template(
    body: WorkflowTemplateCreate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Create a custom workflow template (admin / manager only)."""
    _require_admin_or_manager(current_user)
    now = datetime.utcnow()
    doc = {
        **body.model_dump(),
        "created_by": current_user["user_id"],
        "created_at": now,
        "updated_at": now,
    }
    # Serialise Enum values
    doc["steps"] = [
        {**s, "step_type": s["step_type"].value if hasattr(s["step_type"], "value") else s["step_type"]}
        for s in doc["steps"]
    ]
    result = workflow_templates_collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _tpl_to_response(doc)


@router.get("/templates/{template_id}")
async def get_workflow_template(
    template_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Get a single workflow template by ID."""
    if not ObjectId.is_valid(template_id):
        raise HTTPException(status_code=400, detail="Invalid template ID")
    doc = workflow_templates_collection.find_one({"_id": ObjectId(template_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    return _tpl_to_response(doc)


@router.put("/templates/{template_id}")
async def update_workflow_template(
    template_id: str,
    body: WorkflowTemplateUpdate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Update a workflow template (admin / manager only)."""
    _require_admin_or_manager(current_user)
    if not ObjectId.is_valid(template_id):
        raise HTTPException(status_code=400, detail="Invalid template ID")
    update: dict = {"updated_at": datetime.utcnow()}
    data = body.model_dump(exclude_none=True)
    if "steps" in data:
        data["steps"] = [
            {**s, "step_type": s["step_type"].value if hasattr(s["step_type"], "value") else s["step_type"]}
            for s in data["steps"]
        ]
    update.update(data)
    result = workflow_templates_collection.update_one(
        {"_id": ObjectId(template_id)}, {"$set": update}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    doc = workflow_templates_collection.find_one({"_id": ObjectId(template_id)})
    return _tpl_to_response(doc)


@router.delete("/templates/{template_id}")
async def delete_workflow_template(
    template_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Delete a workflow template (admin / manager only)."""
    _require_admin_or_manager(current_user)
    if not ObjectId.is_valid(template_id):
        raise HTTPException(status_code=400, detail="Invalid template ID")
    result = workflow_templates_collection.delete_one({"_id": ObjectId(template_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"message": "Template deleted"}


# ─────────────────────────────────────────────────────────────────────────────

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
    create_audit_log(
        action=AuditAction.workflow_complete,
        resource_type="workflow",
        resource_id=workflow_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Workflow step advanced{f': {comments}' if comments else ''}",
    )
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
    create_audit_log(
        action=AuditAction.status_change,
        resource_type="workflow",
        resource_id=workflow_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Workflow rejected{f': {reason}' if reason else ''}",
    )
    return result


class PauseRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/{workflow_id}/pause")
async def pause_workflow_route(
    workflow_id: str,
    request: PauseRequest = None,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Pause an active workflow. Admin/manager only."""
    _require_admin_or_manager(current_user)
    reason = request.reason if request else None
    result = await pause_workflow(workflow_id, current_user["user_id"], reason=reason)
    if not result:
        raise HTTPException(status_code=400, detail="Cannot pause workflow. It may not be active.")
    create_audit_log(
        action=AuditAction.status_change,
        resource_type="workflow",
        resource_id=workflow_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Workflow paused{f': {reason}' if reason else ''}",
    )
    return result


@router.post("/{workflow_id}/resume")
async def resume_workflow_route(
    workflow_id: str,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Resume a paused workflow. Admin/manager only."""
    _require_admin_or_manager(current_user)
    result = await resume_workflow(workflow_id, current_user["user_id"])
    if not result:
        raise HTTPException(status_code=400, detail="Cannot resume workflow. It may not be paused.")
    create_audit_log(
        action=AuditAction.status_change,
        resource_type="workflow",
        resource_id=workflow_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details="Workflow resumed",
    )
    return result
