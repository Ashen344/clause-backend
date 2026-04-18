from fastapi import APIRouter, HTTPException, Depends, Query
import httpx
from app.middleware.auth import get_current_user
from app.models.user import UserUpdate, UserRole
from app.services.auth_service import (
    get_or_create_user,
    get_user_by_clerk_id,
    update_user,
    get_all_users,
    update_user_role,
    deactivate_user,
    activate_user,
)
from app.config import CLERK_SECRET_KEY

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# ── Clerk Management API helpers ──────────────────────────────────────────────

def _clerk_headers() -> dict:
    return {"Authorization": f"Bearer {CLERK_SECRET_KEY}"}


async def _fetch_clerk_user(clerk_id: str) -> dict:
    """Fetch a single user's full profile from the Clerk Management API."""
    if not CLERK_SECRET_KEY or not clerk_id:
        return {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_id}",
                headers=_clerk_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {}


async def _fetch_all_clerk_users(limit: int = 200) -> list:
    """Fetch all users from the Clerk Management API."""
    if not CLERK_SECRET_KEY:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users?limit={limit}&order_by=-created_at",
                headers=_clerk_headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return []


def _extract_clerk_profile(cu: dict) -> dict:
    """Extract name, email and avatar from a Clerk user object."""
    first = cu.get("first_name") or ""
    last  = cu.get("last_name")  or ""
    full_name = f"{first} {last}".strip() or cu.get("username") or ""

    email_addresses   = cu.get("email_addresses", [])
    primary_email_id  = cu.get("primary_email_address_id")
    email = ""
    if email_addresses:
        primary = next(
            (e for e in email_addresses if e.get("id") == primary_email_id),
            email_addresses[0],
        )
        email = primary.get("email_address", "")

    return {
        "full_name":  full_name,
        "email":      email,
        "image_url":  cu.get("image_url", ""),
        "created_at": cu.get("created_at"),   # epoch ms from Clerk
    }


async def _sync_role_to_clerk(clerk_id: str, role: str) -> None:
    """Push the updated role into Clerk's publicMetadata so the frontend sees it immediately."""
    if not CLERK_SECRET_KEY or not clerk_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"https://api.clerk.com/v1/users/{clerk_id}/metadata",
                headers={**_clerk_headers(), "Content-Type": "application/json"},
                json={"public_metadata": {"role": role}},
                timeout=10,
            )
    except Exception:
        pass  # Non-fatal — DB is source of truth; Clerk sync is best-effort


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/sync")
async def sync_user(current_user: dict = Depends(get_current_user)):
    """Sync user from Clerk on first login or session refresh.
    Fetches the real name + email from the Clerk Management API so the DB
    always holds accurate profile data."""
    clerk_id = current_user["user_id"]

    # Pull rich profile from Clerk Management API
    clerk_profile = await _fetch_clerk_user(clerk_id)
    if clerk_profile:
        profile = _extract_clerk_profile(clerk_profile)
        email     = profile["email"]     or current_user.get("email", "")
        full_name = profile["full_name"] or f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
    else:
        email     = current_user.get("email", "")
        full_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()

    user = get_or_create_user(clerk_id=clerk_id, email=email, full_name=full_name)
    return user


@router.get("/me")
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Get the currently authenticated user's profile."""
    user = get_user_by_clerk_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User profile not found. Please sync first.")
    return user


