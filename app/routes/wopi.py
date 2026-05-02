"""
WOPI protocol endpoints for Collabora Online (LibreOffice in browser).

Collabora calls these to read/write contract documents:
  GET  /wopi/files/{contract_id}           — CheckFileInfo
  GET  /wopi/files/{contract_id}/contents  — GetFile
  POST /wopi/files/{contract_id}/contents  — PutFile
"""

import hashlib
import hmac
import os
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.config import contracts_collection, SECRET_KEY

router = APIRouter(prefix="/wopi", tags=["WOPI"])

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"
)

_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt":  "application/vnd.oasis.opendocument.text",
    ".doc":  "application/msword",
    ".pdf":  "application/pdf",
    ".txt":  "text/plain",
    ".rtf":  "application/rtf",
}


def make_wopi_token(contract_id: str) -> str:
    return hmac.new(
        SECRET_KEY.encode(),
        contract_id.encode(),
        hashlib.sha256,
    ).hexdigest()


def _verify(contract_id: str, token: str) -> bool:
    # Collabora appends ?permission=readonly (URL-encoded as %3F...) for view mode.
    # Strip any query-string suffix before comparing.
    clean = token.split("?")[0]
    return hmac.compare_digest(make_wopi_token(contract_id), clean)


def _latest(contract: dict) -> dict | None:
    """Return a version-like dict for the contract's current file."""
    file_url = contract.get("file_url")
    if not file_url:
        versions = contract.get("versions", [])
        return versions[-1] if versions else None
    # Build a synthetic version entry from top-level fields
    _, ext = os.path.splitext(file_url)
    versions = contract.get("versions", [])
    # Use version metadata but override file_url with the current active file
    base = versions[-1].copy() if versions else {}
    base["file_url"] = file_url
    base["file_type"] = ext.lower() or base.get("file_type", ".docx")
    return base


@router.get("/files/{contract_id}")
async def check_file_info(contract_id: str, access_token: str = ""):
    if not _verify(contract_id, access_token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=404)

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404)

    v = _latest(contract)
    if not v:
        raise HTTPException(status_code=404, detail="No document attached")

    file_path = os.path.join(UPLOAD_DIR, v["file_url"])
    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    modified = v.get("uploaded_at", datetime.utcnow())
    if isinstance(modified, datetime):
        modified = modified.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    return {
        "BaseFileName": v.get("original_filename", "document.docx"),
        "Size": size,
        "OwnerId": contract.get("created_by", "clause"),
        "UserId": "clause-user",
        "UserFriendlyName": "Clause User",
        "UserCanWrite": True,
        "UserCanNotWriteRelative": True,
        "SupportsUpdate": True,
        "SupportsLocks": False,
        "LastModifiedTime": modified,
    }


@router.get("/files/{contract_id}/contents")
async def get_file(contract_id: str, access_token: str = ""):
    if not _verify(contract_id, access_token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=404)

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404)

    v = _latest(contract)
    if not v:
        raise HTTPException(status_code=404)

    file_path = os.path.join(UPLOAD_DIR, v["file_url"])
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404)

    return FileResponse(
        path=file_path,
        media_type=_MIME.get(v.get("file_type", ".docx"), "application/octet-stream"),
    )


@router.post("/files/{contract_id}/contents")
async def put_file(contract_id: str, request: Request, access_token: str = ""):
    if not _verify(contract_id, access_token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=404)

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404)

    v = _latest(contract)
    if not v:
        raise HTTPException(status_code=404)

    file_path = os.path.join(UPLOAD_DIR, v["file_url"])
    content = await request.body()
    with open(file_path, "wb") as f:
        f.write(content)

    idx = len(contract.get("versions", [])) - 1
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {
            "updated_at": datetime.utcnow(),
            f"versions.{idx}.uploaded_at": datetime.utcnow(),
        }},
    )
    return Response(status_code=200)
