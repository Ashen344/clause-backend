import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from conftest import make_workflow


# ══════════════════════════════════════════════════════════════════════
# advance_workflow()
# ══════════════════════════════════════════════════════════════════════
class TestAdvanceWorkflow:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_wf):
        """PATH P1 — Bad ObjectId. Branch: L104 TRUE side"""
        from app.services.workflow_service import advance_workflow
        result = await advance_workflow("bad-id", "user_001")
        assert result is None
        mock_wf.find_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_workflow_not_found(self, mock_wf):
        """PATH P2 — DB returns None. Branch: L108 TRUE (not workflow)"""
        mock_wf.find_one.return_value = None

        from app.services.workflow_service import advance_workflow
        result = await advance_workflow(str(ObjectId()), "user_001")
        assert result is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_non_active_workflow_returns_none(self, mock_wf):
        """PATH P3 — status != active. Branch: L108 TRUE (status != active)"""
        wf = make_workflow(status="completed")
        mock_wf.find_one.return_value = wf

        from app.services.workflow_service import advance_workflow
        result = await advance_workflow(str(wf["_id"]), "user_001")
        assert result is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_step_out_of_bounds(self, mock_wf):
        """PATH P4 — current_step_idx >= len(steps). Branch: L114 TRUE side"""
        wf = make_workflow(num_steps=2, current_step=10)
        mock_wf.find_one.return_value = wf

        from app.services.workflow_service import advance_workflow
        result = await advance_workflow(str(wf["_id"]), "user_001")
        assert result is None

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_mid_advance_no_comments(self, mock_wf, mock_ct):
        """PATH P5 — Mid step, no comments. Branch: L121 FALSE, L132 FALSE"""
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
        """PATH P6 — Mid step with comments. Branch: L121 TRUE, L132 FALSE"""
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
        """PATH P7 — Last step. Branch: L132 TRUE, L138 TRUE"""
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
        assert ct_payload["status"]         == "active"
        assert ct_payload["workflow_stage"] == "storage"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_last_step_no_contract_id(self, mock_wf, mock_ct):
        """EXTRA — L138 FALSE branch (contract_id is None)."""
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
        """Rejection: workflow=cancelled, contract=draft, stage=request."""
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
        """Reason string saved on the rejected step."""
        wf = make_workflow()
        mock_wf.find_one.side_effect = [wf, {**wf, "_id": wf["_id"]}]
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()

        from app.services.workflow_service import reject_workflow
        await reject_workflow(str(wf["_id"]), "user_001", reason="Missing signature")

        payload = mock_wf.update_one.call_args[0][1]["$set"]
        assert payload["steps"][0]["comments"] == "Missing signature"


# ══════════════════════════════════════════════════════════════════════
# get_workflow()
# PATHS: P1=invalid id | P2=not found | P3=found
# ══════════════════════════════════════════════════════════════════════
class TestGetWorkflow:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_wf):
        """PATH P1 — Bad ObjectId → None. Branch: guard TRUE side"""
        from app.services.workflow_service import get_workflow
        result = await get_workflow("bad-id")
        assert result is None
        mock_wf.find_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, mock_wf):
        """PATH P2 — Valid id but missing. Branch: if not workflow TRUE"""
        mock_wf.find_one.return_value = None
        from app.services.workflow_service import get_workflow
        result = await get_workflow(str(ObjectId()))
        assert result is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_found_returns_workflow(self, mock_wf):
        """PATH P3 — Valid id, workflow found. Branch: if not workflow FALSE"""
        wf = make_workflow()
        mock_wf.find_one.return_value = wf
        from app.services.workflow_service import get_workflow
        result = await get_workflow(str(ObjectId()))
        assert result is not None
        assert "id"  in result
        assert "_id" not in result


# ══════════════════════════════════════════════════════════════════════
# get_all_workflows()
# PATHS: P1=admin | P2=non-admin no contracts | P3=non-admin with contracts
# ══════════════════════════════════════════════════════════════════════
class TestGetAllWorkflows:

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_admin_sees_all_workflows(self, mock_wf, mock_ct):
        """Branch: is_admin TRUE → all workflows, no contract filter."""
        wf = make_workflow()
        mock_wf.find.return_value.sort.return_value = iter([wf])

        from app.services.workflow_service import get_all_workflows
        result = await get_all_workflows("admin_001", is_admin=True)

        assert "workflows" in result
        assert result["total"] >= 0
        mock_ct.find.assert_not_called()

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_non_admin_no_contracts_returns_empty(self, mock_wf, mock_ct):
        """Branch: is_admin FALSE, no contracts → empty immediately."""
        mock_ct.find.return_value = iter([])

        from app.services.workflow_service import get_all_workflows
        result = await get_all_workflows("user_001", is_admin=False)

        assert result == {"workflows": [], "total": 0}
        mock_wf.find.assert_not_called()

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_non_admin_with_contracts_filters_workflows(self, mock_wf, mock_ct):
        """Branch: is_admin FALSE, has contracts → filtered by contract_ids."""
        contract_oid = ObjectId()
        mock_ct.find.return_value = iter([{"_id": contract_oid}])

        wf = make_workflow(contract_id=str(contract_oid))
        mock_wf.find.return_value.sort.return_value = iter([wf])

        from app.services.workflow_service import get_all_workflows
        result = await get_all_workflows("user_001", is_admin=False)

        assert "workflows" in result
        mock_wf.find.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
# get_workflows_by_contract()
# PATHS: P1=has workflows | P2=empty
# ══════════════════════════════════════════════════════════════════════
class TestGetWorkflowsByContract:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_returns_workflows_for_contract(self, mock_wf):
        """All workflows for a contract returned as list with string ids."""
        wf1 = make_workflow()
        wf2 = make_workflow()
        mock_wf.find.return_value.sort.return_value = iter([wf1, wf2])

        from app.services.workflow_service import get_workflows_by_contract
        result = await get_workflows_by_contract("contract_abc")

        assert len(result) == 2
        for wf in result:
            assert "id"  in wf
            assert "_id" not in wf

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_wf):
        """No workflows for contract → empty list."""
        mock_wf.find.return_value.sort.return_value = iter([])

        from app.services.workflow_service import get_workflows_by_contract
        result = await get_workflows_by_contract("contract_abc")

        assert result == []