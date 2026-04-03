"""
Seed script to populate the Clause database with sample data.
Run: python seed.py
"""

from datetime import datetime, timedelta
from app.config import (
    db,
    users_collection,
    contracts_collection,
    templates_collection,
    workflows_collection,
    approvals_collection,
    notifications_collection,
    audit_logs_collection,
)

# Clear existing data
def clear_all():
    for col in [users_collection, contracts_collection, templates_collection,
                workflows_collection, approvals_collection, notifications_collection,
                audit_logs_collection]:
        col.delete_many({})
    print("Cleared all collections.")


def seed_users():
    users = [
        {
            "clerk_id": "user_seed_admin_001",
            "email": "admin@clause.io",
            "full_name": "Sarah Johnson",
            "role": "admin",
            "organization": "Clause Inc.",
            "status": "active",
            "created_at": datetime(2025, 1, 15),
            "updated_at": datetime(2026, 3, 20),
            "last_login": datetime(2026, 3, 31),
        },
        {
            "clerk_id": "user_seed_manager_001",
            "email": "michael.chen@clause.io",
            "full_name": "Michael Chen",
            "role": "manager",
            "organization": "Clause Inc.",
            "status": "active",
            "created_at": datetime(2025, 3, 1),
            "updated_at": datetime(2026, 3, 28),
            "last_login": datetime(2026, 3, 30),
        },
        {
            "clerk_id": "user_seed_user_001",
            "email": "emily.davis@clause.io",
            "full_name": "Emily Davis",
            "role": "user",
            "organization": "Clause Inc.",
            "status": "active",
            "created_at": datetime(2025, 6, 10),
            "updated_at": datetime(2026, 3, 25),
            "last_login": datetime(2026, 3, 29),
        },
        {
            "clerk_id": "user_seed_user_002",
            "email": "james.wilson@clause.io",
            "full_name": "James Wilson",
            "role": "user",
            "organization": "Clause Inc.",
            "status": "active",
            "created_at": datetime(2025, 8, 20),
            "updated_at": datetime(2026, 3, 15),
            "last_login": datetime(2026, 3, 28),
        },
        {
            "clerk_id": "user_seed_viewer_001",
            "email": "lisa.martinez@clause.io",
            "full_name": "Lisa Martinez",
            "role": "viewer",
            "organization": "Clause Inc.",
            "status": "active",
            "created_at": datetime(2025, 11, 5),
            "updated_at": datetime(2026, 2, 10),
            "last_login": datetime(2026, 3, 20),
        },
    ]
    result = users_collection.insert_many(users)
    print(f"Inserted {len(result.inserted_ids)} users.")
    return result.inserted_ids


