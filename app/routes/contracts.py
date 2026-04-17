from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
from app.middleware.auth import get_current_user
from app.models.contract import (
    ContractCreate,
    ContractUpdate,
    ContractResponse,
    ContractFilter,
    ContractType,
    ContractStatus,
    WorkflowStage,
    RiskLevel,
)
from app.services.contract_service import (
    create_contract,
    get_contract,
    get_contracts,
    update_contract,
    delete_contract,
    update_workflow_stage,
    get_dashboard_stats,
)
from app.services.audit_service import create_audit_log
from app.services.notification_service import create_notification
from app.models.audit_log import AuditAction
from app.models.notification import NotificationCreate, NotificationType

# Create a router - this groups all contract-related endpoints together
# The prefix means all routes in this file start with /api/contracts
# Tags help organize the auto-generated docs at /docs
router = APIRouter(prefix="/api/contracts", tags=["Contracts"])


# POST /api/contracts - Create a new contract
@router.post("/", response_model=None)
async def create_new_contract(
    contract: ContractCreate,
    current_user: dict = Depends(get_current_user),
):
    result = await create_contract(contract, user_id=current_user["user_id"])

    create_audit_log(
        action=AuditAction.create,
        resource_type="contract",
        resource_id=result["id"],
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Created contract: {contract.title}",
    )

    create_notification(NotificationCreate(
        user_id=current_user["user_id"],
        notification_type=NotificationType.status_change,
        title="Contract Created",
        message=f"Contract '{contract.title}' has been created.",
        contract_id=result["id"],
    ))

    return result


# GET /api/contracts - List all contracts with optional filters
@router.get("/")
async def list_contracts(
    search: Optional[str] = Query(None, description="Search by title"),
    contract_type: Optional[ContractType] = Query(None),
    status: Optional[ContractStatus] = Query(None),
    workflow_stage: Optional[WorkflowStage] = Query(None),
    risk_level: Optional[RiskLevel] = Query(None),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
):
    # Build the filter object from query parameters
    filters = ContractFilter(
        search=search,
        contract_type=contract_type,
        status=status,
        workflow_stage=workflow_stage,
        risk_level=risk_level,
        page=page,
        per_page=per_page,
    )
    return await get_contracts(filters)


# GET /api/contracts/dashboard - Dashboard statistics
# IMPORTANT: This route must be ABOVE /{contract_id}
# Otherwise FastAPI thinks "dashboard" is a contract ID
@router.get("/dashboard")
async def dashboard_statistics():
    return await get_dashboard_stats()


# GET /api/contracts/{contract_id} - Get a single contract
@router.get("/{contract_id}")
async def get_single_contract(contract_id: str):
    contract = await get_contract(contract_id)

    if not contract:
        # Return a 404 error with a clear message
        raise HTTPException(status_code=404, detail="Contract not found")

    return contract


# PUT /api/contracts/{contract_id} - Update a contract
@router.put("/{contract_id}")
async def update_existing_contract(
    contract_id: str,
    update_data: ContractUpdate,
    current_user: dict = Depends(get_current_user),
):
    contract = await update_contract(contract_id, update_data)

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    create_audit_log(
        action=AuditAction.update,
        resource_type="contract",
        resource_id=contract_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Updated contract: {contract.get('title', contract_id)}",
    )

    if update_data.status:
        create_notification(NotificationCreate(
            user_id=current_user["user_id"],
            notification_type=NotificationType.status_change,
            title="Contract Status Updated",
            message=f"Contract status changed to {update_data.status.value}.",
            contract_id=contract_id,
        ))

    return contract


# DELETE /api/contracts/{contract_id} - Delete a contract
@router.delete("/{contract_id}")
async def delete_existing_contract(
    contract_id: str,
    current_user: dict = Depends(get_current_user),
):
    success = await delete_contract(contract_id)

    if not success:
        raise HTTPException(status_code=404, detail="Contract not found")

    create_audit_log(
        action=AuditAction.delete,
        resource_type="contract",
        resource_id=contract_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details="Deleted contract",
    )

    return {"message": "Contract deleted successfully"}


# PATCH /api/contracts/{contract_id}/workflow - Update workflow stage
@router.patch("/{contract_id}/workflow")
async def change_workflow_stage(
    contract_id: str,
    stage: WorkflowStage,
    current_user: dict = Depends(get_current_user),
):
    contract = await update_workflow_stage(contract_id, stage.value)

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    create_audit_log(
        action=AuditAction.status_change,
        resource_type="contract",
        resource_id=contract_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Changed workflow stage to: {stage.value}",
    )

    create_notification(NotificationCreate(
        user_id=current_user["user_id"],
        notification_type=NotificationType.workflow_update,
        title="Workflow Stage Changed",
        message=f"Contract workflow stage changed to {stage.value}.",
        contract_id=contract_id,
    ))

    return contract
