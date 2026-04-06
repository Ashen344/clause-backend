import os
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse
from bson import ObjectId
from io import BytesIO
from app.config import contracts_collection, fs
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/api/documents", tags=["Documents"])

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".rtf": "application/rtf",
    ".odt": "application/vnd.oasis.opendocument.text",
}


@router.post("/upload/{contract_id}")
async def upload_document(
    contract_id: str,
    file: UploadFile = File(...),
    change_notes: str = Form(default=""),
    current_user: dict = Depends(get_current_user),
):
    """Upload a document to a contract. Stored in MongoDB GridFS."""
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

    # Store file in GridFS (MongoDB)
    gridfs_id = fs.put(
        content,
        filename=file.filename,
        content_type=MIME_TYPES.get(ext, "application/octet-stream"),
        contract_id=contract_id,
        uploaded_by=current_user["user_id"],
        uploaded_at=datetime.utcnow(),
    )

    # Build version entry
    current_version = contract.get("current_version", 0)
    new_version = current_version + 1

    version_entry = {
        "version_number": new_version,
        "gridfs_id": str(gridfs_id),
        "original_filename": file.filename,
        "file_size": len(content),
        "file_type": ext,
        "uploaded_by": current_user["user_id"],
        "uploaded_at": datetime.utcnow(),
        "change_notes": change_notes or None,
    }

    # Update contract in DB
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {
            "$push": {"versions": version_entry},
            "$set": {
                "current_version": new_version,
                "current_gridfs_id": str(gridfs_id),
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
        "gridfs_id": str(gridfs_id),
    }


@router.get("/download/{contract_id}")
async def download_document(
    contract_id: str,
    version: int = 0,
    current_user: dict = Depends(get_current_user),
):
    """Download a document from GridFS. If version=0 (default), downloads the latest."""
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

    gridfs_id = target.get("gridfs_id")
    if not gridfs_id or not ObjectId.is_valid(gridfs_id):
        raise HTTPException(status_code=404, detail="File reference not found")

    # Retrieve from GridFS
    try:
        grid_file = fs.get(ObjectId(gridfs_id))
    except Exception:
        raise HTTPException(status_code=404, detail="File not found in database")

    original_name = target.get("original_filename", "document")
    content_type = MIME_TYPES.get(target.get("file_type", ""), "application/octet-stream")

    return StreamingResponse(
        BytesIO(grid_file.read()),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{original_name}"'},
    )


@router.get("/list/{contract_id}")
async def list_documents(
    contract_id: str,
    current_user: dict = Depends(get_current_user),
):
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
                "original_filename": v.get("original_filename", ""),
                "file_size": v.get("file_size"),
                "file_type": v.get("file_type"),
                "uploaded_by": v.get("uploaded_by"),
                "uploaded_at": v.get("uploaded_at"),
                "change_notes": v.get("change_notes"),
                "gridfs_id": v.get("gridfs_id"),
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

    # Remove file from GridFS
    gridfs_id = target.get("gridfs_id")
    if gridfs_id and ObjectId.is_valid(gridfs_id):
        try:
            fs.delete(ObjectId(gridfs_id))
        except Exception:
            pass  # File may already be deleted

    # Remove from DB
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$pull": {"versions": {"version_number": version_number}}},
    )

    # Update current version if needed
    remaining = [v for v in versions if v["version_number"] != version_number]
    new_current = remaining[-1]["version_number"] if remaining else 0
    new_gridfs = remaining[-1].get("gridfs_id") if remaining else None

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {
            "current_version": new_current,
            "current_gridfs_id": new_gridfs,
            "updated_at": datetime.utcnow(),
        }},
    )

    return {"message": f"Version {version_number} deleted successfully"}
