from bson import ObjectId
from datetime import datetime
from typing import Optional
from app.config import workflows_collection, contracts_collection
from app.models.workflow import (
    WorkflowCreate,
    WorkflowInDB,
    WorkflowStatus,
    StepStatus,
    DEFAULT_WORKFLOW_STEPS,
)


def workflow_to_response(workflow: dict) -> dict:
    workflow["id"] = str(workflow["_id"])
    del workflow["_id"]
    return workflow


async def create_workflow(workflow_data: WorkflowCreate, user_id: str) -> dict:
    """Create a new workflow for a contract."""
    # Verify the contract exists
    if not ObjectId.is_valid(workflow_data.contract_id):
        return None

    contract = contracts_collection.find_one({"_id": ObjectId(workflow_data.contract_id)})
    if not contract:
        return None

    # Use provided steps or default workflow steps
    steps = workflow_data.steps if workflow_data.steps else DEFAULT_WORKFLOW_STEPS

    # Set first step to in_progress
    steps_dicts = []
    for i, step in enumerate(steps):
        step_dict = step.model_dump()
        if i == 0:
            step_dict["status"] = StepStatus.in_progress.value
        steps_dicts.append(step_dict)

    workflow_dict = WorkflowInDB(
        contract_id=workflow_data.contract_id,
        name=workflow_data.name,
        steps=steps,
        created_by=user_id,
    ).model_dump()

    # Override steps with our modified version
    workflow_dict["steps"] = steps_dicts

    result = workflows_collection.insert_one(workflow_dict)

    # Link workflow to contract
    contracts_collection.update_one(
        {"_id": ObjectId(workflow_data.contract_id)},
        {"$set": {
            "workflow_id": str(result.inserted_id),
            "workflow_stage": "request",
            "updated_at": datetime.utcnow(),
        }}
    )

    created = workflows_collection.find_one({"_id": result.inserted_id})
    return workflow_to_response(created)


async def get_workflow(workflow_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(workflow_id):
        return None
    workflow = workflows_collection.find_one({"_id": ObjectId(workflow_id)})
    if not workflow:
        return None
    return workflow_to_response(workflow)


async def get_workflows_by_contract(contract_id: str) -> list:
    workflows = workflows_collection.find({"contract_id": contract_id}).sort("created_at", -1)
    return [workflow_to_response(w) for w in workflows]


async def advance_workflow(workflow_id: str, user_id: str, comments: str = None) -> Optional[dict]:
    """Complete the current step and advance to the next one."""
    if not ObjectId.is_valid(workflow_id):
        return None

    workflow = workflows_collection.find_one({"_id": ObjectId(workflow_id)})
    if not workflow or workflow["status"] != WorkflowStatus.active.value:
        return None

    steps = workflow["steps"]
    current_step_idx = workflow["current_step"] - 1

    if current_step_idx >= len(steps):
        return None

    # Complete current step
    steps[current_step_idx]["status"] = StepStatus.completed.value
    steps[current_step_idx]["completed_by"] = user_id
    steps[current_step_idx]["completed_at"] = datetime.utcnow()
    if comments:
        steps[current_step_idx]["comments"] = comments

    # Check if this was the last step
    next_step = workflow["current_step"] + 1
    update = {
        "steps": steps,
        "current_step": next_step,
        "updated_at": datetime.utcnow(),
    }

    if current_step_idx + 1 >= len(steps):
        # Workflow complete
        update["status"] = WorkflowStatus.completed.value
        update["completed_at"] = datetime.utcnow()

        # Update contract status to active
        if workflow.get("contract_id"):
            contracts_collection.update_one(
                {"_id": ObjectId(workflow["contract_id"])},
                {"$set": {"status": "active", "workflow_stage": "storage", "updated_at": datetime.utcnow()}}
            )
    else:
        # Activate next step
        steps[current_step_idx + 1]["status"] = StepStatus.in_progress.value

        # Map step number to workflow stage for contract
        stage_map = {
            1: "request", 2: "authoring", 3: "review", 4: "review",
            5: "approval", 6: "execution", 7: "storage", 8: "monitoring", 9: "renewal",
        }
        new_stage = stage_map.get(next_step, "monitoring")

        if workflow.get("contract_id"):
            contracts_collection.update_one(
                {"_id": ObjectId(workflow["contract_id"])},
                {"$set": {"workflow_stage": new_stage, "updated_at": datetime.utcnow()}}
            )

    workflows_collection.update_one(
        {"_id": ObjectId(workflow_id)},
        {"$set": update}
    )

    return await get_workflow(workflow_id)


async def reject_workflow(workflow_id: str, user_id: str, reason: str = None) -> Optional[dict]:
    """Reject the workflow at the current step."""
    if not ObjectId.is_valid(workflow_id):
        return None

    workflow = workflows_collection.find_one({"_id": ObjectId(workflow_id)})
    if not workflow or workflow["status"] != WorkflowStatus.active.value:
        return None

    steps = workflow["steps"]
    current_step_idx = workflow["current_step"] - 1

    steps[current_step_idx]["status"] = StepStatus.rejected.value
    steps[current_step_idx]["completed_by"] = user_id
    steps[current_step_idx]["completed_at"] = datetime.utcnow()
    if reason:
        steps[current_step_idx]["comments"] = reason

    workflows_collection.update_one(
        {"_id": ObjectId(workflow_id)},
        {"$set": {
            "steps": steps,
            "status": WorkflowStatus.cancelled.value,
            "updated_at": datetime.utcnow(),
        }}
    )

    # Revert contract to draft
    if workflow.get("contract_id"):
        contracts_collection.update_one(
            {"_id": ObjectId(workflow["contract_id"])},
            {"$set": {"status": "draft", "workflow_stage": "request", "updated_at": datetime.utcnow()}}
        )

    return await get_workflow(workflow_id)
