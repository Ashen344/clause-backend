from fastapi import APIRouter, HTTPException, Depends
from app.middleware.auth import get_current_user, get_current_user_with_role
from app.models.approval import ApprovalCreate, VoteRequest
from app.services.approval_service import (
    create_approval,
    get_approval,
    cast_vote,
    get_pending_approvals,
    get_approvals_by_contract,
)
from app.config import contracts_collection
from bson import ObjectId

router = APIRouter(prefix="/api/approvals", tags=["Approvals"])


@router.post("/")
async def create_new_approval(
    approval_data: ApprovalCreate,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Create a new approval request. Admins can create for any contract; users only for their own."""
    is_admin = current_user.get("role") in ("admin", "manager")

    if not is_admin:
        # Verify the user owns the contract
        if not ObjectId.is_valid(approval_data.contract_id):
            raise HTTPException(status_code=400, detail="Invalid contract ID")
        contract = contracts_collection.find_one({"_id": ObjectId(approval_data.contract_id)})
        if not contract or contract.get("created_by") != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="You can only create approvals for your own contracts")

    result = await create_approval(approval_data, user_id=current_user["user_id"])
    return result


@router.get("/{approval_id}")
async def get_approval_details(approval_id: str):
    """Get approval details by ID."""
    approval = await get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/{approval_id}/vote")
async def vote_on_approval(
    approval_id: str,
    vote: VoteRequest,
    current_user: dict = Depends(get_current_user_with_role),
):
    """Cast a vote on an approval. Admins can vote on any approval; others only if listed as approver."""
    is_admin = current_user.get("role") in ("admin", "manager")
    result = await cast_vote(approval_id, user_id=current_user["user_id"], vote=vote, is_admin=is_admin)
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
