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
)
from app.config import CLERK_SECRET_KEY

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


async def _sync_role_to_clerk(clerk_id: str, role: str) -> None:
    """Push the updated role into Clerk's publicMetadata so the frontend sees it immediately."""
    if not CLERK_SECRET_KEY or not clerk_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"https://api.clerk.com/v1/users/{clerk_id}/metadata",
                headers={
                    "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                    "Content-Type": "application/json",
                },
                json={"public_metadata": {"role": role}},
                timeout=10,
            )
    except Exception:
        pass  # Non-fatal — DB is source of truth; Clerk sync is best-effort


@router.post("/sync")
async def sync_user(current_user: dict = Depends(get_current_user)):
    """Sync user from Clerk on first login or session refresh.
    Creates the user in our DB if they don't exist yet."""
    user = get_or_create_user(
        clerk_id=current_user["user_id"],
        email=current_user.get("email", ""),
        full_name=f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip(),
    )
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
    """List all users (admin only)."""
    db_user = get_user_by_clerk_id(current_user["user_id"])
    if not db_user or db_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return get_all_users(page, per_page)


@router.patch("/users/{user_id}/role")
async def change_user_role(
    user_id: str,
    role: UserRole,
    current_user: dict = Depends(get_current_user),
):
    """Change a user's role (admin only)."""
    db_user = get_user_by_clerk_id(current_user["user_id"])
    if not db_user or db_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    user = update_user_role(user_id, role.value)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Sync the new role to Clerk public metadata so the frontend picks it up
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

    user = deactivate_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
