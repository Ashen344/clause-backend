"""
test_contract_service.py
Complete white-box + requirements test suite for contract_service.py
FR-CM-01, FR-CC-02–06, FR-CM-02/03/05/06/07/08, FR-CAS-01/02, FR-DR-02, FR-RSA-01, FR-WP-04
NFR-RB-06, NFR-SC-04
"""

import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime


def make_contract(created_by="user_001", status="active", tags=None, ai=None, version=1):
    return {
        "_id":            ObjectId(),
        "title":          "Test Contract",
        "contract_type":  "nda",
        "description":    "A test NDA",
        "status":         status,
        "workflow_stage": "request",
        "start_date":     datetime(2025, 1, 1),
        "end_date":       datetime(2026, 1, 1),
        "value":          10000.0,
        "payment_terms":  "Net 30",
        "parties":        [{"name": "Acme", "role": "client"}],
        "tags":           tags or [],
        "version":        version,
        "created_by":     created_by,
        "shared_with":    [],
        "ai_analysis":    ai,
        "created_at":     datetime.utcnow(),
        "updated_at":     datetime.utcnow(),
    }


def setup_list_mock(mock_col, docs=None, total=0):
    if docs is None:
        docs = []
    mock_col.count_documents.return_value = total
    mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter(docs)


class TestContractToResponse:

    def test_with_ai_analysis_flattens_risk_fields(self):
        from app.services.contract_service import contract_to_response
        result = contract_to_response(make_contract(ai={"risk_score": 75.0, "risk_level": "high"}))
        assert result["risk_score"] == 75.0
        assert result["risk_level"] == "high"
        assert "id" in result and "_id" not in result

    def test_without_ai_analysis_sets_none(self):
        from app.services.contract_service import contract_to_response
        result = contract_to_response(make_contract(ai=None))
        assert result["risk_score"] is None
        assert result["risk_level"] is None


class TestCreateContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_create_calls_insert_one(self, mock_col):
        from app.services.contract_service import create_contract
        from app.models.contract import ContractCreate
        new_doc = make_contract(status="draft")
        mock_col.insert_one.return_value = MagicMock(inserted_id=new_doc["_id"])
        mock_col.find_one.return_value = new_doc
        result = await create_contract(ContractCreate(title="NDA", contract_type="nda", start_date=datetime(2025,1,1), end_date=datetime(2026,1,1)), user_id="user_001")
        mock_col.insert_one.assert_called_once()
        assert result is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_new_contract_stored_with_created_by(self, mock_col):
        from app.services.contract_service import create_contract
        from app.models.contract import ContractCreate
        new_doc = make_contract(created_by="user_abc")
        mock_col.insert_one.return_value = MagicMock(inserted_id=new_doc["_id"])
        mock_col.find_one.return_value = new_doc
        await create_contract(ContractCreate(title="NDA", contract_type="nda", start_date=datetime(2025,1,1), end_date=datetime(2026,1,1)), user_id="user_abc")
        assert mock_col.insert_one.call_args[0][0]["created_by"] == "user_abc"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_new_contract_default_status_is_draft(self, mock_col):
        from app.services.contract_service import create_contract
        from app.models.contract import ContractCreate
        new_doc = make_contract(status="draft")
        mock_col.insert_one.return_value = MagicMock(inserted_id=new_doc["_id"])
        mock_col.find_one.return_value = new_doc
        await create_contract(ContractCreate(title="NDA", contract_type="nda", start_date=datetime(2025,1,1), end_date=datetime(2026,1,1)), user_id="user_001")
        assert mock_col.insert_one.call_args[0][0]["status"] == "draft"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_new_contract_has_created_at(self, mock_col):
        from app.services.contract_service import create_contract
        from app.models.contract import ContractCreate
        new_doc = make_contract()
        mock_col.insert_one.return_value = MagicMock(inserted_id=new_doc["_id"])
        mock_col.find_one.return_value = new_doc
        await create_contract(ContractCreate(title="NDA", contract_type="nda", start_date=datetime(2025,1,1), end_date=datetime(2026,1,1)), user_id="user_001")
        doc = mock_col.insert_one.call_args[0][0]
        assert "created_at" in doc and isinstance(doc["created_at"], datetime)


class TestGetContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        from app.services.contract_service import get_contract
        assert await get_contract("not-valid") is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_not_in_db_returns_none(self, mock_col):
        mock_col.find_one.return_value = None
        from app.services.contract_service import get_contract
        assert await get_contract(str(ObjectId())) is None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_can_access_any_contract(self, mock_col):
        contract = make_contract(created_by="other_user")
        mock_col.find_one.return_value = contract
        from app.services.contract_service import get_contract
        assert await get_contract(str(contract["_id"]), user_id="admin_001", is_admin=True) is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_user_access_own_contract(self, mock_col):
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract
        from app.services.contract_service import get_contract
        assert await get_contract(str(contract["_id"]), user_id="user_001", is_admin=False) is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_user_cannot_access_others_contract(self, mock_col):
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract
        from app.services.contract_service import get_contract
        assert await get_contract(str(contract["_id"]), user_id="user_999", is_admin=False) is None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_shared_user_can_access_contract(self, mock_col):
        contract = make_contract(created_by="user_001")
        contract["shared_with"] = ["user_002"]
        mock_col.find_one.return_value = contract
        from app.services.contract_service import get_contract
        assert await get_contract(str(contract["_id"]), user_id="user_002", is_admin=False) is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_empty_string_id_rejected(self, mock_col):
        from app.services.contract_service import get_contract
        assert await get_contract("") is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_sql_injection_rejected(self, mock_col):
        from app.services.contract_service import get_contract
        assert await get_contract("' OR '1'='1") is None
        mock_col.find_one.assert_not_called()


class TestGetContracts:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_non_admin_scoped_to_user(self, mock_col):
        setup_list_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter
        await get_contracts(ContractFilter(), user_id="u1", is_admin=False)
        assert mock_col.count_documents.call_args[0][0].get("created_by") == "u1"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_sees_all_contracts(self, mock_col):
        setup_list_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter
        await get_contracts(ContractFilter(), user_id="admin_001", is_admin=True)
        assert "created_by" not in mock_col.count_documents.call_args[0][0]

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_search_filter_adds_regex(self, mock_col):
        setup_list_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter
        await get_contracts(ContractFilter(search="vendor"), user_id=None, is_admin=True)
        assert "$regex" in mock_col.count_documents.call_args[0][0].get("title", {})

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_status_filter_added(self, mock_col):
        setup_list_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter, ContractStatus
        await get_contracts(ContractFilter(status=ContractStatus.active), user_id=None, is_admin=True)
        assert mock_col.count_documents.call_args[0][0].get("status") == "active"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_date_range_filter(self, mock_col):
        setup_list_mock(mock_col)
        from app.services.contract_service import get_contracts
        from app.models.contract import ContractFilter
        await get_contracts(ContractFilter(start_date_from=datetime(2025,1,1), start_date_to=datetime(2025,12,31)), user_id=None, is_admin=True)
        sd = mock_col.count_documents.call_args[0][0].get("start_date", {})
        assert "$gte" in sd and "$lte" in sd


class TestGetDashboardStats:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_returns_all_required_keys(self, mock_col):
        mock_col.count_documents.return_value = 0
        from app.services.contract_service import get_dashboard_stats
        result = await get_dashboard_stats()
        for key in ["total_contracts", "active_contracts", "draft_contracts", "expired_contracts", "expiring_soon", "risk_summary"]:
            assert key in result

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_counts_are_correct(self, mock_col):
        mock_col.count_documents.return_value = 5
        from app.services.contract_service import get_dashboard_stats
        result = await get_dashboard_stats()
        assert result["total_contracts"] == 5
        assert result["risk_summary"]["high"] == 5


class TestUpdateContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        assert await update_contract("bad-id", ContractUpdate()) is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_empty_update_no_db_write(self, mock_col):
        mock_col.find_one.return_value = make_contract()
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        await update_contract(str(ObjectId()), ContractUpdate())
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_update_with_fields(self, mock_col):
        mock_col.find_one.return_value = make_contract()
        mock_col.update_one.return_value = MagicMock()
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        await update_contract(str(ObjectId()), ContractUpdate(title="New Title"))
        mock_col.update_one.assert_called_once()
        assert "updated_at" in mock_col.update_one.call_args[0][1]["$set"]

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_tags_update_stored(self, mock_col):
        mock_col.find_one.return_value = make_contract()
        mock_col.update_one.return_value = MagicMock()
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        await update_contract(str(ObjectId()), ContractUpdate(tags=["legal", "nda"]))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "legal" in payload.get("tags", [])


class TestDeleteContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_false(self, mock_col):
        from app.services.contract_service import delete_contract
        assert await delete_contract("bad-id") is False
        mock_col.delete_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_not_found_returns_false(self, mock_col):
        mock_col.delete_one.return_value = MagicMock(deleted_count=0)
        from app.services.contract_service import delete_contract
        assert await delete_contract(str(ObjectId())) is False

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_success_returns_true(self, mock_col):
        mock_col.delete_one.return_value = MagicMock(deleted_count=1)
        from app.services.contract_service import delete_contract
        assert await delete_contract(str(ObjectId())) is True


class TestUpdateWorkflowStage:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        from app.services.contract_service import update_workflow_stage
        assert await update_workflow_stage("bad-id", "approval") is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_valid_id_updates_stage(self, mock_col):
        mock_col.find_one.return_value = make_contract()
        mock_col.update_one.return_value = MagicMock()
        from app.services.contract_service import update_workflow_stage
        await update_workflow_stage(str(ObjectId()), "approval")
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["workflow_stage"] == "approval"
        assert "updated_at" in payload


class TestArchiveRestoreContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_archive_sets_status_archived(self, mock_col):
        from app.services.contract_service import archive_contract
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_contract(status="archived")
        await archive_contract(str(ObjectId()), user_id="user_001")
        assert mock_col.update_one.call_args[0][1]["$set"]["status"] == "archived"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_restore_sets_status_draft(self, mock_col):
        from app.services.contract_service import restore_contract
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        mock_col.find_one.return_value = make_contract(status="draft")
        await restore_contract(str(ObjectId()), user_id="user_001")
        assert mock_col.update_one.call_args[0][1]["$set"]["status"] == "draft"

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_archive_invalid_objectid_returns_none(self, mock_col):
        from app.services.contract_service import archive_contract
        assert await archive_contract("bad-id", user_id="user_001") is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_archive_not_found_returns_none(self, mock_col):
        from app.services.contract_service import archive_contract
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        assert await archive_contract(str(ObjectId()), user_id="user_001") is None


class TestContractSharing:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_owner_can_share_contract(self, mock_col):
        from app.services.contract_service import share_contract
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        await share_contract(str(contract["_id"]), owner_id="user_001", share_with_user_id="user_002")
        mock_col.update_one.assert_called_once()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_non_owner_cannot_share(self, mock_col):
        from app.services.contract_service import share_contract
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract
        result = await share_contract(str(contract["_id"]), owner_id="user_999", share_with_user_id="user_002", is_admin=False)
        assert result is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_can_share_any_contract(self, mock_col):
        from app.services.contract_service import share_contract
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        await share_contract(str(contract["_id"]), owner_id="admin_001", share_with_user_id="user_002", is_admin=True)
        mock_col.update_one.assert_called_once()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_share_invalid_objectid_returns_none(self, mock_col):
        from app.services.contract_service import share_contract
        assert await share_contract("bad-id", owner_id="user_001", share_with_user_id="user_002") is None
        mock_col.update_one.assert_not_called()