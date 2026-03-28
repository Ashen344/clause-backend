from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional


def to_object_id(id_string: str) -> Optional[ObjectId]:
    """Safely convert a string to MongoDB ObjectId."""
    if ObjectId.is_valid(id_string):
        return ObjectId(id_string)
    return None


def serialize_doc(doc: dict) -> dict:
    """Convert a MongoDB document to a JSON-serializable dict."""
    if doc is None:
        return None
    doc["id"] = str(doc.pop("_id"))
    # Convert any remaining ObjectId fields
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, datetime):
            doc[key] = value.isoformat()
    return doc


def generate_contract_number() -> str:
    """Generate a unique contract number like CLM-2026-0001."""
    from app.config import contracts_collection
    now = datetime.utcnow()
    year = now.year
    # Count contracts created this year
    count = contracts_collection.count_documents({
        "created_at": {
            "$gte": datetime(year, 1, 1),
            "$lt": datetime(year + 1, 1, 1),
        }
    })
    return f"CLM-{year}-{count + 1:04d}"


def days_until(target_date: datetime) -> int:
    """Calculate days from now until a target date."""
    delta = target_date - datetime.utcnow()
    return max(0, delta.days)


def paginate_query(collection, query: dict, sort_field: str = "created_at",
                   sort_order: int = -1, page: int = 1, per_page: int = 20) -> dict:
    """Generic pagination helper for MongoDB queries."""
    skip = (page - 1) * per_page
    total = collection.count_documents(query)
    cursor = (
        collection
        .find(query)
        .sort(sort_field, sort_order)
        .skip(skip)
        .limit(per_page)
    )
    return {
        "items": list(cursor),
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }
