"""
upload.py — Save an uploaded file to local disk and enqueue an async ingestion job.

Usage (standalone):
    python upload.py /path/to/contract.pdf --doc-type SLA --customer Acme

Importable API:
    from upload import upload_contract
    result = upload_contract(file_bytes, filename="contract.pdf", doc_type="SLA", customer="Acme")
"""

import os
import sys
import uuid
import logging
import argparse
from redis import Redis
from rq import Queue
from tasks import analyze_contract

logger = logging.getLogger(__name__)

# --- Configuration ---
REDIS_HOST   = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT   = int(os.environ.get("REDIS_PORT", 6379))
UPLOAD_DIR   = os.environ.get("UPLOAD_DIR", "/data/uploads")
QUEUE_NAME   = os.environ.get("QUEUE_NAME", "contract_tasks")
JOB_TIMEOUT  = int(os.environ.get("JOB_TIMEOUT", 600))   # seconds per job

MAX_FILE_SIZE = 50 * 1024 * 1024   # 50 MB in bytes

ALLOWED_EXTENSIONS = {
    ".pdf", ".txt", ".csv", ".json",
    ".docx", ".xlsx", ".html", ".htm", ".md"
}

os.makedirs(UPLOAD_DIR, exist_ok=True)

redis_conn = Redis(host=REDIS_HOST, port=REDIS_PORT)
queue = Queue(QUEUE_NAME, connection=redis_conn)


def _validate_upload(file_data: bytes, filename: str) -> None:
    """
    Raise ValueError with a clear message if the upload is invalid.

    Checks:
      - File size does not exceed MAX_FILE_SIZE (50 MB).
      - File extension is in ALLOWED_EXTENSIONS.
    """
    size = len(file_data)
    if size > MAX_FILE_SIZE:
        raise ValueError(
            f"File '{filename}' is too large: {size / (1024 * 1024):.1f} MB "
            f"(maximum allowed: {MAX_FILE_SIZE // (1024 * 1024)} MB)."
        )

    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        raise ValueError(
            f"File '{filename}' has no extension. "
            f"Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type '{ext}' is not allowed for '{filename}'. "
            f"Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )


def save_to_disk(file_data: bytes, filename: str) -> str:
    """
    Write raw bytes to UPLOAD_DIR with a collision-safe name.
    Returns the absolute path of the saved file.
    """
    safe_name = f"{uuid.uuid4().hex}_{os.path.basename(filename)}"
    dest = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest, "wb") as f:
        f.write(file_data)
    logger.info("Saved: %s", dest)
    return dest


def upload_contract(
    file_data: bytes,
    filename: str = "contract.pdf",
    doc_type: str = "SLA",
    customer: str = "Unknown",
) -> dict:
    """
    1. Validate the upload (size and extension).
    2. Persist the file to local disk.
    3. Enqueue analyze_contract as a background RQ job.
    Returns immediately with the job ID.
    Raises ValueError if validation fails.
    """
    _validate_upload(file_data, filename)

    file_path = save_to_disk(file_data, filename)

    job = queue.enqueue(
        analyze_contract,
        file_path,
        doc_type,
        customer,
        job_timeout=JOB_TIMEOUT,
    )

    result = {"status": "processing", "job_id": job.id, "file": os.path.basename(file_path)}
    logger.info("Enqueued job %s for %s", job.id, filename)
    return result


def job_status(job_id: str) -> dict:
    """Fetch the current status of an RQ job by ID."""
    from rq.job import Job
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        result = {
            "job_id":   job_id,
            "status":   job.get_status().value,
            "result":   job.result,
            "error":    str(job.exc_info) if job.exc_info else None,
        }
    except Exception as e:
        result = {"job_id": job_id, "status": "not_found", "error": str(e)}
    return result


# --- CLI for local testing ---
def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    parser = argparse.ArgumentParser(description="Upload a file and enqueue async ingestion")
    parser.add_argument("file",        help="Path to a local file to upload")
    parser.add_argument("--doc-type",  default="SLA",     help="Document type (SLA, MSA, SOW ...)")
    parser.add_argument("--customer",  default="Unknown", help="Customer name")
    parser.add_argument("--status",    metavar="JOB_ID",  help="Check status of an existing job")
    args = parser.parse_args()

    if args.status:
        import json
        logger.info("Job status: %s", json.dumps(job_status(args.status), indent=2))
        return

    if not os.path.isfile(args.file):
        logger.error("File not found: %s", args.file)
        sys.exit(1)

    with open(args.file, "rb") as f:
        data = f.read()

    try:
        import json
        result = upload_contract(data, filename=os.path.basename(args.file),
                                 doc_type=args.doc_type, customer=args.customer)
        logger.info("Upload result: %s", json.dumps(result, indent=2))
    except ValueError as e:
        logger.error("Upload rejected: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
