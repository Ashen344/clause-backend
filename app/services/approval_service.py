from bson import ObjectId
from datetime import datetime
from typing import Optional
from app.config import approvals_collection
from app.models.approval import (
    ApprovalCreate,
    ApprovalInDB,
    ApprovalStatus,
    ApprovalDecision,
    ApproverVote,
    VoteRequest,
)


def approval_to_response(approval: dict) -> dict:
    approval["id"] = str(approval["_id"])
    del approval["_id"]
    return approval


async def create_approval(approval_data: ApprovalCreate, user_id: str) -> dict:
    """Create a new approval request."""
    # Build approver list with pending votes
    approvers = [
        ApproverVote(user_id=uid).model_dump()
        for uid in approval_data.approver_ids
    ]

    approval_dict = ApprovalInDB(
        contract_id=approval_data.contract_id,
        workflow_id=approval_data.workflow_id,
        approval_type=approval_data.approval_type,
        approvers=approvers,
        due_date=approval_data.due_date,
        created_by=user_id,
    ).model_dump()

    result = approvals_collection.insert_one(approval_dict)
    created = approvals_collection.find_one({"_id": result.inserted_id})
    return approval_to_response(created)


async def get_approval(approval_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(approval_id):
        return None
    approval = approvals_collection.find_one({"_id": ObjectId(approval_id)})
    if not approval:
        return None
    return approval_to_response(approval)


async def cast_vote(approval_id: str, user_id: str, vote: VoteRequest) -> Optional[dict]:
    """Cast a vote on an approval request."""
    if not ObjectId.is_valid(approval_id):
        return None

    approval = approvals_collection.find_one({"_id": ObjectId(approval_id)})
    if not approval or approval["status"] != ApprovalStatus.pending.value:
        return None

    # Find the approver and check they haven't already voted
    approvers = approval["approvers"]
    voter_found = False
    for approver in approvers:
        if approver["user_id"] == user_id:
            if approver.get("decision") is not None:
                return None  # Already voted
            approver["decision"] = vote.decision.value
            approver["comments"] = vote.comments
            approver["decided_at"] = datetime.utcnow()
            voter_found = True
            break

    if not voter_found:
        return None  # Not an authorized approver

    # Evaluate overall decision based on approval type
    overall_status = _evaluate_decision(approvers, approval["approval_type"])

    update = {
        "approvers": approvers,
        "updated_at": datetime.utcnow(),
    }

    if overall_status != ApprovalStatus.pending.value:
        update["status"] = overall_status
        update["decided_at"] = datetime.utcnow()

    approvals_collection.update_one(
        {"_id": ObjectId(approval_id)},
        {"$set": update}
    )

    return await get_approval(approval_id)


def _evaluate_decision(approvers: list, approval_type: str) -> str:
    """Evaluate the overall approval decision based on votes and type."""
    voted = [a for a in approvers if a.get("decision") is not None]
    total = len(approvers)

    if not voted:
        return ApprovalStatus.pending.value

    if approval_type == "first_person":
        # First vote decides
        return _map_decision(voted[0]["decision"])

    if approval_type == "all_required":
        # Any rejection or changes_requested fails it
        for v in voted:
            if v["decision"] in ("rejected", "changes_requested"):
                return _map_decision(v["decision"])
        # All must have voted and approved
        if len(voted) == total:
            if all(v["decision"] == "approved" for v in voted):
                return ApprovalStatus.approved.value
        return ApprovalStatus.pending.value

    if approval_type == "majority":
        if len(voted) < total:
            return ApprovalStatus.pending.value  # Wait for all votes
        approved_count = sum(1 for v in voted if v["decision"] == "approved")
        if approved_count > total / 2:
            return ApprovalStatus.approved.value
        return ApprovalStatus.rejected.value

    return ApprovalStatus.pending.value


def _map_decision(decision: str) -> str:
    if decision == "approved":
        return ApprovalStatus.approved.value
    if decision == "changes_requested":
        return ApprovalStatus.changes_requested.value
    return ApprovalStatus.rejected.value


async def get_pending_approvals(user_id: str) -> list:
    """Get all pending approvals where the user needs to vote."""
    approvals = approvals_collection.find({
        "status": "pending",
        "approvers.user_id": user_id,
    }).sort("created_at", -1)

    results = []
    for a in approvals:
        # Check if user hasn't voted yet
        for approver in a["approvers"]:
            if approver["user_id"] == user_id and approver.get("decision") is None:
                results.append(approval_to_response(a))
                break

    return results


async def get_approvals_by_contract(contract_id: str) -> list:
    approvals = approvals_collection.find({"contract_id": contract_id}).sort("created_at", -1)
    return [approval_to_response(a) for a in approvals]
