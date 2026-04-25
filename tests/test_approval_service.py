import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from conftest import approver, make_approval
from app.services.approval_service import _evaluate_decision


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
                "user_id":    "u1",
                "decision":   "approved",
                "user_email": None,
                "decided_at": None
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
                "user_id":    "u2",
                "decision":   None,
                "user_email": None,
                "decided_at": None
            }]
        )
        mock_col.find_one.return_value = approval
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote(str(approval["_id"]), "u1", vote, is_admin=False)

        assert result is None