def seed_templates():
    templates = [
        {
            "name": "Standard NDA",
            "description": "Non-disclosure agreement for protecting confidential business information.",
            "contract_type": "nda",
            "content": "<h1>Non-Disclosure Agreement</h1><p>This NDA is entered into by {{party_a}} and {{party_b}}...</p>",
            "fields": [
                {"field_name": "party_a", "field_type": "text", "required": True},
                {"field_name": "party_b", "field_type": "text", "required": True},
                {"field_name": "effective_date", "field_type": "date", "required": True},
                {"field_name": "duration_months", "field_type": "number", "required": True, "default_value": "24"},
            ],
            "tags": ["nda", "confidentiality", "standard"],
            "version": 1,
            "is_active": True,
            "created_by": "user_seed_admin_001",
            "created_at": datetime(2025, 2, 1),
            "updated_at": datetime(2025, 2, 1),
        },
        {
            "name": "SaaS Service Agreement",
            "description": "Template for software-as-a-service subscription agreements.",
            "contract_type": "service_agreement",
            "content": "<h1>SaaS Service Agreement</h1><p>This agreement governs the use of {{service_name}}...</p>",
            "fields": [
                {"field_name": "service_name", "field_type": "text", "required": True},
                {"field_name": "subscription_tier", "field_type": "select", "required": True, "options": ["Basic", "Professional", "Enterprise"]},
                {"field_name": "monthly_fee", "field_type": "number", "required": True},
                {"field_name": "start_date", "field_type": "date", "required": True},
            ],
            "tags": ["saas", "service", "subscription"],
            "version": 2,
            "is_active": True,
            "created_by": "user_seed_admin_001",
            "created_at": datetime(2025, 3, 15),
            "updated_at": datetime(2025, 9, 10),
        },
        {
            "name": "Employment Contract",
            "description": "Standard employment agreement for full-time employees.",
            "contract_type": "employment",
            "content": "<h1>Employment Agreement</h1><p>This employment contract is between {{company}} and {{employee}}...</p>",
            "fields": [
                {"field_name": "company", "field_type": "text", "required": True},
                {"field_name": "employee", "field_type": "text", "required": True},
                {"field_name": "position", "field_type": "text", "required": True},
                {"field_name": "salary", "field_type": "number", "required": True},
                {"field_name": "start_date", "field_type": "date", "required": True},
            ],
            "tags": ["employment", "hr", "hiring"],
            "version": 1,
            "is_active": True,
            "created_by": "user_seed_manager_001",
            "created_at": datetime(2025, 4, 1),
            "updated_at": datetime(2025, 4, 1),
        },
        {
            "name": "Vendor Agreement",
            "description": "Standard vendor/supplier agreement template.",
            "contract_type": "vendor",
            "content": "<h1>Vendor Agreement</h1><p>This agreement is between {{buyer}} and {{vendor}}...</p>",
            "fields": [
                {"field_name": "buyer", "field_type": "text", "required": True},
                {"field_name": "vendor", "field_type": "text", "required": True},
                {"field_name": "contract_value", "field_type": "number", "required": True},
            ],
            "tags": ["vendor", "procurement", "supply"],
            "version": 1,
            "is_active": True,
            "created_by": "user_seed_admin_001",
            "created_at": datetime(2025, 5, 20),
            "updated_at": datetime(2025, 5, 20),
        },
    ]
    result = templates_collection.insert_many(templates)
    print(f"Inserted {len(result.inserted_ids)} templates.")
    return result.inserted_ids


