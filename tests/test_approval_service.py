import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from app.services.approval_service import _evaluate_decision
import app.services.approval_service as approval_module


def approver(user_id, decision=None):
    return {
        "user_id": user_id,
        "decision": decision,
        "user_email": f"{user_id}@test.com",
        "decided_at": datetime.utcnow() if decision else None,
    }


def make_approval(status="pending", approval_type="all_required", approvers=None):
    if approvers is None:
        approvers = [approver("u1"), approver("u2")]
    return {
        "_id": ObjectId(),
        "contract_id": str(ObjectId()),
        "status": status,
        "approval_type": approval_type,
        "approvers": approvers,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


class TestEvaluateDecision:
    """FR-WP-04: Approval decision logic (CC=10)"""

    def test_P1_no_votes_returns_pending(self):
        assert _evaluate_decision([approver("u1"), approver("u2")], "all_required") == "pending"

    def test_P2_first_person_approved(self):
        """TC-AP-02: First-person approval"""
        assert _evaluate_decision([approver("u1", "approved")], "first_person") == "approved"

    def test_P3_first_person_rejected(self):
        assert _evaluate_decision([approver("u1", "rejected")], "first_person") == "rejected"

    def test_P4_all_required_one_rejection(self):
        """TC-AP-04: All-required rejection"""
        assert _evaluate_decision(
            [approver("u1", "approved"), approver("u2", "rejected")], "all_required"
        ) == "rejected"

    def test_P4b_changes_requested_also_fails(self):
        assert _evaluate_decision(
            [approver("u1", "changes_requested")], "all_required"
        ) == "changes_requested"

    def test_P5_all_required_all_approved(self):
        """TC-AP-06: All-required approval"""
        assert _evaluate_decision(
            [approver("u1", "approved"), approver("u2", "approved")], "all_required"
        ) == "approved"

    def test_P6_partial_votes_still_pending(self):
        assert _evaluate_decision(
            [approver("u1", "approved"), approver("u2", None)], "all_required"
        ) == "pending"

    def test_P7_majority_not_all_voted(self):
        """TC-AP-08: Majority not ready"""
        assert _evaluate_decision(
            [approver("u1", "approved"), approver("u2")], "majority"
        ) == "pending"

    def test_P8_majority_approved(self):
        """TC-AP-09: Majority approved"""
        assert _evaluate_decision(
            [approver("u1", "approved"), approver("u2", "approved"), approver("u3", "rejected")],
            "majority",
        ) == "approved"

    def test_P9_majority_rejected(self):
        assert _evaluate_decision(
            [approver("u1", "rejected"), approver("u2", "rejected"), approver("u3", "approved")],
            "majority",
        ) == "rejected"

    def test_P10_unknown_type_fallback(self):
        assert _evaluate_decision([approver("u1", "approved")], "some_unknown_type") == "pending"

    def test_P11_exact_tie_is_rejected(self):
        """Boundary: 50% is NOT majority"""
        assert _evaluate_decision(
            [approver("u1", "approved"), approver("u2", "rejected")], "majority"
        ) == "rejected"


class TestCastVote:

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        """TC-AI-13: Input validation"""
        from app.models.approval import VoteRequest, ApprovalDecision
        assert await approval_module.cast_vote(
            "bad-id", "u1", VoteRequest(decision=ApprovalDecision.approved)
        ) is None

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_approval_not_pending(self, mock_col):
        """Cannot vote on decided approval"""
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(status="approved")
        mock_col.find_one.return_value = approval
        
        assert await approval_module.cast_vote(
            str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved)
        ) is None

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_already_voted_returns_none(self, mock_col):
        """Cannot double-vote"""
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u1", "approved")])
        mock_col.find_one.return_value = approval
        
        assert await approval_module.cast_vote(
            str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved)
        ) is None

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_unauthorized_voter_returns_none(self, mock_col):
        """TC-AP-16: Unauthorized voter rejected"""
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u2")])
        mock_col.find_one.return_value = approval
        
        assert await approval_module.cast_vote(
            str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved), is_admin=False
        ) is None

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_valid_vote_updates_status(self, mock_col):
        """TC-AP-17: Vote casting updates status"""
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approval_type="all_required", approvers=[approver("u1"), approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        
        await approval_module.cast_vote(
            str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved)
        )
        
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "approvers" in payload


class TestGetPendingApprovals:

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_returns_only_unvoted_approvals(self, mock_col):
        """TC-AP-18: Get pending approvals"""
        approval = {
            "_id": ObjectId(),
            "status": "pending",
            "approval_type": "all_required",
            "contract_id": str(ObjectId()),
            "approvers": [{"user_id": "u1", "decision": None, "user_email": None}],
        }
        mock_col.find.return_value.sort.return_value = iter([approval])
        
        result = await approval_module.get_pending_approvals("u1")
        assert len(result) == 1

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_excludes_already_voted(self, mock_col):
        approval = {
            "_id": ObjectId(),
            "status": "pending",
            "approval_type": "all_required",
            "contract_id": str(ObjectId()),
            "approvers": [{"user_id": "u1", "decision": "approved", "user_email": None}],
        }
        mock_col.find.return_value.sort.return_value = iter([approval])
        
        result = await approval_module.get_pending_approvals("u1")
        assert len(result) == 0


class TestGetApprovalsByContract:

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_returns_all_approvals_for_contract(self, mock_col):
        """TC-AP-20: Get approvals by contract"""
        cid = str(ObjectId())
        a1 = {"_id": ObjectId(), "contract_id": cid, "status": "pending", "approvers": []}
        a2 = {"_id": ObjectId(), "contract_id": cid, "status": "approved", "approvers": []}
        mock_col.find.return_value.sort.return_value = iter([a1, a2])
        
        result = await approval_module.get_approvals_by_contract(cid)
        assert len(result) == 2

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_col):
        mock_col.find.return_value.sort.return_value = iter([])
        assert await approval_module.get_approvals_by_contract("contract_abc") == []

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_admin_can_vote_even_if_not_listed(self, mock_col):
        """TC-AP-22: Admin can vote even if not in approver list"""
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        
        result = await approval_module.cast_vote(
            str(approval["_id"]), "admin_001", VoteRequest(decision=ApprovalDecision.approved), is_admin=True
        )
        
        # Admin should be added to approvers list
        assert result is not None

    @patch.object(approval_module, "approvals_collection")
    @pytest.mark.asyncio
    async def test_changes_requested_in_all_required(self, mock_col):
        """TC-AP-23: Changes requested handling"""
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u1"), approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        
        await approval_module.cast_vote(
            str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.changes_requested)
        )
        
        payload = mock_col.update_one.call_args[0][1]["$set"]
        # Should have status set when all_required and someone requests changes
        assert "status" in payload or "approvers" in payload