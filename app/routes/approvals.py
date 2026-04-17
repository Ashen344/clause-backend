from fastapi import APIRouter, HTTPException, Depends
from app.middleware.auth import get_current_user
from app.models.approval import ApprovalCreate, VoteRequest
from app.services.approval_service import (
    create_approval,
    get_approval,
    cast_vote,
    get_pending_approvals,
    get_approvals_by_contract,
)
from app.services.audit_service import create_audit_log
from app.services.notification_service import create_notification
from app.models.audit_log import AuditAction
from app.models.notification import NotificationCreate, NotificationType

router = APIRouter(prefix="/api/approvals", tags=["Approvals"])


@router.post("/")
async def create_new_approval(
    approval_data: ApprovalCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new approval request for a contract."""
    result = await create_approval(approval_data, user_id=current_user["user_id"])

    create_audit_log(
        action=AuditAction.create,
        resource_type="approval",
        resource_id=result["id"],
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Created approval request for contract {approval_data.contract_id}",
    )

    # Notify each approver
    for approver_id in approval_data.approver_ids:
        create_notification(NotificationCreate(
            user_id=approver_id,
            notification_type=NotificationType.approval_required,
            title="Approval Required",
            message=f"You have been requested to approve contract {approval_data.contract_id}.",
            contract_id=approval_data.contract_id,
        ))

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
    current_user: dict = Depends(get_current_user),
):
    """Cast a vote on an approval request."""
    result = await cast_vote(approval_id, user_id=current_user["user_id"], vote=vote)
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Cannot vote. You may have already voted, not be an approver, or the approval is closed.",
        )

    create_audit_log(
        action=AuditAction.approval_vote,
        resource_type="approval",
        resource_id=approval_id,
        user_id=current_user["user_id"],
        user_email=current_user.get("email"),
        details=f"Voted '{vote.decision.value}' on approval",
    )

    # Notify about the decision if approval is resolved
    if result.get("status") != "pending":
        create_notification(NotificationCreate(
            user_id=result.get("created_by", current_user["user_id"]),
            notification_type=NotificationType.approval_decision,
            title=f"Approval {result['status'].replace('_', ' ').title()}",
            message=f"Approval for contract {result.get('contract_id', '')} has been {result['status']}.",
            contract_id=result.get("contract_id"),
        ))

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
