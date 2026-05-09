"""
test_workflow_service.py
Complete white-box + requirements test suite for workflow_service.py
FR-WP-04, FR-WP-05, FR-WP-06, NFR-RB-04, NFR-RB-06, NFR-SC-04
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime


def make_workflow(num_steps=2, current_step=1, status="active", contract_id=None):
    steps = [{"name": f"Step {i}", "status": "in_progress" if i == 1 else "pending", "assignee": f"u{i}"} for i in range(1, num_steps + 1)]
    return {"_id": ObjectId(), "status": status, "contract_id": contract_id or str(ObjectId()), "current_step": current_step, "steps": steps, "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()}


class TestAdvanceWorkflow:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_wf):
        from app.services.workflow_service import advance_workflow
        assert await advance_workflow("bad-id", "user_001") is None
        mock_wf.find_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_workflow_not_found(self, mock_wf):
        mock_wf.find_one.return_value = None
        from app.services.workflow_service import advance_workflow
        assert await advance_workflow(str(ObjectId()), "user_001") is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_non_active_workflow_returns_none(self, mock_wf):
        mock_wf.find_one.return_value = make_workflow(status="completed")
        from app.services.workflow_service import advance_workflow
        assert await advance_workflow(str(ObjectId()), "user_001") is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_step_out_of_bounds(self, mock_wf):
        mock_wf.find_one.return_value = make_workflow(num_steps=2, current_step=10)
        from app.services.workflow_service import advance_workflow
        assert await advance_workflow(str(ObjectId()), "user_001") is None

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_mid_advance_no_comments(self, mock_wf, mock_ct):
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
        wf = make_workflow(num_steps=3, current_step=1)
        mock_wf.find_one.return_value = wf
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()
        from app.services.workflow_service import advance_workflow
        await advance_workflow(str(wf["_id"]), "user_001", comments="Looks good!")
        assert mock_wf.update_one.call_args[0][1]["$set"]["steps"][0]["comments"] == "Looks good!"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_last_step_completion_marks_workflow_done(self, mock_wf, mock_ct):
        wf = make_workflow(num_steps=2, current_step=2)
        wf["steps"][0]["status"] = "completed"
        updated = {**wf, "_id": wf["_id"], "status": "completed"}
        mock_wf.find_one.side_effect = [wf, updated]
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()
        from app.services.workflow_service import advance_workflow
        await advance_workflow(str(wf["_id"]), "user_001")
        assert mock_wf.update_one.call_args[0][1]["$set"]["status"] == "completed"
        ct_payload = mock_ct.update_one.call_args[0][1]["$set"]
        assert ct_payload["status"] == "active"
        assert ct_payload["workflow_stage"] == "storage"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_last_step_no_contract_id(self, mock_wf, mock_ct):
        wf = make_workflow(num_steps=1, current_step=1)
        wf["contract_id"] = None
        mock_wf.find_one.side_effect = [wf, {**wf, "_id": wf["_id"]}]
        mock_wf.update_one.return_value = MagicMock()
        from app.services.workflow_service import advance_workflow
        await advance_workflow(str(wf["_id"]), "user_001")
        mock_ct.update_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_none_id_rejected(self, mock_wf):
        from app.services.workflow_service import advance_workflow
        assert await advance_workflow(None, "user_001") is None
        mock_wf.find_one.assert_not_called()


class TestRejectWorkflow:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_wf):
        from app.services.workflow_service import reject_workflow
        assert await reject_workflow("bad-id", "user_001") is None
        mock_wf.find_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_workflow_not_found(self, mock_wf):
        mock_wf.find_one.return_value = None
        from app.services.workflow_service import reject_workflow
        assert await reject_workflow(str(ObjectId()), "user_001") is None

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_rejection_reverts_contract_to_draft(self, mock_wf, mock_ct):
        wf = make_workflow()
        mock_wf.find_one.side_effect = [wf, {**wf, "_id": wf["_id"]}]
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()
        from app.services.workflow_service import reject_workflow
        await reject_workflow(str(wf["_id"]), "user_001", reason="Needs revision")
        assert mock_wf.update_one.call_args[0][1]["$set"]["status"] == "cancelled"
        ct_payload = mock_ct.update_one.call_args[0][1]["$set"]
        assert ct_payload["status"] == "draft"
        assert ct_payload["workflow_stage"] == "request"

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_rejection_with_reason_saved(self, mock_wf, mock_ct):
        wf = make_workflow()
        mock_wf.find_one.side_effect = [wf, {**wf, "_id": wf["_id"]}]
        mock_wf.update_one.return_value = MagicMock()
        mock_ct.update_one.return_value = MagicMock()
        from app.services.workflow_service import reject_workflow
        await reject_workflow(str(wf["_id"]), "user_001", reason="Missing signature")
        assert mock_wf.update_one.call_args[0][1]["$set"]["steps"][0]["comments"] == "Missing signature"


class TestGetWorkflow:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_wf):
        from app.services.workflow_service import get_workflow
        assert await get_workflow("bad-id") is None
        mock_wf.find_one.assert_not_called()

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, mock_wf):
        mock_wf.find_one.return_value = None
        from app.services.workflow_service import get_workflow
        assert await get_workflow(str(ObjectId())) is None

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_found_returns_workflow(self, mock_wf):
        mock_wf.find_one.return_value = make_workflow()
        from app.services.workflow_service import get_workflow
        result = await get_workflow(str(ObjectId()))
        assert result is not None and "id" in result and "_id" not in result


class TestGetAllWorkflows:

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_admin_sees_all_workflows(self, mock_wf, mock_ct):
        mock_wf.find.return_value.sort.return_value = iter([make_workflow()])
        from app.services.workflow_service import get_all_workflows
        result = await get_all_workflows("admin_001", is_admin=True)
        assert "workflows" in result
        mock_ct.find.assert_not_called()

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_non_admin_no_contracts_returns_empty(self, mock_wf, mock_ct):
        mock_ct.find.return_value = iter([])
        from app.services.workflow_service import get_all_workflows
        result = await get_all_workflows("user_001", is_admin=False)
        assert result == {"workflows": [], "total": 0}
        mock_wf.find.assert_not_called()

    @patch("app.services.workflow_service.contracts_collection")
    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_non_admin_with_contracts_filters_workflows(self, mock_wf, mock_ct):
        contract_oid = ObjectId()
        mock_ct.find.return_value = iter([{"_id": contract_oid}])
        mock_wf.find.return_value.sort.return_value = iter([make_workflow(contract_id=str(contract_oid))])
        from app.services.workflow_service import get_all_workflows
        result = await get_all_workflows("user_001", is_admin=False)
        assert "workflows" in result
        mock_wf.find.assert_called_once()


class TestGetWorkflowsByContract:

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_returns_workflows_for_contract(self, mock_wf):
        mock_wf.find.return_value.sort.return_value = iter([make_workflow(), make_workflow()])
        from app.services.workflow_service import get_workflows_by_contract
        result = await get_workflows_by_contract("contract_abc")
        assert len(result) == 2
        for wf in result:
            assert "id" in wf and "_id" not in wf

    @patch("app.services.workflow_service.workflows_collection")
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_wf):
        mock_wf.find.return_value.sort.return_value = iter([])
        from app.services.workflow_service import get_workflows_by_contract
        assert await get_workflows_by_contract("contract_abc") == []