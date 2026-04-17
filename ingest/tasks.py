"""
tasks.py — RQ task definitions.

Each function here is imported by the RQ worker process.
They must be importable at module level (no __main__ guard).
"""

from ingest import ingest_document


def analyze_contract(file_path: str, doc_type: str = "SLA", customer: str = "Unknown"):
    """
    RQ task: extract, embed, and index a single PDF asynchronously.
    This is a thin wrapper so the queue always calls a named task.
    """
    ingest_document(file_path, doc_type=doc_type, customer=customer)
    return {"file": file_path, "doc_type": doc_type, "customer": customer, "status": "indexed"}

