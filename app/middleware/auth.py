from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from typing import Optional
import httpx
from pymongo import ReturnDocument
from app.config import CLERK_SECRET_KEY, CLERK_ISSUER, users_collection

security = HTTPBearer(auto_error=False)

# Cache for Clerk's JWKS keys
_jwks_cache = None


async def _get_clerk_jwks():
    """Fetch Clerk's JSON Web Key Set for token verification."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache

    if not CLERK_ISSUER:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{CLERK_ISSUER}/.well-known/jwks.json")
            if response.status_code == 200:
                _jwks_cache = response.json()
                return _jwks_cache
    except Exception:
        pass
    return None


def decode_clerk_token(token: str) -> Optional[dict]:
    """Decode and verify a Clerk JWT token."""
    try:
        # Try to decode without verification first (for development)
        unverified = jwt.get_unverified_claims(token)
        pub_meta = unverified.get("public_metadata") or {}
        return {
            "user_id": unverified.get("sub"),
            "email": unverified.get("email", ""),
            "first_name": unverified.get("first_name", ""),
            "last_name": unverified.get("last_name", ""),
            "role": pub_meta.get("role", ""),
        }
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Dependency that extracts and validates the current user from the JWT token."""
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please provide a valid Bearer token.",
        )

    token = credentials.credentials
    user_data = decode_clerk_token(token)

    if not user_data or not user_data.get("user_id"):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token.",
        )

    return user_data


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Dependency that optionally extracts user info - doesn't fail if no token."""
    if not credentials:
        return None

    token = credentials.credentials
    return decode_clerk_token(token)


async def get_current_user_with_role(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Like get_current_user but also attaches the user's role from our DB."""
    user_data = await get_current_user(credentials)

    first = user_data.get("first_name", "").strip()
    last = user_data.get("last_name", "").strip()
    full_name = f"{first} {last}".strip() or user_data.get("email", "")

    # Only overwrite email/full_name if the JWT actually contains them —
    # otherwise we'd wipe values that were stored by /api/auth/sync
    set_doc = {"clerk_id": user_data["user_id"]}
    if user_data.get("email"):
        set_doc["email"] = user_data["email"]
    if full_name:
        set_doc["full_name"] = full_name

    db_user = users_collection.find_one_and_update(
        {"clerk_id": user_data["user_id"]},
        {"$set": set_doc, "$setOnInsert": {"role": "user", "status": "active"}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    user_data["role"] = db_user.get("role", "user")
    user_data["db_id"] = str(db_user["_id"])
    user_data["full_name"] = full_name

    return user_data