def seed_contracts():
    now = datetime.utcnow()
    contracts = [
        {
            "title": "Acme Corp NDA",
            "contract_type": "nda",
            "description": "Mutual NDA with Acme Corp for joint product exploration.",
            "parties": [
                {"name": "Clause Inc.", "role": "discloser", "email": "legal@clause.io", "organization": "Clause Inc."},
                {"name": "Acme Corp", "role": "recipient", "email": "legal@acme.com", "organization": "Acme Corp"},
            ],
            "start_date": datetime(2026, 1, 1),
            "end_date": datetime(2027, 1, 1),
            "value": None,
            "payment_terms": None,
            "status": "active",
            "workflow_stage": "monitoring",
            "approval_type": "all_required",
            "workflow_trigger": "creation",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": {
                "summary": "Standard mutual NDA with 12-month term. No unusual clauses detected.",
                "extracted_clauses": ["Confidentiality", "Non-solicitation", "Term and Termination", "Governing Law"],
                "key_information": {"duration": "12 months", "governing_law": "Delaware"},
                "risk_score": 15.0,
                "risk_level": "low",
                "analyzed_at": datetime(2026, 1, 2),
            },
            "created_by": "user_seed_user_001",
            "organization_id": "clause_inc",
            "tags": ["nda", "acme", "partnership"],
            "template_id": None,
            "created_at": datetime(2025, 12, 20),
            "updated_at": datetime(2026, 1, 5),
        },
        {
            "title": "CloudHost Pro Service Agreement",
            "contract_type": "service_agreement",
            "description": "Enterprise cloud hosting service agreement with CloudHost Pro.",
            "parties": [
                {"name": "Clause Inc.", "role": "client", "email": "ops@clause.io", "organization": "Clause Inc."},
                {"name": "CloudHost Pro", "role": "provider", "email": "sales@cloudhost.io", "organization": "CloudHost Pro"},
            ],
            "start_date": datetime(2026, 2, 1),
            "end_date": datetime(2027, 2, 1),
            "value": 48000.00,
            "payment_terms": "Monthly - $4,000/month",
            "status": "active",
            "workflow_stage": "monitoring",
            "approval_type": "majority",
            "workflow_trigger": "creation",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": {
                "summary": "Cloud hosting agreement with standard SLA. Auto-renewal clause present. Data processing addendum included.",
                "extracted_clauses": ["SLA 99.9% uptime", "Data Processing Agreement", "Auto-renewal", "Liability Cap", "Force Majeure"],
                "key_information": {"monthly_cost": "$4,000", "uptime_sla": "99.9%", "data_center": "US-East"},
                "risk_score": 35.0,
                "risk_level": "medium",
                "analyzed_at": datetime(2026, 2, 3),
            },
            "created_by": "user_seed_manager_001",
            "organization_id": "clause_inc",
            "tags": ["cloud", "hosting", "infrastructure"],
            "template_id": None,
            "created_at": datetime(2026, 1, 15),
            "updated_at": datetime(2026, 2, 5),
        },
        {
            "title": "Senior Developer Employment Contract - Alex Kim",
            "contract_type": "employment",
            "description": "Full-time employment agreement for Senior Developer position.",
            "parties": [
                {"name": "Clause Inc.", "role": "employer", "email": "hr@clause.io", "organization": "Clause Inc."},
                {"name": "Alex Kim", "role": "employee", "email": "alex.kim@email.com"},
            ],
            "start_date": datetime(2026, 3, 1),
            "end_date": datetime(2027, 3, 1),
            "value": 145000.00,
            "payment_terms": "Bi-weekly salary",
            "status": "active",
            "workflow_stage": "execution",
            "approval_type": "all_required",
            "workflow_trigger": "creation",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": {
                "summary": "Standard employment contract. Non-compete clause covers 12 months. Stock options vesting over 4 years.",
                "extracted_clauses": ["Compensation", "Non-compete (12 months)", "IP Assignment", "Stock Options", "Termination"],
                "key_information": {"salary": "$145,000", "equity": "10,000 options", "vesting": "4 years"},
                "risk_score": 25.0,
                "risk_level": "low",
                "analyzed_at": datetime(2026, 3, 2),
            },
            "created_by": "user_seed_manager_001",
            "organization_id": "clause_inc",
            "tags": ["employment", "engineering", "senior"],
            "template_id": None,
            "created_at": datetime(2026, 2, 10),
            "updated_at": datetime(2026, 3, 1),
        },
        {
            "title": "DataSecure Vendor Agreement",
            "contract_type": "vendor",
            "description": "Security audit and penetration testing services from DataSecure Ltd.",
            "parties": [
                {"name": "Clause Inc.", "role": "client", "email": "security@clause.io", "organization": "Clause Inc."},
                {"name": "DataSecure Ltd.", "role": "vendor", "email": "contracts@datasecure.com", "organization": "DataSecure Ltd."},
            ],
            "start_date": datetime(2026, 3, 15),
            "end_date": datetime(2026, 9, 15),
            "value": 75000.00,
            "payment_terms": "50% upfront, 50% on completion",
            "status": "draft",
            "workflow_stage": "review",
            "approval_type": "all_required",
            "workflow_trigger": "creation",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": {
                "summary": "Vendor agreement for security services. Unlimited liability clause flagged as high risk. Indemnification terms are one-sided.",
                "extracted_clauses": ["Scope of Work", "Unlimited Liability", "Indemnification", "Confidentiality", "Insurance Requirements"],
                "key_information": {"service_type": "Security Audit", "duration": "6 months"},
                "risk_score": 72.0,
                "risk_level": "high",
                "analyzed_at": datetime(2026, 3, 16),
            },
            "created_by": "user_seed_user_001",
            "organization_id": "clause_inc",
            "tags": ["security", "vendor", "audit"],
            "template_id": None,
            "created_at": datetime(2026, 3, 10),
            "updated_at": datetime(2026, 3, 16),
        },
        {
            "title": "TechBridge Licensing Agreement",
            "contract_type": "licensing",
            "description": "Software licensing agreement for TechBridge API integration toolkit.",
            "parties": [
                {"name": "Clause Inc.", "role": "licensee", "email": "tech@clause.io", "organization": "Clause Inc."},
                {"name": "TechBridge Solutions", "role": "licensor", "email": "licensing@techbridge.com", "organization": "TechBridge Solutions"},
            ],
            "start_date": datetime(2026, 4, 1),
            "end_date": datetime(2028, 4, 1),
            "value": 120000.00,
            "payment_terms": "Annual - $60,000/year",
            "status": "draft",
            "workflow_stage": "approval",
            "approval_type": "majority",
            "workflow_trigger": "creation",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": {
                "summary": "Two-year licensing agreement. Usage limits apply. Audit rights clause allows licensor to inspect usage records.",
                "extracted_clauses": ["License Grant", "Usage Limits", "Audit Rights", "IP Ownership", "Warranty Disclaimer"],
                "key_information": {"license_type": "Enterprise", "seats": "Unlimited", "term": "2 years"},
                "risk_score": 45.0,
                "risk_level": "medium",
                "analyzed_at": datetime(2026, 3, 28),
            },
            "created_by": "user_seed_admin_001",
            "organization_id": "clause_inc",
            "tags": ["licensing", "api", "integration"],
            "template_id": None,
            "created_at": datetime(2026, 3, 20),
            "updated_at": datetime(2026, 3, 28),
        },
        {
            "title": "Strategic Partnership - InnovateCo",
            "contract_type": "partnership",
            "description": "Strategic partnership agreement for co-developing AI-powered contract tools.",
            "parties": [
                {"name": "Clause Inc.", "role": "partner", "email": "partnerships@clause.io", "organization": "Clause Inc."},
                {"name": "InnovateCo", "role": "partner", "email": "bd@innovateco.com", "organization": "InnovateCo"},
            ],
            "start_date": datetime(2026, 5, 1),
            "end_date": datetime(2029, 5, 1),
            "value": 500000.00,
            "payment_terms": "Revenue sharing - 60/40 split",
            "status": "draft",
            "workflow_stage": "authoring",
            "approval_type": "all_required",
            "workflow_trigger": "creation",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": None,
            "created_by": "user_seed_admin_001",
            "organization_id": "clause_inc",
            "tags": ["partnership", "ai", "strategic"],
            "template_id": None,
            "created_at": datetime(2026, 3, 25),
            "updated_at": datetime(2026, 3, 25),
        },
        {
            "title": "Office Lease Renewal - Downtown HQ",
            "contract_type": "other",
            "description": "Renewal of 3-year office lease for downtown headquarters.",
            "parties": [
                {"name": "Clause Inc.", "role": "tenant", "email": "ops@clause.io", "organization": "Clause Inc."},
                {"name": "Metro Properties LLC", "role": "landlord", "email": "leasing@metroprops.com", "organization": "Metro Properties LLC"},
            ],
            "start_date": datetime(2026, 7, 1),
            "end_date": datetime(2029, 7, 1),
            "value": 360000.00,
            "payment_terms": "Monthly - $10,000/month",
            "status": "draft",
            "workflow_stage": "request",
            "approval_type": "all_required",
            "workflow_trigger": "renewal",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": None,
            "created_by": "user_seed_user_002",
            "organization_id": "clause_inc",
            "tags": ["lease", "office", "renewal"],
            "template_id": None,
            "created_at": datetime(2026, 3, 30),
            "updated_at": datetime(2026, 3, 30),
        },
        {
            "title": "Marketing Agency Retainer - BrightSpark",
            "contract_type": "service_agreement",
            "description": "Monthly retainer for digital marketing services.",
            "parties": [
                {"name": "Clause Inc.", "role": "client", "email": "marketing@clause.io", "organization": "Clause Inc."},
                {"name": "BrightSpark Agency", "role": "provider", "email": "accounts@brightspark.co", "organization": "BrightSpark Agency"},
            ],
            "start_date": datetime(2026, 1, 1),
            "end_date": datetime(2026, 12, 31),
            "value": 96000.00,
            "payment_terms": "Monthly - $8,000/month",
            "status": "active",
            "workflow_stage": "monitoring",
            "approval_type": "first_person",
            "workflow_trigger": "creation",
            "file_url": None,
            "versions": [],
            "current_version": 1,
            "ai_analysis": {
                "summary": "Standard marketing retainer. 30-day termination notice. Deliverables well-defined.",
                "extracted_clauses": ["Scope of Services", "Deliverables", "Termination Notice", "IP Ownership", "Payment Terms"],
                "key_information": {"retainer": "$8,000/month", "notice_period": "30 days"},
                "risk_score": 18.0,
                "risk_level": "low",
                "analyzed_at": datetime(2026, 1, 3),
            },
            "created_by": "user_seed_user_001",
            "organization_id": "clause_inc",
            "tags": ["marketing", "retainer", "agency"],
            "template_id": None,
            "created_at": datetime(2025, 12, 15),
            "updated_at": datetime(2026, 1, 5),
        },
    ]
    result = contracts_collection.insert_many(contracts)
    print(f"Inserted {len(result.inserted_ids)} contracts.")
    return result.inserted_ids


def seed_workflows(contract_ids):
    def make_steps(completed_up_to=0):
        steps = [
            {"step_number": 1, "name": "Request & Initiation", "step_type": "review"},
            {"step_number": 2, "name": "Authoring & Drafting", "step_type": "review"},
            {"step_number": 3, "name": "AI Risk Analysis", "step_type": "ai_analysis"},
            {"step_number": 4, "name": "Review & Negotiation", "step_type": "review"},
            {"step_number": 5, "name": "Approval", "step_type": "approval"},
            {"step_number": 6, "name": "Execution & Signing", "step_type": "signing"},
            {"step_number": 7, "name": "Storage & Repository", "step_type": "notification"},
            {"step_number": 8, "name": "Monitoring & Obligations", "step_type": "review"},
            {"step_number": 9, "name": "Renewal / Expiration", "step_type": "review"},
        ]
        for s in steps:
            if s["step_number"] <= completed_up_to:
                s["status"] = "completed"
                s["completed_at"] = datetime(2026, 1, s["step_number"])
            elif s["step_number"] == completed_up_to + 1:
                s["status"] = "in_progress"
            else:
                s["status"] = "pending"
        return steps

    workflows = [
        {
            "contract_id": str(contract_ids[0]),
            "name": "Acme NDA Workflow",
            "status": "active",
            "steps": make_steps(7),
            "current_step": 8,
            "created_by": "user_seed_user_001",
            "created_at": datetime(2025, 12, 20),
            "updated_at": datetime(2026, 1, 10),
            "completed_at": None,
        },
        {
            "contract_id": str(contract_ids[1]),
            "name": "CloudHost Agreement Workflow",
            "status": "active",
            "steps": make_steps(7),
            "current_step": 8,
            "created_by": "user_seed_manager_001",
            "created_at": datetime(2026, 1, 15),
            "updated_at": datetime(2026, 2, 10),
            "completed_at": None,
        },
        {
            "contract_id": str(contract_ids[3]),
            "name": "DataSecure Vendor Workflow",
            "status": "active",
            "steps": make_steps(3),
            "current_step": 4,
            "created_by": "user_seed_user_001",
            "created_at": datetime(2026, 3, 10),
            "updated_at": datetime(2026, 3, 16),
            "completed_at": None,
        },
        {
            "contract_id": str(contract_ids[4]),
            "name": "TechBridge Licensing Workflow",
            "status": "active",
            "steps": make_steps(4),
            "current_step": 5,
            "created_by": "user_seed_admin_001",
            "created_at": datetime(2026, 3, 20),
            "updated_at": datetime(2026, 3, 28),
            "completed_at": None,
        },
    ]
    result = workflows_collection.insert_many(workflows)
    print(f"Inserted {len(result.inserted_ids)} workflows.")
    return result.inserted_ids


def seed_approvals(contract_ids):
    approvals = [
        {
            "contract_id": str(contract_ids[4]),
            "workflow_id": None,
            "approval_type": "majority",
            "status": "pending",
            "approvers": [
                {"user_id": "user_seed_admin_001", "user_email": "admin@clause.io", "decision": "approved", "comments": "Looks good. Pricing is competitive.", "decided_at": datetime(2026, 3, 27)},
                {"user_id": "user_seed_manager_001", "user_email": "michael.chen@clause.io", "decision": None, "comments": None, "decided_at": None},
            ],
            "due_date": datetime(2026, 4, 5),
            "created_by": "user_seed_admin_001",
            "created_at": datetime(2026, 3, 25),
            "updated_at": datetime(2026, 3, 27),
            "decided_at": None,
        },
        {
            "contract_id": str(contract_ids[3]),
            "workflow_id": None,
            "approval_type": "all_required",
            "status": "pending",
            "approvers": [
                {"user_id": "user_seed_admin_001", "user_email": "admin@clause.io", "decision": None, "comments": None, "decided_at": None},
                {"user_id": "user_seed_manager_001", "user_email": "michael.chen@clause.io", "decision": None, "comments": None, "decided_at": None},
            ],
            "due_date": datetime(2026, 4, 10),
            "created_by": "user_seed_user_001",
            "created_at": datetime(2026, 3, 16),
            "updated_at": datetime(2026, 3, 16),
            "decided_at": None,
        },
        {
            "contract_id": str(contract_ids[0]),
            "workflow_id": None,
            "approval_type": "all_required",
            "status": "approved",
            "approvers": [
                {"user_id": "user_seed_admin_001", "user_email": "admin@clause.io", "decision": "approved", "comments": "Approved.", "decided_at": datetime(2025, 12, 28)},
                {"user_id": "user_seed_manager_001", "user_email": "michael.chen@clause.io", "decision": "approved", "comments": "LGTM", "decided_at": datetime(2025, 12, 29)},
            ],
            "due_date": datetime(2026, 1, 5),
            "created_by": "user_seed_user_001",
            "created_at": datetime(2025, 12, 22),
            "updated_at": datetime(2025, 12, 29),
            "decided_at": datetime(2025, 12, 29),
        },
    ]
    result = approvals_collection.insert_many(approvals)
    print(f"Inserted {len(result.inserted_ids)} approvals.")
    return result.inserted_ids


def seed_notifications():
    notifications = [
        {
            "user_id": "user_seed_manager_001",
            "notification_type": "approval_required",
            "title": "Approval Needed: TechBridge Licensing Agreement",
            "message": "You have a pending approval for the TechBridge Licensing Agreement. Please review and vote by April 5, 2026.",
            "contract_id": None,
            "workflow_id": None,
            "link": "/contracts",
            "is_read": False,
            "created_at": datetime(2026, 3, 25),
        },
        {
            "user_id": "user_seed_admin_001",
            "notification_type": "approval_required",
            "title": "Approval Needed: DataSecure Vendor Agreement",
            "message": "The DataSecure Vendor Agreement requires your approval. High risk items have been flagged.",
            "contract_id": None,
            "workflow_id": None,
            "link": "/contracts",
            "is_read": False,
            "created_at": datetime(2026, 3, 16),
        },
        {
            "user_id": "user_seed_user_001",
            "notification_type": "contract_expiring",
            "title": "Contract Expiring: BrightSpark Marketing Retainer",
            "message": "The BrightSpark Agency retainer agreement expires on December 31, 2026. Consider initiating renewal.",
            "contract_id": None,
            "link": "/contracts",
            "is_read": False,
            "created_at": datetime(2026, 3, 30),
        },
        {
            "user_id": "user_seed_user_001",
            "notification_type": "workflow_update",
            "title": "Workflow Update: DataSecure Vendor Agreement",
            "message": "AI Risk Analysis completed for the DataSecure agreement. Risk level: HIGH (72/100).",
            "contract_id": None,
            "link": "/contracts",
            "is_read": True,
            "created_at": datetime(2026, 3, 16),
        },
        {
            "user_id": "user_seed_admin_001",
            "notification_type": "status_change",
            "title": "Contract Signed: Alex Kim Employment Contract",
            "message": "The employment contract for Alex Kim has been fully executed.",
            "contract_id": None,
            "link": "/contracts",
            "is_read": True,
            "created_at": datetime(2026, 3, 1),
        },
        {
            "user_id": "user_seed_manager_001",
            "notification_type": "system",
            "title": "New Contract Created: Strategic Partnership - InnovateCo",
            "message": "Sarah Johnson created a new partnership contract with InnovateCo.",
            "contract_id": None,
            "link": "/contracts",
            "is_read": True,
            "created_at": datetime(2026, 3, 25),
        },
    ]
    result = notifications_collection.insert_many(notifications)
    print(f"Inserted {len(result.inserted_ids)} notifications.")
    return result.inserted_ids


