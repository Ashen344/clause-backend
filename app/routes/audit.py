from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.middleware.auth import get_current_user
from app.services.audit_service import get_audit_logs

router = APIRouter(prefix="/api/audit", tags=["Audit Logs"])


@router.get("/")
async def list_audit_logs(
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Get audit logs with optional filters (admin/manager only)."""
    return get_audit_logs(
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        action=action,
        page=page,
        per_page=per_page,
    )
