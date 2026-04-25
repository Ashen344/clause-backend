import sys
import os
from bson import ObjectId
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))


# ── User helpers ──────────────────────────────────────────────────────────────

def make_user(clerk_id: str = "clerk_default", status: str = "active") -> dict:
    return {
        "_id": ObjectId(),
        "clerk_id": clerk_id,
        "email": f"{clerk_id}@example.com",
        "full_name": "Test User",
        "role": "user",
        "organization": None,
        "status": status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "last_login": datetime.now(timezone.utc),
    }


# ── Workflow helpers ──────────────────────────────────────────────────────────

def _make_step(index: int, status: str = "pending") -> dict:
    return {
        "name": f"Step {index + 1}",
        "description": f"Description {index + 1}",
        "role_required": "user",
        "status": status,
        "completed_by": None,
        "completed_at": None,
        "comments": None,
    }


def make_workflow(
    num_steps: int = 2,
    current_step: int = 1,
    status: str = "active",
) -> dict:
    steps = [_make_step(i) for i in range(num_steps)]
    if steps and 0 <= current_step - 1 < len(steps):
        steps[current_step - 1]["status"] = "in_progress"
    return {
        "_id": ObjectId(),
        "contract_id": str(ObjectId()),
        "name": "Test Workflow",
        "status": status,
        "current_step": current_step,
        "steps": steps,
        "created_by": "user_001",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


# ── Contract helpers ──────────────────────────────────────────────────────────

def make_contract(
    created_by: str = "user_001",
    ai: dict = None,
) -> dict:
    return {
        "_id": ObjectId(),
        "title": "Test Contract",
        "description": "A test contract",
        "status": "draft",
        "workflow_stage": "request",
        "created_by": created_by,
        "ai_analysis": ai,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


# ── Approval helpers ──────────────────────────────────────────────────────────

def approver(user_id: str, decision: str = None) -> dict:
    return {
        "user_id": user_id,
        "decision": decision,
        "user_email": None,
        "decided_at": None,
    }


def make_approval(
    status: str = "pending",
    approvers: list = None,
) -> dict:
    if approvers is None:
        approvers = [approver("u1"), approver("u2")]
    return {
        "_id": ObjectId(),
        "contract_id": str(ObjectId()),
        "workflow_id": str(ObjectId()),
        "approval_type": "all_required",
        "status": status,
        "approvers": approvers,
        "created_by": "user_001",
        "due_date": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
