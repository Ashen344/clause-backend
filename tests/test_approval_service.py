"""
test_approval_service.py
Complete white-box + requirements test suite for approval_service.py
FR-WP-04, FR-WP-05, FR-WP-06, NFR-RB-06
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from app.services.approval_service import _evaluate_decision


def approver(user_id, decision=None):
    return {"user_id": user_id, "decision": decision, "user_email": f"{user_id}@test.com", "decided_at": datetime.utcnow() if decision else None}


def make_approval(status="pending", approval_type="all_required", approvers=None):
    if approvers is None:
        approvers = [approver("u1"), approver("u2")]
    return {"_id": ObjectId(), "contract_id": str(ObjectId()), "status": status, "approval_type": approval_type, "approvers": approvers, "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()}


class TestEvaluateDecision:

    def test_P1_no_votes_returns_pending(self):
        assert _evaluate_decision([approver("u1"), approver("u2")], "all_required") == "pending"

    def test_P2_first_person_approved(self):
        assert _evaluate_decision([approver("u1", "approved")], "first_person") == "approved"

    def test_P3_first_person_rejected(self):
        assert _evaluate_decision([approver("u1", "rejected")], "first_person") == "rejected"

    def test_P4_all_required_one_rejection(self):
        assert _evaluate_decision([approver("u1", "approved"), approver("u2", "rejected")], "all_required") == "rejected"

    def test_P4b_changes_requested_also_fails(self):
        assert _evaluate_decision([approver("u1", "changes_requested")], "all_required") == "changes_requested"

    def test_P5_all_required_all_approved(self):
        assert _evaluate_decision([approver("u1", "approved"), approver("u2", "approved")], "all_required") == "approved"

    def test_P6_partial_votes_still_pending(self):
        assert _evaluate_decision([approver("u1", "approved"), approver("u2", None)], "all_required") == "pending"

    def test_P7_majority_not_all_voted(self):
        assert _evaluate_decision([approver("u1", "approved"), approver("u2")], "majority") == "pending"

    def test_P8_majority_approved(self):
        assert _evaluate_decision([approver("u1","approved"), approver("u2","approved"), approver("u3","rejected")], "majority") == "approved"

    def test_P9_majority_rejected(self):
        assert _evaluate_decision([approver("u1","rejected"), approver("u2","rejected"), approver("u3","approved")], "majority") == "rejected"

    def test_P10_unknown_type_fallback(self):
        assert _evaluate_decision([approver("u1", "approved")], "unknown_type") == "pending"

    def test_exact_tie_is_rejected(self):
        assert _evaluate_decision([approver("u1","approved"), approver("u2","rejected")], "majority") == "rejected"


class TestCastVote:

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        assert await cast_vote("bad-id", "u1", VoteRequest(decision=ApprovalDecision.approved)) is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_approval_not_pending(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(status="approved")
        mock_col.find_one.return_value = approval
        assert await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved)) is None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_already_voted_returns_none(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u1", "approved")])
        mock_col.find_one.return_value = approval
        assert await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved)) is None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_unauthorized_voter_returns_none(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u2")])
        mock_col.find_one.return_value = approval
        assert await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved), is_admin=False) is None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_valid_vote_calls_update_one(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u1"), approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        result = await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved))
        mock_col.update_one.assert_called_once()
        assert result is not None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_vote_payload_sets_decision_and_timestamp(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u1"), approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        voter = next(a for a in payload["approvers"] if a["user_id"] == "u1")
        assert voter["decision"] == "approved"
        assert voter["decided_at"] is not None

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_rejected_vote_recorded_correctly(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u1"), approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.rejected))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        voter = next(a for a in payload["approvers"] if a["user_id"] == "u1")
        assert voter["decision"] == "rejected"

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_all_required_last_vote_closes_approved(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approval_type="all_required", approvers=[approver("u1","approved"), approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        await cast_vote(str(approval["_id"]), "u2", VoteRequest(decision=ApprovalDecision.approved))
        assert mock_col.update_one.call_args[0][1]["$set"]["status"] == "approved"

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_first_rejection_closes_all_required_as_rejected(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approval_type="all_required", approvers=[approver("u1"), approver("u2")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.rejected))
        assert mock_col.update_one.call_args[0][1]["$set"]["status"] == "rejected"

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_majority_partial_votes_stays_pending(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approval_type="majority", approvers=[approver("u1"), approver("u2"), approver("u3")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        await cast_vote(str(approval["_id"]), "u1", VoteRequest(decision=ApprovalDecision.approved))
        assert mock_col.update_one.call_args[0][1]["$set"]["status"] == "pending"

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_admin_can_vote_on_any_approval(self, mock_col):
        from app.services.approval_service import cast_vote
        from app.models.approval import VoteRequest, ApprovalDecision
        approval = make_approval(approvers=[approver("u2"), approver("u3")])
        mock_col.find_one.side_effect = [approval, {**approval}]
        mock_col.update_one.return_value = MagicMock()
        result = await cast_vote(str(approval["_id"]), "admin_user", VoteRequest(decision=ApprovalDecision.approved), is_admin=True)
        assert result is not None


class TestGetPendingApprovals:

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_returns_only_unvoted_approvals(self, mock_col):
        from app.services.approval_service import get_pending_approvals
        approval = {"_id": ObjectId(), "status": "pending", "approval_type": "all_required", "contract_id": str(ObjectId()), "approvers": [{"user_id": "u1", "decision": None, "user_email": None}]}
        mock_col.find.return_value.sort.return_value = iter([approval])
        result = await get_pending_approvals("u1")
        assert len(result) == 1 and "id" in result[0]

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_excludes_already_voted(self, mock_col):
        from app.services.approval_service import get_pending_approvals
        approval = {"_id": ObjectId(), "status": "pending", "approval_type": "all_required", "contract_id": str(ObjectId()), "approvers": [{"user_id": "u1", "decision": "approved", "user_email": None}]}
        mock_col.find.return_value.sort.return_value = iter([approval])
        assert await get_pending_approvals("u1") == []

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_col):
        from app.services.approval_service import get_pending_approvals
        mock_col.find.return_value.sort.return_value = iter([])
        assert await get_pending_approvals("u1") == []

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_user_not_first_in_list_is_found(self, mock_col):
        from app.services.approval_service import get_pending_approvals
        approval = {"_id": ObjectId(), "status": "pending", "approval_type": "all_required", "contract_id": str(ObjectId()), "approvers": [approver("u1","approved"), approver("u2")]}
        mock_col.find.return_value.sort.return_value = iter([approval])
        result = await get_pending_approvals("u2")
        assert len(result) == 1

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_user_not_in_approvers_excluded(self, mock_col):
        from app.services.approval_service import get_pending_approvals
        approval = {"_id": ObjectId(), "status": "pending", "approval_type": "all_required", "contract_id": str(ObjectId()), "approvers": [approver("u1"), approver("u2")]}
        mock_col.find.return_value.sort.return_value = iter([approval])
        assert await get_pending_approvals("u3") == []


class TestGetApprovalsByContract:

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_returns_all_approvals_for_contract(self, mock_col):
        from app.services.approval_service import get_approvals_by_contract
        cid = str(ObjectId())
        a1 = {"_id": ObjectId(), "contract_id": cid, "status": "pending", "approvers": []}
        a2 = {"_id": ObjectId(), "contract_id": cid, "status": "approved", "approvers": []}
        mock_col.find.return_value.sort.return_value = iter([a1, a2])
        result = await get_approvals_by_contract(cid)
        assert len(result) == 2
        for item in result:
            assert "id" in item and "_id" not in item

    @patch("app.services.approval_service.approvals_collection")
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_col):
        from app.services.approval_service import get_approvals_by_contract
        mock_col.find.return_value.sort.return_value = iter([])
        assert await get_approvals_by_contract("contract_abc") == []