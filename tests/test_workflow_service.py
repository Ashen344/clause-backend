import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from conftest import make_workflow


# ══════════════════════════════════════════════════════════════════════
# advance_workflow()
# PATHS: P1=invalid | P2=not found | P3=not active | P4=out of bounds
#        P5=mid no comments | P6=mid with comments | P7=last step done
# ══════════════════════════════════════════════════════════════════════
class TestAdvanceWorkflow:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_wf):
        """
        PATH P1 — Bad ObjectId.
        Statement: L104(T), L105
        Branch:    L104 TRUE side
        """
        from app.services.workflow_service import advance_workflow
        result = await advance_workflow("bad-id", "user_001")

        assert result is None
        mock_wf.find_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_workflow_not_found(self, mock_wf):
        """
        PATH P2 — DB returns None.
        Statement: L104(F), L107, L108(T), L109
        Branch:    L108 TRUE (not workflow)
        """
        mock_wf.find_one.return_value = None

        from app.services.workflow_service import advance_workflow
        result = await advance_workflow(str(ObjectId()), "user_001")

        assert result is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_non_active_workflow_returns_none(self, mock_wf):
        """
        PATH P3 — Workflow exists but status != active.
        Statement: L104(F), L107, L108(T), L109
        Branch:    L108 TRUE (status != active)
        """
        wf = make_workflow(status="completed")
        mock_wf.find_one.return_value = wf

        from app.services.workflow_service import advance_workflow
        result = await advance_workflow(str(wf["_id"]), "user_001")

        assert result is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_step_out_of_bounds(self, mock_wf):
        """
        PATH P4 — current_step_idx >= len(steps).
        Statement: L108(F), L111, L112, L114(T), L115
        Branch:    L114 TRUE side
        """
        wf = make_workflow(num_steps=2, current_step=10)
        mock_wf.find_one.return_value = wf

        from app.services.workflow_service import advance_workflow
        result = await advance_workflow(str(wf["_id"]), "user_001")

        assert result is None

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_mid_advance_no_comments(self, mock_wf, mock_ct):
        """
        PATH P5 — Mid-workflow step, no comments passed.
        Statement: L114(F), L118, L119, L120, L121(F), L125, L132(F), L145, L160, L165
        Branch:    L121 FALSE, L132 FALSE
        """
        wf = make_workflow(num_steps=3, current_step=1)
        mock_wf.find_one.return_value = wf
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()

        from app.services.workflow_service import advance_workflow
        await advance_workflow(str(wf["_id"]), "user_001")

        payload = mock_wf.update_one.call_args[0][1]["$set"]
        assert payload["steps"][0].get("comments") is None
        assert payload["steps"][1]["status"] == "in_progress"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_comments_saved_on_step(self, mock_wf, mock_ct):
        """
        PATH P6 — Mid-workflow step, comments provided.
        Statement: L114(F), L118, L119, L120, L121(T), L122, L132(F), L145, L160, L165
        Branch:    L121 TRUE, L132 FALSE
        """
        wf = make_workflow(num_steps=3, current_step=1)
        mock_wf.find_one.return_value = wf
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()

        from app.services.workflow_service import advance_workflow
        await advance_workflow(str(wf["_id"]), "user_001", comments="Looks good!")

        payload = mock_wf.update_one.call_args[0][1]["$set"]
        assert payload["steps"][0]["comments"] == "Looks good!"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_last_step_completion_marks_workflow_done(self, mock_wf, mock_ct):
        """
        PATH P7 — Completing the final step.
        Statement: L114(F), L118, L132(T), L134, L135, L138(T), L139, L160, L165
        Branch:    L132 TRUE, L138 TRUE
        Expects:   workflow.status=completed, contract.status=active
        """
        wf = make_workflow(num_steps=2, current_step=2)
        wf["steps"][0]["status"] = "completed"
        wf["steps"][1]["status"] = "in_progress"

        updated_wf = {**wf, "_id": wf["_id"], "status": "completed"}
        mock_wf.find_one.side_effect = [wf, updated_wf]
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()

        from app.services.workflow_service import advance_workflow
        await advance_workflow(str(wf["_id"]), "user_001")

        wf_payload = mock_wf.update_one.call_args[0][1]["$set"]
        assert wf_payload["status"] == "completed"

        ct_payload = mock_ct.update_one.call_args[0][1]["$set"]
        assert ct_payload["status"] == "active"
        assert ct_payload["workflow_stage"] == "storage"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_last_step_no_contract_id(self, mock_wf, mock_ct):
        """
        EXTRA — covers L138 FALSE branch (contract_id is None).
        Expects: contracts_collection.update_one never called.
        Branch:  L138 FALSE side
        """
        wf = make_workflow(num_steps=1, current_step=1)
        wf["contract_id"] = None

        updated_wf = {**wf, "_id": wf["_id"]}
        mock_wf.find_one.side_effect = [wf, updated_wf]
        mock_wf.update_one.return_value = MagicMock()

        from app.services.workflow_service import advance_workflow
        await advance_workflow(str(wf["_id"]), "user_001")

        mock_ct.update_one.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
# reject_workflow()
# ══════════════════════════════════════════════════════════════════════
class TestRejectWorkflow:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_wf):
        from app.services.workflow_service import reject_workflow
        result = await reject_workflow("bad-id", "user_001")
        assert result is None
        mock_wf.find_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_workflow_not_found(self, mock_wf):
        mock_wf.find_one.return_value = None
        from app.services.workflow_service import reject_workflow
        result = await reject_workflow(str(ObjectId()), "user_001")
        assert result is None

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_rejection_reverts_contract_to_draft(self, mock_wf, mock_ct):
        """
        Rejection must:
        1. Set workflow.status = cancelled
        2. Set contract.status = draft
        3. Set contract.workflow_stage = request
        """
        wf = make_workflow()
        mock_wf.find_one.side_effect = [wf, {**wf, "_id": wf["_id"]}]
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()

        from app.services.workflow_service import reject_workflow
        await reject_workflow(str(wf["_id"]), "user_001", reason="Needs revision")

        wf_payload = mock_wf.update_one.call_args[0][1]["$set"]
        assert wf_payload["status"] == "cancelled"

        ct_payload = mock_ct.update_one.call_args[0][1]["$set"]
        assert ct_payload["status"]         == "draft"
        assert ct_payload["workflow_stage"] == "request"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_rejection_with_reason_saved(self, mock_wf, mock_ct):
        """Reason string must be saved on the rejected step."""
        wf = make_workflow()
        mock_wf.find_one.side_effect = [wf, {**wf, "_id": wf["_id"]}]
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()

        from app.services.workflow_service import reject_workflow
        await reject_workflow(str(wf["_id"]), "user_001", reason="Missing signature")

        payload = mock_wf.update_one.call_args[0][1]["$set"]
        assert payload["steps"][0]["comments"] == "Missing signature"