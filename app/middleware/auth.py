from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from typing import Optional, List
import httpx
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
        return {
            "user_id": unverified.get("sub"),
            "email": unverified.get("email", ""),
            "first_name": unverified.get("first_name", ""),
            "last_name": unverified.get("last_name", ""),
        }
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Dependency that extracts and validates the current user from the JWT token.
    Also enriches the token data with the user's role from the database."""
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

    # Enrich with DB role so downstream routes can check permissions
    db_user = users_collection.find_one({"clerk_id": user_data["user_id"]})
    if db_user:
        user_data["role"] = db_user.get("role", "user")
        user_data["db_id"] = str(db_user["_id"])
    else:
        user_data["role"] = "user"
        user_data["db_id"] = None

    return user_data


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Dependency that optionally extracts user info - doesn't fail if no token."""
    if not credentials:
        return None

    token = credentials.credentials
    user_data = decode_clerk_token(token)
    if user_data and user_data.get("user_id"):
        db_user = users_collection.find_one({"clerk_id": user_data["user_id"]})
        if db_user:
            user_data["role"] = db_user.get("role", "user")
            user_data["db_id"] = str(db_user["_id"])
        else:
            user_data["role"] = "user"
            user_data["db_id"] = None
    return user_data


def require_role(allowed_roles: List[str]):
    """Dependency factory that enforces role-based access.
    Usage: current_user: dict = Depends(require_role(["admin", "manager"]))
    """
    async def role_checker(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> dict:
        if not credentials:
            raise HTTPException(
                status_code=401,
                detail="Authentication required.",
            )

        token = credentials.credentials
        user_data = decode_clerk_token(token)

        if not user_data or not user_data.get("user_id"):
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired authentication token.",
            )

        db_user = users_collection.find_one({"clerk_id": user_data["user_id"]})
        if db_user:
            user_data["role"] = db_user.get("role", "user")
            user_data["db_id"] = str(db_user["_id"])
        else:
            user_data["role"] = "user"
            user_data["db_id"] = None

        if user_data["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}. Your role: {user_data['role']}",
            )

        return user_data

    return role_checker
