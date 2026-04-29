import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from conftest import approver, make_approval
from app.services.approval_service import _evaluate_decision


# ══════════════════════════════════════════════════════════════════════
# _evaluate_decision() — all 11 paths
# ══════════════════════════════════════════════════════════════════════
class TestEvaluateDecision:

    def test_P1_no_votes_returns_pending(self):
        approvers = [approver("u1"), approver("u2")]
        assert _evaluate_decision(approvers, "all_required") == "pending"

    def test_P2_first_person_approved(self):
        approvers = [approver("u1", "approved"), approver("u2")]
        assert _evaluate_decision(approvers, "first_person") == "approved"

    def test_P3_first_person_rejected(self):
        approvers = [approver("u1", "rejected")]
        assert _evaluate_decision(approvers, "first_person") == "rejected"

    def test_P4_all_required_one_rejection(self):
        approvers = [approver("u1", "approved"), approver("u2", "rejected")]
        assert _evaluate_decision(approvers, "all_required") == "rejected"

    def test_P4b_changes_requested_also_fails(self):
        approvers = [approver("u1", "changes_requested")]
        assert _evaluate_decision(approvers, "all_required") == "changes_requested"

    def test_P5_all_required_all_approved(self):
        approvers = [approver("u1", "approved"), approver("u2", "approved")]
        assert _evaluate_decision(approvers, "all_required") == "approved"

    def test_P6_partial_votes_still_pending(self):
        approvers = [approver("u1", "approved"), approver("u2", None)]
        assert _evaluate_decision(approvers, "all_required") == "pending"

    def test_P7_majority_not_all_voted(self):
        approvers = [approver("u1", "approved"), approver("u2")]
        assert _evaluate_decision(approvers, "majority") == "pending"

    def test_P8_majority_approved(self):
        approvers = [
            approver("u1", "approved"),
            approver("u2", "approved"),
            approver("u3", "rejected"),
        ]
        assert _evaluate_decision(approvers, "majority") == "approved"

    def test_P9_majority_rejected(self):
        approvers = [
            approver("u1", "rejected"),
            approver("u2", "rejected"),
            approver("u3", "approved"),
        ]
        assert _evaluate_decision(approvers, "majority") == "rejected"

    def test_P10_unknown_type_fallback(self):
        approvers = [approver("u1", "approved")]
        assert _evaluate_decision(approvers, "some_unknown_type") == "pending"

    def test_exact_tie_is_rejected(self):
        approvers = [approver("u1", "approved"), approver("u2", "rejected")]
        assert _evaluate_decision(approvers, "majority") == "rejected"


# ══════════════════════════════════════════════════════════════════════
# cast_vote()
# ══════════════════════════════════════════════════════════════════════
class TestCastVote:

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote("bad-id", "u1", vote)
        assert result is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_approval_not_pending(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(status="approved")
        mock_col.find_one.return_value = approval
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote(str(approval["_id"]), "u1", vote)
        assert result is None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_already_voted_returns_none(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(
            approvers=[{
                "user_id": "u1", "decision": "approved",
                "user_email": None, "decided_at": None
            }]
        )
        mock_col.find_one.return_value = approval
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote(str(approval["_id"]), "u1", vote)
        assert result is None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_unauthorized_voter_returns_none(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(
            approvers=[{
                "user_id": "u2", "decision": None,
                "user_email": None, "decided_at": None
            }]
        )
        mock_col.find_one.return_value = approval
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote(str(approval["_id"]), "u1", vote, is_admin=False)
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# get_pending_approvals()
# ══════════════════════════════════════════════════════════════════════
class TestGetPendingApprovals:

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_returns_only_unvoted_approvals(self, mock_col):
        """
        Branch: user found with decision=None → added to results.
        """
        approval = {
            "_id": ObjectId(), "status": "pending",
            "approvers": [{"user_id": "u1", "decision": None, "user_email": None}],
            "approval_type": "all_required",
            "contract_id": str(ObjectId()),
        }
        mock_col.find.return_value.sort.return_value = iter([approval])

        from app.services.approval_service import get_pending_approvals
        result = await get_pending_approvals("u1")

        assert len(result) == 1
        assert "id" in result[0]

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_excludes_already_voted(self, mock_col):
        """
        Branch: decision is not None → NOT added (already voted).
        """
        approval = {
            "_id": ObjectId(), "status": "pending",
            "approvers": [{"user_id": "u1", "decision": "approved", "user_email": None}],
            "approval_type": "all_required",
            "contract_id": str(ObjectId()),
        }
        mock_col.find.return_value.sort.return_value = iter([approval])

        from app.services.approval_service import get_pending_approvals
        result = await get_pending_approvals("u1")

        assert len(result) == 0

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_col):
        """No pending approvals → empty list."""
        mock_col.find.return_value.sort.return_value = iter([])

        from app.services.approval_service import get_pending_approvals
        result = await get_pending_approvals("u1")

        assert result == []


# ══════════════════════════════════════════════════════════════════════
# get_approvals_by_contract()
# ══════════════════════════════════════════════════════════════════════
class TestGetApprovalsByContract:

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_returns_all_approvals_for_contract(self, mock_col):
        """All approvals for a contract returned as list with string ids."""
        contract_id = str(ObjectId())
        a1 = {"_id": ObjectId(), "contract_id": contract_id,
              "status": "pending",  "approvers": []}
        a2 = {"_id": ObjectId(), "contract_id": contract_id,
              "status": "approved", "approvers": []}
        mock_col.find.return_value.sort.return_value = iter([a1, a2])

        from app.services.approval_service import get_approvals_by_contract
        result = await get_approvals_by_contract(contract_id)

        assert len(result) == 2
        for item in result:
            assert "id"  in item
            assert "_id" not in item

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_col):
        """No approvals for contract → empty list."""
        mock_col.find.return_value.sort.return_value = iter([])

        from app.services.approval_service import get_approvals_by_contract
        result = await get_approvals_by_contract("contract_abc")

        assert result == []