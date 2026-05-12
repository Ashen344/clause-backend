from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional
from app.config import contracts_collection, users_collection, workflows_collection
from app.models.contract import (
    ContractCreate,
    ContractInDB,
    ContractUpdate,
    ContractFilter,
)


# Convert MongoDB's _id (ObjectId) to a string
# MongoDB stores IDs as ObjectId objects, but our API returns strings
def contract_to_response(contract: dict) -> dict:
    contract["id"] = str(contract["_id"])
    del contract["_id"]

    # Resolve created_by (clerk_id) → human-readable name/email
    stored = contract.get("created_by_name", "")
    if not stored or stored.startswith("user_"):
        clerk_id = contract.get("created_by")
        if clerk_id:
            user = users_collection.find_one({"clerk_id": clerk_id}, {"full_name": 1, "email": 1})
            contract["created_by_name"] = (
                user.get("email") or user.get("full_name") if user else None
            ) or clerk_id
        else:
            contract["created_by_name"] = None

    # Auto-derive workflow_rejected from live workflow if not already stored on the contract
    if not contract.get("workflow_rejected") and contract.get("workflow_id"):
        wf_id = contract["workflow_id"]
        if ObjectId.is_valid(wf_id):
            wf = workflows_collection.find_one(
                {"_id": ObjectId(wf_id)},
                {"status": 1, "current_step": 1, "steps": 1},
            )
            if wf and wf.get("status") == "cancelled":
                steps = wf.get("steps", [])
                rejected_step = next(
                    (s for s in steps if s.get("status") == "rejected"), None
                )
                step_num = (
                    rejected_step.get("step_number", wf.get("current_step", 1))
                    if rejected_step
                    else wf.get("current_step", 1)
                )
                stage_map = {
                    1: "request", 2: "authoring", 3: "review", 4: "review",
                    5: "approval", 6: "execution", 7: "storage",
                    8: "monitoring", 9: "renewal",
                }
                contract["workflow_rejected"] = True
                contract["workflow_stage"] = stage_map.get(step_num, "request")
                contract["workflow_current_step"] = step_num
                if not contract.get("workflow_total_steps"):
                    contract["workflow_total_steps"] = len(steps)
                if not contract.get("workflow_step_names"):
                    contract["workflow_step_names"] = [
                        s.get("name") or "Step {}".format(i + 1)
                        for i, s in enumerate(steps)
                    ]

    # Pull risk info from nested ai_analysis into top-level fields
    if contract.get("ai_analysis"):
        contract["risk_score"] = contract["ai_analysis"].get("risk_score")
        contract["risk_level"] = contract["ai_analysis"].get("risk_level")
    else:
        contract["risk_score"] = None
        contract["risk_level"] = None

    return contract


# CREATE a new contract
async def create_contract(contract_data: ContractCreate, user_id: str, created_by_name: str = None) -> dict:
    contract_dict = ContractInDB(
        **contract_data.model_dump(),
        created_by=user_id,
    ).model_dump()
    if created_by_name:
        contract_dict["created_by_name"] = created_by_name

    # Insert into MongoDB - this returns an object with the new document's ID
    result = contracts_collection.insert_one(contract_dict)

    # Fetch the newly created document back so we can return it
    created_contract = contracts_collection.find_one({"_id": result.inserted_id})

    return contract_to_response(created_contract)


# GET a single contract by its ID
async def get_contract(contract_id: str, user_id: str = None, is_admin: bool = False) -> Optional[dict]:
    if not ObjectId.is_valid(contract_id):
        return None

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})

    if not contract:
        return None

    # Non-admins can only access contracts they created
    if not is_admin and user_id and contract.get("created_by") != user_id:
        return None

    return contract_to_response(contract)


# GET all contracts with filtering, searching, and pagination
async def get_contracts(filters: ContractFilter, user_id: str = None, is_admin: bool = False, view: str = "active") -> dict:
    # Build the MongoDB query dynamically based on what filters were provided
    query = {}

    # Scope by view
    if view == "archived":
        query["is_archived"] = True
        query["is_deleted"] = {"$ne": True}
    elif view == "trash":
        query["is_deleted"] = True
    else:
        # Default active view: exclude archived and deleted
        query["is_archived"] = {"$ne": True}
        query["is_deleted"] = {"$ne": True}

    # Non-admins only see contracts they created
    if not is_admin and user_id:
        query["created_by"] = user_id

    # Text search - searches the title field using regex (case-insensitive)
    if filters.search:
        query["title"] = {"$regex": filters.search, "$options": "i"}

    # Exact match filters - only add to query if the filter was provided
    if filters.contract_type:
        query["contract_type"] = filters.contract_type.value

    if filters.status:
        query["status"] = filters.status.value

    if filters.workflow_stage:
        query["workflow_stage"] = filters.workflow_stage.value

    if filters.risk_level:
        query["ai_analysis.risk_level"] = filters.risk_level.value

    # Date range filter - find contracts starting within a date range
    if filters.start_date_from or filters.start_date_to:
        date_filter = {}
        if filters.start_date_from:
            date_filter["$gte"] = filters.start_date_from
        if filters.start_date_to:
            date_filter["$lte"] = filters.start_date_to
        query["start_date"] = date_filter

    # Calculate how many documents to skip for pagination
    # Page 1 skips 0, page 2 skips 20, page 3 skips 40, etc.
    skip = (filters.page - 1) * filters.per_page

    # Get total count of matching documents (for "showing 1-20 of 45 results")
    total = contracts_collection.count_documents(query)

    # Fetch the actual documents, sorted by newest first
    contracts_cursor = (
        contracts_collection
        .find(query)
        .sort("created_at", -1)     # -1 means descending (newest first)
        .skip(skip)                  # Skip documents for pagination
        .limit(filters.per_page)     # Only return this many
    )

    # Convert each document from MongoDB format to API format
    contracts = [contract_to_response(c) for c in contracts_cursor]

    return {
        "contracts": contracts,
        "total": total,
        "page": filters.page,
        "per_page": filters.per_page,
        "total_pages": (total + filters.per_page - 1) // filters.per_page,
    }


