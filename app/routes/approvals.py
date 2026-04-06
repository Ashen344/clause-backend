from fastapi import APIRouter, HTTPException, Depends
from app.middleware.auth import get_current_user, require_role
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
async def create_new_approval(
    approval_data: ApprovalCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new approval request for a contract. Any authenticated user."""
    result = await create_approval(approval_data, user_id=current_user["user_id"])
    return result


@router.get("/{approval_id}")
async def get_approval_details(
    approval_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get approval details by ID."""
    approval = await get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/{approval_id}/vote")
async def vote_on_approval(
    approval_id: str,
    vote: VoteRequest,
    current_user: dict = Depends(require_role(["admin", "manager"])),
):
    """Cast a vote on an approval request. Admin/Manager only."""
    result = await cast_vote(approval_id, user_id=current_user["user_id"], vote=vote)
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Cannot vote. You may have already voted, not be an approver, or the approval is closed.",
        )
    return result


@router.get("/pending/me")
async def get_my_pending_approvals(
    current_user: dict = Depends(require_role(["admin", "manager"])),
):
    """Get all pending approvals for the current user."""
    approvals = await get_pending_approvals(current_user["user_id"])
    return {"approvals": approvals, "count": len(approvals)}


@router.get("/pending/{user_id}")
async def get_user_pending_approvals(
    user_id: str,
    current_user: dict = Depends(require_role(["admin", "manager"])),
):
    """Get all pending approvals for a specific user. Admin/Manager only."""
    approvals = await get_pending_approvals(user_id)
    return {"approvals": approvals, "count": len(approvals)}


@router.get("/contract/{contract_id}")
async def get_contract_approvals(
    contract_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get all approvals for a specific contract."""
    approvals = await get_approvals_by_contract(contract_id)
    return {"approvals": approvals}