def seed_audit_logs(contract_ids):
    logs = [
        {
            "action": "create",
            "resource_type": "contract",
            "resource_id": str(contract_ids[0]),
            "user_id": "user_seed_user_001",
            "user_email": "emily.davis@clause.io",
            "details": "Created NDA contract with Acme Corp.",
            "changes": None,
            "ip_address": "192.168.1.10",
            "created_at": datetime(2025, 12, 20),
        },
        {
            "action": "ai_analysis",
            "resource_type": "contract",
            "resource_id": str(contract_ids[0]),
            "user_id": "user_seed_user_001",
            "user_email": "emily.davis@clause.io",
            "details": "AI analysis completed. Risk score: 15 (Low).",
            "changes": None,
            "ip_address": "192.168.1.10",
            "created_at": datetime(2026, 1, 2),
        },
        {
            "action": "approval_vote",
            "resource_type": "approval",
            "resource_id": str(contract_ids[0]),
            "user_id": "user_seed_admin_001",
            "user_email": "admin@clause.io",
            "details": "Approved Acme Corp NDA.",
            "changes": {"status": {"old": "pending", "new": "approved"}},
            "ip_address": "192.168.1.5",
            "created_at": datetime(2025, 12, 28),
        },
        {
            "action": "create",
            "resource_type": "contract",
            "resource_id": str(contract_ids[1]),
            "user_id": "user_seed_manager_001",
            "user_email": "michael.chen@clause.io",
            "details": "Created CloudHost Pro Service Agreement.",
            "changes": None,
            "ip_address": "192.168.1.15",
            "created_at": datetime(2026, 1, 15),
        },
        {
            "action": "create",
            "resource_type": "contract",
            "resource_id": str(contract_ids[3]),
            "user_id": "user_seed_user_001",
            "user_email": "emily.davis@clause.io",
            "details": "Created DataSecure Vendor Agreement.",
            "changes": None,
            "ip_address": "192.168.1.10",
            "created_at": datetime(2026, 3, 10),
        },
        {
            "action": "ai_analysis",
            "resource_type": "contract",
            "resource_id": str(contract_ids[3]),
            "user_id": "user_seed_user_001",
            "user_email": "emily.davis@clause.io",
            "details": "AI analysis completed. Risk score: 72 (High). Unlimited liability clause flagged.",
            "changes": None,
            "ip_address": "192.168.1.10",
            "created_at": datetime(2026, 3, 16),
        },
        {
            "action": "status_change",
            "resource_type": "contract",
            "resource_id": str(contract_ids[2]),
            "user_id": "user_seed_manager_001",
            "user_email": "michael.chen@clause.io",
            "details": "Contract moved to execution stage.",
            "changes": {"workflow_stage": {"old": "approval", "new": "execution"}},
            "ip_address": "192.168.1.15",
            "created_at": datetime(2026, 3, 1),
        },
        {
            "action": "create",
            "resource_type": "contract",
            "resource_id": str(contract_ids[5]),
            "user_id": "user_seed_admin_001",
            "user_email": "admin@clause.io",
            "details": "Created Strategic Partnership contract with InnovateCo.",
            "changes": None,
            "ip_address": "192.168.1.5",
            "created_at": datetime(2026, 3, 25),
        },
        {
            "action": "login",
            "resource_type": "user",
            "resource_id": "user_seed_admin_001",
            "user_id": "user_seed_admin_001",
            "user_email": "admin@clause.io",
            "details": "User logged in.",
            "changes": None,
            "ip_address": "192.168.1.5",
            "created_at": datetime(2026, 3, 31),
        },
    ]
    result = audit_logs_collection.insert_many(logs)
    print(f"Inserted {len(result.inserted_ids)} audit logs.")
    return result.inserted_ids


def main():
    print("Seeding Clause database...\n")
    clear_all()

    seed_users()
    seed_templates()
    contract_ids = seed_contracts()
    seed_workflows(contract_ids)
    seed_approvals(contract_ids)
    seed_notifications()
    seed_audit_logs(contract_ids)

    print("\nDone! Database seeded successfully.")
    print(f"\nSummary:")
    print(f"  Users:         {users_collection.count_documents({})}")
    print(f"  Templates:     {templates_collection.count_documents({})}")
    print(f"  Contracts:     {contracts_collection.count_documents({})}")
    print(f"  Workflows:     {workflows_collection.count_documents({})}")
    print(f"  Approvals:     {approvals_collection.count_documents({})}")
    print(f"  Notifications: {notifications_collection.count_documents({})}")
    print(f"  Audit Logs:    {audit_logs_collection.count_documents({})}")


if __name__ == "__main__":
    main()