@router.put("/me")
async def update_my_profile(
    update_data: UserUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update the current user's profile information."""
    # Prevent non-admins from changing their own role
    if update_data.role is not None:
        db_user = get_user_by_clerk_id(current_user["user_id"])
        if db_user and db_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Only admins can change roles")

    user = update_user(current_user["user_id"], update_data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# --- Admin endpoints ---

@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """List all users (admin only).

    Returns Clerk users enriched with roles/status from our MongoDB.
    Users who haven't synced yet are included with role='user' and status='active'.
    """
    db_user = get_user_by_clerk_id(current_user["user_id"])
    if not db_user or db_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # 1. Fetch all users from Clerk (source of truth for name/email/avatar)
    clerk_users = await _fetch_all_clerk_users(limit=500)

    # 2. Build a map of clerk_id → MongoDB record for roles/status
    from app.config import users_collection
    db_records = {
        u["clerk_id"]: u
        for u in users_collection.find({}, {"_id": 1, "clerk_id": 1, "role": 1, "status": 1, "created_at": 1})
        if u.get("clerk_id")
    }

    # 3. Merge: one row per Clerk user
    merged = []
    from datetime import datetime, timezone
    for cu in clerk_users:
        clerk_id = cu.get("id", "")
        profile  = _extract_clerk_profile(cu)
        db       = db_records.get(clerk_id, {})

        # Clerk timestamps are epoch milliseconds
        raw_ts = cu.get("created_at")
        if raw_ts:
            try:
                created_at = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc).isoformat()
            except Exception:
                created_at = None
        else:
            created_at = None

        merged.append({
            "id":        str(db["_id"]) if db.get("_id") else clerk_id,  # MongoDB _id if synced
            "clerk_id":  clerk_id,
            "full_name": profile["full_name"],
            "email":     profile["email"],
            "image_url": profile["image_url"],
            "role":      db.get("role", "user"),
            "status":    db.get("status", "active"),
            "created_at": created_at,
        })

    # 4. Paginate
    total = len(merged)
    start = (page - 1) * per_page
    page_items = merged[start: start + per_page]

    return {
        "users":       page_items,
        "total":       total,
        "page":        page,
        "per_page":    per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


def _resolve_user_by_id_or_clerk(user_id: str):
    """Find a MongoDB user by Mongo _id (preferred) or clerk_id (fallback).
    For users who haven't synced yet, `user_id` will be the Clerk user ID."""
    from app.services.auth_service import get_user_by_id, get_user_by_clerk_id as _by_clerk
    user = get_user_by_id(user_id)
    if not user:
        user = _by_clerk(user_id)
    return user


@router.patch("/users/{user_id}/role")
async def change_user_role(
    user_id: str,
    role: UserRole,
    current_user: dict = Depends(get_current_user),
):
    """Change a user's role (admin only).

    user_id may be a MongoDB _id or a Clerk user ID (for un-synced users).
    If the user hasn't synced yet we create a minimal DB record first."""
    db_user = get_user_by_clerk_id(current_user["user_id"])
    if not db_user or db_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Try to find by MongoDB _id first, then clerk_id
    target = _resolve_user_by_id_or_clerk(user_id)

    if not target:
        # User exists in Clerk but hasn't synced — create a stub record so we can assign a role
        clerk_profile = await _fetch_clerk_user(user_id)
        if not clerk_profile:
            raise HTTPException(status_code=404, detail="User not found")
        profile = _extract_clerk_profile(clerk_profile)
        target = get_or_create_user(
            clerk_id=user_id,
            email=profile["email"],
            full_name=profile["full_name"],
        )

    # Now do the role update using the MongoDB _id
    mongo_id = target.get("id") or target.get("_id")
    user = update_user_role(str(mongo_id), role.value)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Sync the new role to Clerk public metadata so the frontend picks it up instantly
    await _sync_role_to_clerk(user.get("clerk_id", ""), role.value)

    return user


@router.patch("/users/{user_id}/deactivate")
async def deactivate_user_account(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Deactivate a user account (admin only)."""
    db_user = get_user_by_clerk_id(current_user["user_id"])
    if not db_user or db_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    target = _resolve_user_by_id_or_clerk(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    mongo_id = target.get("id") or target.get("_id")
    user = deactivate_user(str(mongo_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}/activate")
async def activate_user_account(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Reactivate a deactivated user account (admin only)."""
    db_user = get_user_by_clerk_id(current_user["user_id"])
    if not db_user or db_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    target = _resolve_user_by_id_or_clerk(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    mongo_id = target.get("id") or target.get("_id")
    user = activate_user(str(mongo_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
