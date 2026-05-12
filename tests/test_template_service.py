import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime
import app.services.template_service as template_module


def make_template(name="My Template", version=1):
    return {
        "_id": ObjectId(),
        "name": name,
        "contract_type": "nda",
        "content": "Template content here",
        "version": version,
        "is_active": True,
        "created_by": "user_001",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


class TestTemplateToResponse:

    def test_converts_id_to_string(self):
        """TC-TMP-01: ID conversion"""
        result = template_module.template_to_response(make_template())
        assert "id" in result
        assert "_id" not in result

    def test_other_fields_preserved(self):
        result = template_module.template_to_response(make_template(name="Custom Template", version=3))
        assert result["name"] == "Custom Template"
        assert result["version"] == 3


class TestGetTemplate:

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        """TC-TMP-03: Input validation"""
        assert await template_module.get_template("not-valid-id!!!") is None

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, mock_col):
        mock_col.find_one.return_value = None
        assert await template_module.get_template(str(ObjectId())) is None

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_found_returns_template(self, mock_col):
        """TC-TMP-05: Get template by ID"""
        mock_col.find_one.return_value = make_template()
        result = await template_module.get_template(str(ObjectId()))
        assert result is not None
        assert "id" in result


class TestGetTemplates:

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_no_filters_base_query(self, mock_col):
        """TC-TMP-06: List active templates"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await template_module.get_templates()
        
        query = mock_col.count_documents.call_args[0][0]
        assert query == {"is_active": True}

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_contract_type_filter_added(self, mock_col):
        """TC-TMP-07: Filter by contract type"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await template_module.get_templates(contract_type="nda")
        
        query = mock_col.count_documents.call_args[0][0]
        assert query["contract_type"] == "nda"

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_search_filter_adds_regex(self, mock_col):
        """TC-TMP-08: Search templates"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await template_module.get_templates(search="vendor")
        
        query = mock_col.count_documents.call_args[0][0]
        assert "$regex" in str(query.get("name", {}))

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_both_filters_combined(self, mock_col):
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        await template_module.get_templates(contract_type="nda", search="vendor")
        
        query = mock_col.count_documents.call_args[0][0]
        assert query["contract_type"] == "nda"
        assert "name" in query

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_empty_result_total_pages_zero(self, mock_col):
        """TC-TMP-10: Edge case: Empty result"""
        mock_col.count_documents.return_value = 0
        mock_col.find.return_value.sort.return_value.skip.return_value.limit.return_value = iter([])
        
        result = await template_module.get_templates()
        assert result["total_pages"] == 0


class TestUpdateTemplate:

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_none(self, mock_col):
        """TC-TMP-11: Input validation"""
        from app.models.template import TemplateUpdate
        assert await template_module.update_template("bad-id", TemplateUpdate()) is None

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_empty_update_no_db_write(self, mock_col):
        """TC-TMP-12: Edge case: Empty update"""
        from app.models.template import TemplateUpdate
        mock_col.find_one.return_value = make_template()
        
        await template_module.update_template(str(ObjectId()), TemplateUpdate())
        
        mock_col.update_one.assert_not_called()

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_update_without_content_no_version_bump(self, mock_col):
        """TC-TMP-13: Update without content change"""
        from app.models.template import TemplateUpdate
        mock_col.find_one.return_value = make_template(version=2)
        mock_col.update_one.return_value = MagicMock()
        
        await template_module.update_template(str(ObjectId()), TemplateUpdate(name="New Name"))
        
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert "version" not in payload

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_update_with_content_bumps_version(self, mock_col):
        """TC-TMP-14: Version bump on content change"""
        from app.models.template import TemplateUpdate
        mock_col.find_one.side_effect = [make_template(version=2), make_template(version=3)]
        mock_col.update_one.return_value = MagicMock()
        
        await template_module.update_template(str(ObjectId()), TemplateUpdate(content="New content"))
        
        payload = mock_col.update_one.call_args[0][1]["$set"]
        assert payload["version"] == 3


class TestDeleteTemplate:

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_invalid_objectid_returns_false(self, mock_col):
        assert await template_module.delete_template("bad-id!!!") is False

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_soft_delete_sets_inactive(self, mock_col):
        """TC-TMP-16: Soft delete template"""
        mock_col.update_one.return_value = MagicMock(matched_count=1)
        result = await template_module.delete_template(str(ObjectId()))
        assert result is True

class TestCreateTemplate:

    @patch.object(template_module, "templates_collection")
    @pytest.mark.asyncio
    async def test_template_created_successfully(self, mock_col):
        """TC-TMP-17: Create template"""
        from app.models.template import TemplateCreate
        mock_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        mock_col.find_one.return_value = make_template()
        
        result = await template_module.create_template(
            TemplateCreate(
                name="Test Template",
                contract_type="nda",
                content="Template content"
            ),
            user_id="user_001"
        )
        
        assert result is not None
        assert "id" in result