# UPDATE a contract
async def update_contract(contract_id: str, update_data: ContractUpdate) -> Optional[dict]:
    if not ObjectId.is_valid(contract_id):
        return None

    # model_dump(exclude_unset=True) only includes fields the user actually sent
    # If they only sent {"status": "active"}, we don't overwrite title, parties, etc.
    update_dict = update_data.model_dump(exclude_unset=True)

    # If there's nothing to update, just return the existing contract
    if not update_dict:
        return await get_contract(contract_id)

    # Always update the timestamp when modifying
    update_dict["updated_at"] = datetime.utcnow()

    # $set tells MongoDB "update only these specific fields, leave everything else alone"
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": update_dict}
    )

    return await get_contract(contract_id)


# SOFT-DELETE a contract (moves to trash, permanent delete after 30 days)
async def delete_contract(contract_id: str) -> bool:
    if not ObjectId.is_valid(contract_id):
        return False

    result = contracts_collection.update_one(
        {"_id": ObjectId(contract_id), "is_deleted": {"$ne": True}},
        {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow(), "is_archived": False, "updated_at": datetime.utcnow()}},
    )
    return result.modified_count > 0


# PERMANENTLY delete a contract (irreversible)
async def permanent_delete_contract(contract_id: str) -> bool:
    if not ObjectId.is_valid(contract_id):
        return False

    result = contracts_collection.delete_one({"_id": ObjectId(contract_id)})
    return result.deleted_count > 0


# RESTORE a contract from trash
async def restore_contract(contract_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(contract_id):
        return None

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id), "is_deleted": True},
        {"$set": {"is_deleted": False, "deleted_at": None, "updated_at": datetime.utcnow()}},
    )
    return await get_contract(contract_id)


# ARCHIVE a contract
async def archive_contract(contract_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(contract_id):
        return None

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id), "is_deleted": {"$ne": True}},
        {"$set": {"is_archived": True, "archived_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    return await get_contract(contract_id)


# UNARCHIVE a contract
async def unarchive_contract(contract_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(contract_id):
        return None

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {"is_archived": False, "archived_at": None, "updated_at": datetime.utcnow()}},
    )
    return await get_contract(contract_id)


# PURGE contracts that have been in trash for more than 30 days
async def purge_expired_trash() -> int:
    cutoff = datetime.utcnow() - timedelta(days=30)
    result = contracts_collection.delete_many(
        {"is_deleted": True, "deleted_at": {"$lte": cutoff}}
    )
    return result.deleted_count


# UPDATE workflow stage of a contract
async def update_workflow_stage(contract_id: str, new_stage: str) -> Optional[dict]:
    if not ObjectId.is_valid(contract_id):
        return None

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {
            "$set": {
                "workflow_stage": new_stage,
                "updated_at": datetime.utcnow(),
            }
        }
    )

    return await get_contract(contract_id)


# GET dashboard statistics
async def get_dashboard_stats() -> dict:
    # Count contracts by status
    total = contracts_collection.count_documents({})
    active = contracts_collection.count_documents({"status": "active"})
    draft = contracts_collection.count_documents({"status": "draft"})
    expired = contracts_collection.count_documents({"status": "expired"})

    # Find contracts expiring in the next 30 days
    now = datetime.utcnow()
    thirty_days = datetime(now.year, now.month + 1, now.day) if now.month < 12 else datetime(now.year + 1, 1, now.day)

    expiring_soon = contracts_collection.count_documents({
        "status": "active",
        "end_date": {"$gte": now, "$lte": thirty_days}
    })

    # Count contracts by risk level
    high_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "high"})
    medium_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "medium"})
    low_risk = contracts_collection.count_documents({"ai_analysis.risk_level": "low"})

    return {
        "total_contracts": total,
        "active_contracts": active,
        "draft_contracts": draft,
        "expired_contracts": expired,
        "expiring_soon": expiring_soon,
        "risk_summary": {
            "high": high_risk,
            "medium": medium_risk,
            "low": low_risk,
        }
    }