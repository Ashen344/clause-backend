import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
from conftest import make_contract


# ══════════════════════════════════════════════════════════════════════
# contract_to_response()
# PATHS: P1 = ai_analysis present | P2 = ai_analysis absent
# ══════════════════════════════════════════════════════════════════════
class TestContractToResponse:

    def test_with_ai_analysis_flattens_risk_fields(self):
        """
        PATH P1 — ai_analysis dict exists.
        Branch: L21 TRUE side
        """
        from app.services.contract_service import contract_to_response
        contract = make_contract(ai={"risk_score": 75.0, "risk_level": "high"})
        result = contract_to_response(contract)

        assert result["risk_score"] == 75.0
        assert result["risk_level"] == "high"
        assert "id"  in result
        assert "_id" not in result

    def test_without_ai_analysis_sets_none(self):
        """
        PATH P2 — ai_analysis is None.
        Branch: L21 FALSE side
        """
        from app.services.contract_service import contract_to_response
        contract = make_contract(ai=None)
        result = contract_to_response(contract)

        assert result["risk_score"] is None
        assert result["risk_level"] is None


# ══════════════════════════════════════════════════════════════════════
# get_contract()
# PATHS: P1=invalid id | P2=not found | P3=admin | P4=own | P5=denied
# ══════════════════════════════════════════════════════════════════════
class TestGetContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        """PATH P1 — Bad ObjectId. Branch: L51 TRUE side"""
        from app.services.contract_service import get_contract
        result = await get_contract("not-valid")
        assert result is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_not_in_db_returns_none(self, mock_col):
        """PATH P2 — Valid id, contract missing. Branch: L56 TRUE side"""
        mock_col.find_one.return_value = None

        from app.services.contract_service import get_contract
        result = await get_contract(str(ObjectId()))
        assert result is None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_can_access_any_contract(self, mock_col):
        """PATH P3 — Admin bypasses ownership. Branch: L60 FALSE (is_admin=True)"""
        contract = make_contract(created_by="other_user")
        mock_col.find_one.return_value = contract

        from app.services.contract_service import get_contract
        result = await get_contract(
            str(contract["_id"]), user_id="admin_001", is_admin=True
        )
        assert result is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_user_access_own_contract(self, mock_col):
        """PATH P4 — User views own contract. Branch: L60 FALSE (ids match)"""
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract

        from app.services.contract_service import get_contract
        result = await get_contract(
            str(contract["_id"]), user_id="user_001", is_admin=False
        )
        assert result is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_user_cannot_access_others_contract(self, mock_col):
        """PATH P5 — Access denied. Branch: L60 TRUE side"""
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract

        from app.services.contract_service import get_contract
        result = await get_contract(
            str(contract["_id"]), user_id="user_999", is_admin=False
        )
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# get_contracts()
# PATHS: various filter combinations
# ══════════════════════════════════════════════════════════════════════
class TestGetContracts:

    def _setup_mock(self, mock_col, docs=None, total=0):
        if docs is None:
            docs = []
        mock_col.count_documents.return_value = total
        mock_col.find.return_value \
               .sort.return_value \
               .skip.return_value \
               .limit.return_value = iter(docs)

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_non_admin_scoped_to_user(self, mock_col):
        """Branch: not is_admin AND user_id TRUE — query includes created_by."""
        self._setup_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter

        await get_contracts(ContractFilter(), user_id="u1", is_admin=False)

        query = mock_col.count_documents.call_args[0][0]
        assert query.get("created_by") == "u1"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_sees_all_contracts(self, mock_col):
        """Branch: is_admin TRUE — no created_by filter."""
        self._setup_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter

        await get_contracts(ContractFilter(), user_id="admin_001", is_admin=True)

        query = mock_col.count_documents.call_args[0][0]
        assert "created_by" not in query

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_search_filter_adds_regex(self, mock_col):
        """Branch: filters.search TRUE — regex added on title field."""
        self._setup_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter

        await get_contracts(ContractFilter(search="vendor"), user_id=None, is_admin=True)

        query = mock_col.count_documents.call_args[0][0]
        assert "$regex"   in query.get("title", {})
        assert "$options" in query.get("title", {})

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_status_filter_added(self, mock_col):
        """Branch: filters.status TRUE side."""
        self._setup_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter, ContractStatus

        await get_contracts(
            ContractFilter(status=ContractStatus.active),
            user_id=None, is_admin=True
        )

        query = mock_col.count_documents.call_args[0][0]
        assert query.get("status") == "active"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_date_range_filter(self, mock_col):
        """Branch: start_date_from TRUE, start_date_to TRUE."""
        self._setup_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter

        d1 = datetime(2025, 1, 1)
        d2 = datetime(2025, 12, 31)
        await get_contracts(
            ContractFilter(start_date_from=d1, start_date_to=d2),
            user_id=None, is_admin=True
        )

        query = mock_col.count_documents.call_args[0][0]
        assert "$gte" in query.get("start_date", {})
        assert "$lte" in query.get("start_date", {})

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_empty_result_returns_correct_structure(self, mock_col):
        """Response dict must have all required keys."""
        self._setup_mock(mock_col, total=0)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter

        result = await get_contracts(ContractFilter(), user_id=None, is_admin=True)

        for key in ["contracts", "total", "page", "per_page", "total_pages"]:
            assert key in result


