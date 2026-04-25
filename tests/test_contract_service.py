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
        Expects: risk_score and risk_level promoted to top level.
        Statement: L16, L17, L21(T), L22, L23, L28
        Branch:    L21 TRUE side
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
        Expects: risk_score and risk_level both set to None.
        Statement: L16, L17, L21(F), L25, L26, L28
        Branch:    L21 FALSE side
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
        """
        PATH P1 — Bad ObjectId string.
        Expects: None returned, DB never queried.
        Statement: L51(T), L52
        Branch:    L51 TRUE side
        """
        from app.services.contract_service import get_contract
        result = await get_contract("not-valid")

        assert result is None
        mock_col.find_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_not_in_db_returns_none(self, mock_col):
        """
        PATH P2 — Valid id but contract missing from DB.
        Statement: L51(F), L54, L56(T), L57
        Branch:    L56 TRUE side
        """
        mock_col.find_one.return_value = None

        from app.services.contract_service import get_contract
        result = await get_contract(str(ObjectId()))

        assert result is None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_admin_can_access_any_contract(self, mock_col):
        """
        PATH P3 — is_admin=True bypasses ownership check.
        Expects: contract returned even though created_by != user_id.
        Statement: L51(F), L54, L56(F), L60(F), L63
        Branch:    L60 FALSE (because is_admin=True)
        """
        contract = make_contract(created_by="other_user")
        mock_col.find_one.return_value = contract

        from app.services.contract_service import get_contract
        result = await get_contract(
            str(contract["_id"]),
            user_id="admin_001",
            is_admin=True
        )
        assert result is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_user_access_own_contract(self, mock_col):
        """
        PATH P4 — user_id matches created_by.
        Expects: contract returned.
        Statement: L51(F), L54, L56(F), L60(F), L63
        Branch:    L60 FALSE (because ids match)
        """
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract

        from app.services.contract_service import get_contract
        result = await get_contract(
            str(contract["_id"]),
            user_id="user_001",
            is_admin=False
        )
        assert result is not None

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_user_cannot_access_others_contract(self, mock_col):
        """
        PATH P5 — user_id does NOT match created_by, not admin.
        Expects: None returned (access denied).
        Statement: L51(F), L54, L56(F), L60(T), L61
        Branch:    L60 TRUE side
        """
        contract = make_contract(created_by="user_001")
        mock_col.find_one.return_value = contract

        from app.services.contract_service import get_contract
        result = await get_contract(
            str(contract["_id"]),
            user_id="user_999",
            is_admin=False
        )
        assert result is None


# ══════════════════════════════════════════════════════════════════════
# update_contract()
# PATHS: P1=invalid id | P2=empty update | P3=fields updated
# ══════════════════════════════════════════════════════════════════════
class TestUpdateContract:

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid(self, mock_col):
        """
        PATH P1 — Bad ObjectId.
        Statement: L131(T), L132
        Branch:    L131 TRUE side
        """
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        result = await update_contract("bad-id", ContractUpdate())

        assert result is None
        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_empty_update_no_db_write(self, mock_col):
        """
        PATH P2 — Valid id but ContractUpdate() has no fields set.
        Expects: update_one never called (early exit at L140).
        Statement: L131(F), L136, L139(T), L140
        Branch:    L139 TRUE side
        """
        from app.services.contract_service import update_contract
        from app.models.contract import ContractUpdate
        mock_col.find_one.return_value = make_contract()

        await update_contract(str(ObjectId()), ContractUpdate())

        mock_col.update_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_update_with_fields(self, mock_col):
        """
        PATH P3 — Fields provided, DB gets updated.
        Expects: update_one called, updated_at injected.
        Statement: L131(F), L136, L139(F), L143, L146, L151
        Branch:    L139 FALSE side
        """
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
        """
        PATH P1 — Bad ObjectId.
        Statement: L156(T), L157
        Branch:    L156 TRUE side
        """
        from app.services.contract_service import delete_contract
        result = await delete_contract("bad-id")

        assert result is False
        mock_col.delete_one.assert_not_called()

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_not_found_returns_false(self, mock_col):
        """
        PATH P2 — Valid id but deleted_count=0.
        Statement: L156(F), L159, L162(False)
        Branch:    L162 FALSE side
        """
        mock_col.delete_one.return_value = MagicMock(deleted_count=0)

        from app.services.contract_service import delete_contract
        result = await delete_contract(str(ObjectId()))

        assert result is False

    @patch("app.services.contract_service.contracts_collection")
    @pytest.mark.asyncio
    async def test_delete_success_returns_true(self, mock_col):
        """
        PATH P3 — Valid id, deleted_count=1.
        Statement: L156(F), L159, L162(True)
        Branch:    L162 TRUE side
        """
        mock_col.delete_one.return_value = MagicMock(deleted_count=1)

        from app.services.contract_service import delete_contract
        result = await delete_contract(str(ObjectId()))

        assert result is True