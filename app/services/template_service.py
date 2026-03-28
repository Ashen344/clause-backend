from bson import ObjectId
from datetime import datetime
from typing import Optional
from app.config import templates_collection
from app.models.template import TemplateCreate, TemplateUpdate, TemplateInDB


def template_to_response(template: dict) -> dict:
    template["id"] = str(template["_id"])
    del template["_id"]
    return template


async def create_template(template_data: TemplateCreate, user_id: str) -> dict:
    template_dict = TemplateInDB(
        **template_data.model_dump(),
        created_by=user_id,
    ).model_dump()

    result = templates_collection.insert_one(template_dict)
    created = templates_collection.find_one({"_id": result.inserted_id})
    return template_to_response(created)


async def get_template(template_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(template_id):
        return None
    template = templates_collection.find_one({"_id": ObjectId(template_id)})
    if not template:
        return None
    return template_to_response(template)


async def get_templates(
    contract_type: str = None,
    search: str = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    query = {"is_active": True}

    if contract_type:
        query["contract_type"] = contract_type

    if search:
        query["name"] = {"$regex": search, "$options": "i"}

    skip = (page - 1) * per_page
    total = templates_collection.count_documents(query)

    templates_cursor = (
        templates_collection
        .find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(per_page)
    )

    templates = [template_to_response(t) for t in templates_cursor]

    return {
        "templates": templates,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


async def update_template(template_id: str, update_data: TemplateUpdate) -> Optional[dict]:
    if not ObjectId.is_valid(template_id):
        return None

    update_dict = update_data.model_dump(exclude_unset=True)
    if not update_dict:
        return await get_template(template_id)

    update_dict["updated_at"] = datetime.utcnow()

    # Increment version if content changed
    if "content" in update_dict:
        template = templates_collection.find_one({"_id": ObjectId(template_id)})
        if template:
            update_dict["version"] = template.get("version", 1) + 1

    templates_collection.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": update_dict}
    )

    return await get_template(template_id)


async def delete_template(template_id: str) -> bool:
    if not ObjectId.is_valid(template_id):
        return False
    # Soft delete - just deactivate
    result = templates_collection.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
    )
    return result.matched_count > 0
