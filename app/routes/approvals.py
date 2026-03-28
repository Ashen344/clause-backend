from fastapi import APIRouter, HTTPException, Depends
from app.middleware.auth import get_current_user, get_optional_user
from app.models.approval import ApprovalCreate, VoteRequest
from app.services.approval_service import (
    create_approval,
    get_approval,
    cast_vote,
    get_pending_approvals,
    get_approvals_by_contract,
)

router = APIRouter(prefix="/api/approvals", tags=["Approvals"])


@router.post("/")
async def create_new_approval(approval_data: ApprovalCreate):
    """Create a new approval request for a contract."""
    result = await create_approval(approval_data, user_id="temp_user")
    return result


@router.get("/{approval_id}")
async def get_approval_details(approval_id: str):
    """Get approval details by ID."""
    approval = await get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/{approval_id}/vote")
async def vote_on_approval(approval_id: str, vote: VoteRequest):
    """Cast a vote on an approval request."""
    # In production, user_id would come from auth
    result = await cast_vote(approval_id, user_id="temp_user", vote=vote)
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Cannot vote. You may have already voted, not be an approver, or the approval is closed.",
        )
    return result


@router.get("/pending/{user_id}")
async def get_user_pending_approvals(user_id: str):
    """Get all pending approvals for a specific user."""
    approvals = await get_pending_approvals(user_id)
    return {"approvals": approvals, "count": len(approvals)}


@router.get("/contract/{contract_id}")
async def get_contract_approvals(contract_id: str):
    """Get all approvals for a specific contract."""
    approvals = await get_approvals_by_contract(contract_id)
    return {"approvals": approvals}
