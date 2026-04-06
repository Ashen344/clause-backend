from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
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
from app.middleware.auth import get_current_user, require_role

router = APIRouter(prefix="/api/contracts", tags=["Contracts"])


@router.post("/", response_model=None)
async def create_new_contract(
    contract: ContractCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new contract. Any authenticated user can create."""
    result = await create_contract(contract, user_id=current_user["user_id"])
    return result


@router.get("/")
async def list_contracts(
    search: Optional[str] = Query(None, description="Search by title"),
    contract_type: Optional[ContractType] = Query(None),
    status: Optional[ContractStatus] = Query(None),
    workflow_stage: Optional[WorkflowStage] = Query(None),
    risk_level: Optional[RiskLevel] = Query(None),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: dict = Depends(get_current_user),
):
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


@router.get("/dashboard")
async def dashboard_statistics(current_user: dict = Depends(get_current_user)):
    return await get_dashboard_stats()


@router.get("/{contract_id}")
async def get_single_contract(
    contract_id: str,
    current_user: dict = Depends(get_current_user),
):
    contract = await get_contract(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.put("/{contract_id}")
async def update_existing_contract(
    contract_id: str,
    update_data: ContractUpdate,
    current_user: dict = Depends(get_current_user),
):
    contract = await update_contract(contract_id, update_data)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.delete("/{contract_id}")
async def delete_existing_contract(
    contract_id: str,
    current_user: dict = Depends(get_current_user),
):
    success = await delete_contract(contract_id)
    if not success:
        raise HTTPException(status_code=404, detail="Contract not found")
    return {"message": "Contract deleted successfully"}


@router.patch("/{contract_id}/workflow")
async def change_workflow_stage(
    contract_id: str,
    stage: WorkflowStage,
    current_user: dict = Depends(require_role(["admin", "manager"])),
):
    """Update workflow stage. Admin/Manager only."""
    contract = await update_workflow_stage(contract_id, stage.value)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract