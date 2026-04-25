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
        """
        PATH P1 — Nobody has voted yet.
        voted=[] → L113 True → return pending
        """
        approvers = [approver("u1"), approver("u2")]
        assert _evaluate_decision(approvers, "all_required") == "pending"

    def test_P2_first_person_approved(self):
        """
        PATH P2 — first_person mode, first vote = approved.
        L116 True → L118 → _map_decision → approved
        """
        approvers = [approver("u1", "approved"), approver("u2")]
        assert _evaluate_decision(approvers, "first_person") == "approved"

    def test_P3_first_person_rejected(self):
        """
        PATH P3 — first_person mode, first vote = rejected.
        L116 True → L118 → _map_decision → rejected
        """
        approvers = [approver("u1", "rejected")]
        assert _evaluate_decision(approvers, "first_person") == "rejected"

    def test_P4_all_required_one_rejection(self):
        """
        PATH P4 — all_required, someone rejected.
        L120 True → L122 loop → L123 True → L124 → rejected
        """
        approvers = [approver("u1", "approved"), approver("u2", "rejected")]
        assert _evaluate_decision(approvers, "all_required") == "rejected"

    def test_P4b_changes_requested_also_fails(self):
        """
        PATH P4b — changes_requested also triggers failure.
        L123: 'changes_requested' is in the tuple → True → L124
        """
        approvers = [approver("u1", "changes_requested")]
        assert _evaluate_decision(approvers, "all_required") == "changes_requested"

    def test_P5_all_required_all_approved(self):
        """
        PATH P5 — all_required, all voted, all approved.
        L123 False → L126 True (2==2) → L127 True → L128 approved
        """
        approvers = [approver("u1", "approved"), approver("u2", "approved")]
        assert _evaluate_decision(approvers, "all_required") == "approved"

    def test_P6_partial_votes_still_pending(self):
        """
        PATH P6 — all_required, only some voted.
        L126 False (1 != 2) → L129 pending
        """
        approvers = [approver("u1", "approved"), approver("u2", None)]
        assert _evaluate_decision(approvers, "all_required") == "pending"

    def test_P7_majority_not_all_voted(self):
        """
        PATH P7 — majority, not everyone voted.
        L132 True (1 < 2) → L133 pending
        """
        approvers = [approver("u1", "approved"), approver("u2")]
        assert _evaluate_decision(approvers, "majority") == "pending"

    def test_P8_majority_approved(self):
        """
        PATH P8 — majority, approved_count > half.
        L134: approved=2, total=3
        L135: 2 > 1.5 → True → L136 approved
        """
        approvers = [
            approver("u1", "approved"),
            approver("u2", "approved"),
            approver("u3", "rejected"),
        ]
        assert _evaluate_decision(approvers, "majority") == "approved"

    def test_P9_majority_rejected(self):
        """
        PATH P9 — majority, approved_count NOT > half.
        L135: 1 > 1.5 → False → L137 rejected
        """
        approvers = [
            approver("u1", "rejected"),
            approver("u2", "rejected"),
            approver("u3", "approved"),
        ]
        assert _evaluate_decision(approvers, "majority") == "rejected"

    def test_P10_unknown_type_fallback(self):
        """
        PATH P10 — approval_type not recognised.
        L116, L120, L131 all False → falls to L139 pending
        """
        approvers = [approver("u1", "approved")]
        assert _evaluate_decision(approvers, "some_unknown_type") == "pending"

    def test_exact_tie_is_rejected(self):
        """
        BOUNDARY — 50% is NOT a majority (strict > not >=).
        1 approved out of 2: 1 > 2/2=1.0 → False → rejected
        """
        approvers = [approver("u1", "approved"), approver("u2", "rejected")]
        assert _evaluate_decision(approvers, "majority") == "rejected"


# ══════════════════════════════════════════════════════════════════════
# cast_vote() — branch coverage
# ══════════════════════════════════════════════════════════════════════
class TestCastVote:

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        """Bad ObjectId → None, DB never touched."""
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote("bad-id", "u1", vote)

        assert result is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_approval_not_pending(self, mock_col):
        """Approval already decided → cannot vote again → None."""
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
        """Voter already has a decision → cannot double-vote → None."""
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(
            approvers=[{"user_id": "u1", "decision": "approved", "user_email": None, "decided_at": None}]
        )
        mock_col.find_one.return_value = approval
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote(str(approval["_id"]), "u1", vote)

        assert result is None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_unauthorized_voter_returns_none(self, mock_col):
        """User not in approvers list and not admin → None."""
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(
            approvers=[{"user_id": "u2", "decision": None, "user_email": None, "decided_at": None}]
        )
        mock_col.find_one.return_value = approval
        vote = VoteRequest(decision=ApprovalDecision.approved)
        result = await cast_vote(str(approval["_id"]), "u1", vote, is_admin=False)

        assert result is None