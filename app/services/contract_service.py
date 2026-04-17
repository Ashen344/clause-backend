from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional
from app.config import contracts_collection
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

    # Pull risk info from nested ai_analysis into top-level fields
    # so the frontend can display them easily without digging into nested objects
    if contract.get("ai_analysis"):
        contract["risk_score"] = contract["ai_analysis"].get("risk_score")
        contract["risk_level"] = contract["ai_analysis"].get("risk_level")
    else:
        contract["risk_score"] = None
        contract["risk_level"] = None

    return contract


# CREATE a new contract
async def create_contract(contract_data: ContractCreate, user_id: str) -> dict:
    # Build the full document that goes into MongoDB
    # We take what the user sent and add server-controlled fields
    contract_dict = ContractInDB(
        **contract_data.model_dump(),    # Spread all fields from the request
        created_by=user_id,              # Server sets who created it
    ).model_dump()

    # Insert into MongoDB - this returns an object with the new document's ID
    result = contracts_collection.insert_one(contract_dict)

    # Fetch the newly created document back so we can return it
    created_contract = contracts_collection.find_one({"_id": result.inserted_id})

    return contract_to_response(created_contract)


# GET a single contract by its ID
async def get_contract(contract_id: str) -> Optional[dict]:
    # Validate that the ID is a valid MongoDB ObjectId format
    # If someone sends "abc123" instead of a proper 24-character hex string, catch it
    if not ObjectId.is_valid(contract_id):
        return None

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})

    if not contract:
        return None

    return contract_to_response(contract)


# GET all contracts with filtering, searching, and pagination
async def get_contracts(filters: ContractFilter) -> dict:
    # Build the MongoDB query dynamically based on what filters were provided
    query = {}

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


# DELETE a contract
async def delete_contract(contract_id: str) -> bool:
    if not ObjectId.is_valid(contract_id):
        return False

    result = contracts_collection.delete_one({"_id": ObjectId(contract_id)})

    # deleted_count is 1 if a document was found and deleted, 0 if not found
    return result.deleted_count > 0


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
    thirty_days = now + timedelta(days=30)

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
