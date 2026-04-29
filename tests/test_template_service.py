import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime

import app.services.template_service as tmpl_module


def make_template(name="NDA Template", is_active=True, version=1):
    return {
        "_id":           ObjectId(),
        "name":          name,
        "description":   "Standard NDA",
        "contract_type": "nda",
        "content":       "This agreement is between...",
        "fields":        [],
        "tags":          ["legal", "nda"],
        "version":       version,
        "is_active":     is_active,
        "created_by":    "user_001",
        "created_at":    datetime.utcnow(),
        "updated_at":    datetime.utcnow(),
    }


class TestTemplateToResponse:

    def test_converts_id_to_string(self):
        template = make_template()
        result = tmpl_module.template_to_response(template)
        assert "id"  in result
        assert "_id" not in result
        assert isinstance(result["id"], str)

    def test_other_fields_preserved(self):
        template = make_template(name="My Template", version=3)
        result = tmpl_module.template_to_response(template)
        assert result["name"]    == "My Template"
        assert result["version"] == 3


class TestGetTemplate:

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        """PATH P1 — Bad ObjectId → None. Branch: guard TRUE side"""
        result = await tmpl_module.get_template("not-valid-id!!!")
        assert result is None
        mock_col.find_one.assert_not_called()

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, mock_col):
        """PATH P2 — Valid id but missing. Branch: if not template TRUE"""
        mock_col.find_one.return_value = None
        result = await tmpl_module.get_template(str(ObjectId()))
        assert result is None

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_found_returns_template(self, mock_col):
        """PATH P3 — Valid id, found. Branch: if not template FALSE"""
        template = make_template()
        mock_col.find_one.return_value = template
        result = await tmpl_module.get_template(str(ObjectId()))
        assert result is not None
        assert "id"  in result
        assert "_id" not in result


class TestGetTemplates:

    def _setup_mock(self, mock_col, docs=None, total=0):
        if docs is None:
            docs = []
        mock_col.count_documents.return_value = total
        mock_col.find.return_value \
               .sort.return_value \
               .skip.return_value \
               .limit.return_value = iter(docs)

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_no_filters_base_query(self, mock_col):
        """PATH P1 — No filters → query only has is_active=True."""
        self._setup_mock(mock_col)
        await tmpl_module.get_templates()
        query = mock_col.count_documents.call_args[0][0]
        assert query == {"is_active": True}

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_contract_type_filter_added(self, mock_col):
        """PATH P2 — contract_type filter added. Branch: contract_type TRUE"""
        self._setup_mock(mock_col)
        await tmpl_module.get_templates(contract_type="nda")
        query = mock_col.count_documents.call_args[0][0]
        assert query["contract_type"] == "nda"

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_search_filter_adds_regex(self, mock_col):
        """PATH P3 — search adds regex. Branch: search TRUE"""
        self._setup_mock(mock_col)
        await tmpl_module.get_templates(search="vendor")
        query = mock_col.count_documents.call_args[0][0]
        assert "$regex" in query.get("name", {})
        assert query["name"]["$options"] == "i"

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_both_filters_combined(self, mock_col):
        """PATH P4 — Both filters. Branch: both TRUE"""
        self._setup_mock(mock_col)
        await tmpl_module.get_templates(contract_type="nda", search="vendor")
        query = mock_col.count_documents.call_args[0][0]
        assert query["contract_type"] == "nda"
        assert "$regex" in query.get("name", {})

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_empty_result_total_pages_zero(self, mock_col):
        """PATH P5 — total=0 → total_pages=0."""
        self._setup_mock(mock_col, total=0)
        result = await tmpl_module.get_templates()
        assert result["total"]       == 0
        assert result["total_pages"] == 0


class TestUpdateTemplate:

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        """PATH P1 — Bad ObjectId → None."""
        from app.models.template import TemplateUpdate
        result = await tmpl_module.update_template("bad-id", TemplateUpdate())
        assert result is None
        mock_col.update_one.assert_not_called()

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_empty_update_no_db_write(self, mock_col):
        """PATH P2 — No fields → no DB write. Branch: if not update_dict TRUE"""
        from app.models.template import TemplateUpdate
        template = make_template()
        mock_col.find_one.return_value = template
        await tmpl_module.update_template(str(ObjectId()), TemplateUpdate())
        mock_col.update_one.assert_not_called()

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_update_without_content_no_version_bump(self, mock_col):
        """PATH P3 — Name updated, no content → version unchanged."""
        from app.models.template import TemplateUpdate
        template = make_template(version=1)
        mock_col.find_one.return_value = template
        mock_col.update_one.return_value = MagicMock()
        await tmpl_module.update_template(str(ObjectId()), TemplateUpdate(name="New Name"))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "version"    not in payload
        assert "updated_at" in     payload

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_update_with_content_bumps_version(self, mock_col):
        """PATH P4 — Content changed → version incremented."""
        from app.models.template import TemplateUpdate
        template = make_template(version=2)
        mock_col.find_one.side_effect = [template, template]
        mock_col.update_one.return_value = MagicMock()
        await tmpl_module.update_template(str(ObjectId()), TemplateUpdate(content="New content"))
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["version"] == 3


class TestDeleteTemplate:

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_false(self, mock_col):
        """PATH P1 — Bad ObjectId → False."""
        result = await tmpl_module.delete_template("bad-id!!!")
        assert result is False
        mock_col.update_one.assert_not_called()

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_not_found_returns_false(self, mock_col):
        """PATH P2 — matched_count=0 → False."""
        mock_col.update_one.return_value = MagicMock(matched_count=0)
        result = await tmpl_module.delete_template(str(ObjectId()))
        assert result is False

    @patch.object(tmpl_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_soft_delete_sets_inactive(self, mock_col):
        """PATH P3 — matched_count=1 → True, is_active=False (soft delete)."""
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        result = await tmpl_module.delete_template(str(ObjectId()))
        assert result is True
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["is_active"] is False
        assert "updated_at"         in payload