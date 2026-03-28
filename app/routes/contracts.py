from fastapi import APIRouter, HTTPException, Query
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

# Create a router - this groups all contract-related endpoints together
# The prefix means all routes in this file start with /api/contracts
# Tags help organize the auto-generated docs at /docs
router = APIRouter(prefix="/api/contracts", tags=["Contracts"])


# POST /api/contracts - Create a new contract
@router.post("/", response_model=None)
async def create_new_contract(contract: ContractCreate):
    # For now we hardcode user_id - later Clerk auth will provide this
    result = await create_contract(contract, user_id="temp_user")
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
async def update_existing_contract(contract_id: str, update_data: ContractUpdate):
    contract = await update_contract(contract_id, update_data)

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    return contract


# DELETE /api/contracts/{contract_id} - Delete a contract
@router.delete("/{contract_id}")
async def delete_existing_contract(contract_id: str):
    success = await delete_contract(contract_id)

    if not success:
        raise HTTPException(status_code=404, detail="Contract not found")

    return {"message": "Contract deleted successfully"}


# PATCH /api/contracts/{contract_id}/workflow - Update workflow stage
@router.patch("/{contract_id}/workflow")
async def change_workflow_stage(contract_id: str, stage: WorkflowStage):
    contract = await update_workflow_stage(contract_id, stage.value)

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    return contract