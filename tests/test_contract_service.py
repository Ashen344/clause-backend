import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import app.services.contract_service as contract_module


def make_contract(created_by="user_001", status="active", ai=None):
    return {
        "_id": ObjectId(),
        "title": "Test Contract",
        "contract_type": "nda",
        "status": status,
        "workflow_stage": "request",
        "start_date": datetime(2025, 1, 1),
        "end_date": datetime(2026, 1, 1),
        "value": 10000.0,
        "created_by": created_by,
        "ai_analysis": ai,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


class TestContractToResponse:

    def test_with_ai_analysis_flattens_risk_fields(self):
        """FR-ACA-01: Risk fields promotion"""
        result = contract_module.contract_to_response(
            make_contract(ai={"risk_score": 75.0, "risk_level": "high"})
        )
        assert result["risk_score"] == 75.0
        assert result["risk_level"] == "high"

    def test_without_ai_analysis_sets_none(self):
        result = contract_module.contract_to_response(make_contract(ai=None))
        assert result["risk_score"] is None
        assert result["risk_level"] is None


class TestGetContract:

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        """NFR-RB-06: Input validation"""
        assert await contract_module.get_contract("not-valid") is None

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_not_in_db_returns_none(self, mock_col):
        mock_col.find_one.return_value = None
        assert await contract_module.get_contract(str(ObjectId())) is None

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_can_access_any_contract(self, mock_col):
        """NFR-RB-01: Admin bypass ownership check"""
        contract = make_contract(created_by="other_user")
        mock_col.find_one.return_value = contract
        result = await contract_module.get_contract(
            str(contract["_id"]), user_id="admin_001", is_admin=True
        )
        assert result is not None

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_user_access_own_contract(self, mock_col):
        """NFR-RB-02: User can access own contract"""
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract
        result = await contract_module.get_contract(
            str(contract["_id"]), user_id="user_001", is_admin=False
        )
        assert result is not None

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_user_cannot_access_others_contract(self, mock_col):
        """NFR-RB-03: Access denied for other user's contract"""
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract
        result = await contract_module.get_contract(
            str(contract["_id"]), user_id="user_999", is_admin=False
        )
        assert result is None


class TestGetContracts:

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_non_admin_scoped_to_user(self, mock_col):
        """NFR-RB-04: User scope filtering"""
        from app.models.contract import ContractFilter
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await contract_module.get_contracts(
            ContractFilter(), user_id="u1", is_admin=False
        )
        
        assert mock_col.count_documents.call_args[0][0].get("created_by") == "u1"

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_sees_all_contracts(self, mock_col):
        """NFR-RB-05: Admin sees all"""
        from app.models.contract import ContractFilter
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await contract_module.get_contracts(
            ContractFilter(), user_id="admin_001", is_admin=True
        )
        
        assert "created_by" not in mock_col.count_documents.call_args[0][0]

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_search_filter_adds_regex(self, mock_col):
        """FR-CM-02: Text search"""
        from app.models.contract import ContractFilter
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await contract_module.get_contracts(
            ContractFilter(search="vendor"), user_id="u1", is_admin=True
        )
        
        query = mock_col.count_documents.call_args[0][0]
        assert "$regex" in str(query.get("title", {}))

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_status_filter_added(self, mock_col):
        """FR-CM-03: Status filtering"""
        from app.models.contract import ContractFilter, ContractStatus
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await contract_module.get_contracts(
            ContractFilter(status=ContractStatus.active), user_id="u1", is_admin=True
        )
        
        query = mock_col.count_documents.call_args[0][0]
        assert query.get("status") == "active"

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_date_range_filter(self, mock_col):
        """FR-CM-04: Date range filtering"""
        from app.models.contract import ContractFilter
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await contract_module.get_contracts(
            ContractFilter(
                start_date_from=datetime(2025, 1, 1),
                start_date_to=datetime(2025, 12, 31)
            ),
            user_id="u1",
            is_admin=True
        )
        
        query = mock_col.count_documents.call_args[0][0]
        assert "$gte" in query.get("start_date", {})


class TestGetDashboardStats:

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_returns_all_required_keys(self, mock_col):
        """FR-CM-05: Dashboard statistics"""
        mock_col.count_documents.return_value = 0
        result = await contract_module.get_dashboard_stats()
        assert "total_contracts" in result
        assert "active_contracts" in result
        assert "risk_summary" in result

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_counts_are_correct(self, mock_col):
        mock_col.count_documents.return_value = 5
        result = await contract_module.get_dashboard_stats()
        assert result["total_contracts"] == 5


class TestUpdateContract:

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        """NFR-RB-06: Input validation"""
        from app.models.contract import ContractUpdate
        assert await contract_module.update_contract("bad-id", ContractUpdate()) is None

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_empty_update_no_db_write(self, mock_col):
        """Edge case: Empty update"""
        from app.models.contract import ContractUpdate
        mock_col.find_one.return_value = make_contract()
        
        await contract_module.update_contract(str(ObjectId()), ContractUpdate())
        
        mock_col.update_one.assert_not_called()

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_update_with_fields(self, mock_col):
        """FR-CM-06: Contract update"""
        from app.models.contract import ContractUpdate
        mock_col.find_one.return_value = make_contract()
        mock_col.update_one.return_value = MagicMock()
        
        await contract_module.update_contract(
            str(ObjectId()), ContractUpdate(title="New Title")
        )
        
        mock_col.update_one.assert_called_once()


class TestDeleteContract:

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_false(self, mock_col):
        assert await contract_module.delete_contract("bad-id") is False

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_not_found_returns_false(self, mock_col):
        mock_col.delete_one.return_value = MagicMock(deleted_count=0)
        assert await contract_module.delete_contract(str(ObjectId())) is False

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_success_returns_true(self, mock_col):
        """FR-CM-07: Contract deletion"""
        mock_col.delete_one.return_value = MagicMock(deleted_count=1)
        assert await contract_module.delete_contract(str(ObjectId())) is True


class TestUpdateWorkflowStage:

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        assert await contract_module.update_workflow_stage("bad-id", "approval") is None

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_valid_id_updates_stage(self, mock_col):
        """FR-CM-08: Workflow stage update"""
        mock_col.find_one.return_value = make_contract()
        mock_col.update_one.return_value = MagicMock()
        
        await contract_module.update_workflow_stage(str(ObjectId()), "approval")
        
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["workflow_stage"] == "approval"

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_risk_level_filter(self, mock_col):
        """FR-CM-09: Risk level filtering"""
        from app.models.contract import ContractFilter, RiskLevel
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await contract_module.get_contracts(
            ContractFilter(risk_level=RiskLevel.high), user_id="u1", is_admin=True
        )
        
        query = mock_col.count_documents.call_args[0][0]
        assert query.get("ai_analysis.risk_level") == "high"

    @patch.object(contract_module, "contracts_collection")
    @pytest.mark.asyncio
    async def test_workflow_stage_filter(self, mock_col):
        """FR-CM-10: Workflow stage filtering"""
        from app.models.contract import ContractFilter, WorkflowStage
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await contract_module.get_contracts(
            ContractFilter(workflow_stage=WorkflowStage.approval), user_id="u1", is_admin=True
        )
        
        query = mock_col.count_documents.call_args[0][0]
        assert query.get("workflow_stage") == "approval"