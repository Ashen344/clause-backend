import pytest
from bson import ObjectId
from datetime import datetime


def make_user(clerk_id="u1", role="user", status="active"):
    return {
        "_id":          ObjectId(),
        "clerk_id":     clerk_id,
        "email":        "test@example.com",
        "full_name":    "Test User",
        "role":         role,
        "status":       status,
        "organization": None,
        "created_at":   datetime.utcnow(),
        "updated_at":   datetime.utcnow(),
        "last_login":   datetime.utcnow(),
    }


def make_contract(created_by="user_001", ai=None):
    from datetime import timedelta
    return {
        "_id":             ObjectId(),
        "title":           "Test Contract",
        "contract_type":   "service_agreement",
        "status":          "draft",
        "workflow_stage":  "request",
        "parties":         [],
        "start_date":      datetime.utcnow(),
        "end_date":        datetime.utcnow() + timedelta(days=365),
        "value":           10000.0,
        "created_by":      created_by,
        "created_at":      datetime.utcnow(),
        "updated_at":      datetime.utcnow(),
        "ai_analysis":     ai,
        "versions":        [],
        "current_version": 1,
    }


def make_workflow(status="active", current_step=1, num_steps=3, contract_id=None):
    steps = [
        {
            "step_number":  i + 1,
            "name":         f"Step {i+1}",
            "status":       "in_progress" if i == 0 else "pending",
            "completed_by": None,
            "completed_at": None,
            "comments":     None,
        }
        for i in range(num_steps)
    ]
    return {
        "_id":          ObjectId(),
        "status":       status,
        "current_step": current_step,
        "steps":        steps,
        "contract_id":  contract_id or str(ObjectId()),
        "created_by":   "user_001",
        "created_at":   datetime.utcnow(),
        "updated_at":   datetime.utcnow(),
    }


def make_approval(status="pending", approvers=None, approval_type="all_required"):
    if approvers is None:
        approvers = [{"user_id": "u1", "decision": None, "user_email": None, "decided_at": None}]
    return {
        "_id":           ObjectId(),
        "status":        status,
        "approvers":     approvers,
        "approval_type": approval_type,
        "contract_id":   str(ObjectId()),
        "workflow_id":   str(ObjectId()),
    }


def approver(uid, decision=None):
    return {
        "user_id":    uid,
        "user_email": f"{uid}@test.com",
        "decision":   decision,
        "decided_at": None,
    }