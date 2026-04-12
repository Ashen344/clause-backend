import os
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse
from bson import ObjectId
from app.config import contracts_collection
from app.middleware.auth import get_current_user, get_optional_user

MIME_MAP = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".rtf": "application/rtf",
    ".odt": "application/vnd.oasis.opendocument.text",
}

router = APIRouter(prefix="/api/documents", tags=["Documents"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/upload/{contract_id}")
async def upload_document(
    contract_id: str,
    file: UploadFile = File(...),
    change_notes: str = Form(default=""),
    current_user: dict = Depends(get_optional_user),
):
    """Upload a document to a contract."""
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Validate file extension
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read file content
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 20MB limit")

    # Save file to disk
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_id = uuid.uuid4().hex
    stored_filename = f"{file_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # Build version entry
    current_version = contract.get("current_version", 0)
    new_version = current_version + 1
    user_id = current_user["user_id"] if current_user else "unknown"

    version_entry = {
        "version_number": new_version,
        "file_url": stored_filename,
        "original_filename": file.filename,
        "file_size": len(content),
        "file_type": ext,
        "uploaded_by": user_id,
        "uploaded_at": datetime.utcnow(),
        "change_notes": change_notes or None,
    }

    # Update contract in DB
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {
            "$push": {"versions": version_entry},
            "$set": {
                "file_url": stored_filename,
                "current_version": new_version,
                "updated_at": datetime.utcnow(),
            },
        },
    )

    return {
        "message": "Document uploaded successfully",
        "version": new_version,
        "filename": file.filename,
        "file_size": len(content),
        "file_type": ext,
    }


@router.get("/download/{contract_id}")
async def download_document(contract_id: str, version: int = 0):
    """Download a document. If version=0 (default), downloads the latest."""
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    versions = contract.get("versions", [])
    if not versions:
        raise HTTPException(status_code=404, detail="No documents uploaded for this contract")

    # Find the requested version
    if version > 0:
        target = next((v for v in versions if v["version_number"] == version), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Version {version} not found")
    else:
        target = versions[-1]  # latest

    file_path = os.path.join(UPLOAD_DIR, target["file_url"])
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    original_name = target.get("original_filename", target["file_url"])
    return FileResponse(
        path=file_path,
        filename=original_name,
        media_type="application/octet-stream",
    )


@router.get("/view/{contract_id}")
async def view_document(contract_id: str, version: int = 0):
    """Serve a document inline so the browser can render it (PDF viewer, text, etc.)."""
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    versions = contract.get("versions", [])
    if not versions:
        raise HTTPException(status_code=404, detail="No documents uploaded for this contract")

    if version > 0:
        target = next((v for v in versions if v["version_number"] == version), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Version {version} not found")
    else:
        target = versions[-1]

    file_path = os.path.join(UPLOAD_DIR, target["file_url"])
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    ext = target.get("file_type", ".pdf")
    media_type = MIME_MAP.get(ext, "application/octet-stream")
    original_name = target.get("original_filename", target["file_url"])

    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{original_name}"'},
    )


@router.get("/list/{contract_id}")
async def list_documents(contract_id: str):
    """List all document versions for a contract."""
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    versions = contract.get("versions", [])
    return {
        "contract_id": contract_id,
        "current_version": contract.get("current_version", 0),
        "documents": [
            {
                "version_number": v.get("version_number"),
                "original_filename": v.get("original_filename", v.get("file_url", "")),
                "file_size": v.get("file_size"),
                "file_type": v.get("file_type"),
                "uploaded_by": v.get("uploaded_by"),
                "uploaded_at": v.get("uploaded_at"),
                "change_notes": v.get("change_notes"),
            }
            for v in versions
        ],
    }


@router.delete("/{contract_id}/{version_number}")
async def delete_document(
    contract_id: str,
    version_number: int,
    current_user: dict = Depends(get_current_user),
):
    """Delete a specific document version."""
    if not ObjectId.is_valid(contract_id):
        raise HTTPException(status_code=400, detail="Invalid contract ID")

    contract = contracts_collection.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    versions = contract.get("versions", [])
    target = next((v for v in versions if v["version_number"] == version_number), None)
    if not target:
        raise HTTPException(status_code=404, detail="Version not found")

    # Remove file from disk
    file_path = os.path.join(UPLOAD_DIR, target["file_url"])
    if os.path.exists(file_path):
        os.remove(file_path)

    # Remove from DB
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$pull": {"versions": {"version_number": version_number}}},
    )

    # Update current version if needed
    remaining = [v for v in versions if v["version_number"] != version_number]
    new_current = remaining[-1]["version_number"] if remaining else 0
    new_file_url = remaining[-1]["file_url"] if remaining else None

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {
            "current_version": new_current,
            "file_url": new_file_url,
            "updated_at": datetime.utcnow(),
        }},
    )

    return {"message": f"Version {version_number} deleted successfully"}