# ══════════════════════════════════════════════════════════════════════
# get_dashboard_stats()
# ══════════════════════════════════════════════════════════════════════
class TestGetDashboardStats:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_returns_all_required_keys(self, mock_col):
        """Dashboard stats must return all expected keys."""
        mock_col.count_documents.return_value = 0

        from app.services.contract_service import get_dashboard_stats
        result = await get_dashboard_stats()

        assert "total_contracts"   in result
        assert "active_contracts"  in result
        assert "draft_contracts"   in result
        assert "expired_contracts" in result
        assert "expiring_soon"     in result
        assert "risk_summary"      in result

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_counts_are_correct(self, mock_col):
        """count_documents called for each status, returns correct values."""
        mock_col.count_documents.return_value = 5

        from app.services.contract_service import get_dashboard_stats
        result = await get_dashboard_stats()

        assert result["total_contracts"]        == 5
        assert result["active_contracts"]       == 5
        assert result["risk_summary"]["high"]   == 5
        assert result["risk_summary"]["medium"] == 5
        assert result["risk_summary"]["low"]    == 5


# ══════════════════════════════════════════════════════════════════════
# update_contract()
# PATHS: P1=invalid id | P2=empty update | P3=fields updated
# ══════════════════════════════════════════════════════════════════════
class TestUpdateContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        """PATH P1 — Bad ObjectId. Branch: L131 TRUE side"""
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        result = await update_contract("bad-id", ContractUpdate())

        assert result is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_empty_update_no_db_write(self, mock_col):
        """PATH P2 — No fields set. Branch: L139 TRUE side"""
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        mock_col.find_one.return_value = make_contract()

        await update_contract(str(ObjectId()), ContractUpdate())

        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_update_with_fields(self, mock_col):
        """PATH P3 — Fields provided. Branch: L139 FALSE side"""
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        mock_col.find_one.return_value = make_contract()
        mock_col.update_one.return_value = MagicMock()

        await update_contract(str(ObjectId()), ContractUpdate(title="New Title"))

        mock_col.update_one.assert_called_once()
        payload = mock_col.update_one.call_args[0][1]
        assert "updated_at" in payload["$set"]


# ══════════════════════════════════════════════════════════════════════
# delete_contract()
# PATHS: P1=invalid id | P2=not found | P3=deleted
# ══════════════════════════════════════════════════════════════════════
class TestDeleteContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_false(self, mock_col):
        """PATH P1 — Bad ObjectId. Branch: L156 TRUE side"""
        from app.services.contract_service import delete_contract
        result = await delete_contract("bad-id")

        assert result is False
        mock_col.delete_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_not_found_returns_false(self, mock_col):
        """PATH P2 — deleted_count=0. Branch: L162 FALSE side"""
        mock_col.delete_one.return_value = MagicMock(deleted_count=0)

        from app.services.contract_service import delete_contract
        result = await delete_contract(str(ObjectId()))
        assert result is False

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_success_returns_true(self, mock_col):
        """PATH P3 — deleted_count=1. Branch: L162 TRUE side"""
        mock_col.delete_one.return_value = MagicMock(deleted_count=1)

        from app.services.contract_service import delete_contract
        result = await delete_contract(str(ObjectId()))
        assert result is True


# ══════════════════════════════════════════════════════════════════════
# update_workflow_stage()
# PATHS: P1=invalid id | P2=valid id updated
# ══════════════════════════════════════════════════════════════════════
class TestUpdateWorkflowStage:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        """
        PATH P1 — Bad ObjectId → None.
        Branch: guard TRUE side
        """
        from app.services.contract_service import update_workflow_stage
        result = await update_workflow_stage("bad-id", "approval")
        assert result is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_valid_id_updates_stage(self, mock_col):
        """
        PATH P2 — Valid ObjectId → stage updated in DB.
        Branch: guard FALSE side
        """
        from app.services.contract_service import update_workflow_stage
        contract = make_contract()
        mock_col.find_one.return_value = contract
        mock_col.update_one.return_value = MagicMock()

        await update_workflow_stage(str(ObjectId()), "approval")

        mock_col.update_one.assert_called_once()
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["workflow_stage"] == "approval"
        assert "updated_at" in payload