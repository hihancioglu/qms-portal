import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile, Request
from sqlalchemy.orm import Session
from .models import AuditLog, Document, Revision, User

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/app/storage"))
DOCS_DIR = STORAGE_DIR / "documents"
VERSIONS_DIR = STORAGE_DIR / "versions"
PUBLISHED_DIR = STORAGE_DIR / "published"

for d in (DOCS_DIR, VERSIONS_DIR, PUBLISHED_DIR):
    d.mkdir(parents=True, exist_ok=True)

def audit(db: Session, user: User | None, action: str, entity_type: str, entity_id: int | None, details: str | None, request: Request | None = None):
    ip = request.client.host if request and request.client else None
    row = AuditLog(user_id=user.id if user else None, action=action, entity_type=entity_type, entity_id=entity_id, details=details, ip_address=ip)
    db.add(row)
    db.commit()

def safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return ext if ext in [".docx", ".xlsx", ".pptx", ".pdf", ".odt", ".ods", ".odp"] else ".bin"

async def save_upload(upload: UploadFile, prefix: str) -> tuple[str, str]:
    ext = safe_ext(upload.filename or "file.bin")
    stored_name = f"{prefix}_{uuid.uuid4().hex}{ext}"
    path = DOCS_DIR / stored_name
    with path.open("wb") as f:
        while chunk := await upload.read(1024 * 1024):
            f.write(chunk)
    return str(path), upload.filename or stored_name

def make_new_revision_no(current: str | None) -> str:
    if not current:
        return "00"
    try:
        return f"{int(current) + 1:02d}"
    except ValueError:
        return f"{current}-1"

def publish_revision(db: Session, document: Document, revision: Revision):
    ext = Path(revision.source_filename).suffix.lower()
    published_name = f"{document.code}_Rev{revision.revision_no}{ext}"
    published_path = PUBLISHED_DIR / published_name
    shutil.copyfile(revision.storage_path, published_path)

    for rev in document.revisions:
        if rev.id != revision.id and rev.status == "published":
            rev.status = "obsolete"
    revision.status = "published"
    revision.published_path = str(published_path)
    revision.updated_at = datetime.utcnow()
    document.status = "published"
    document.current_revision_id = revision.id
    document.updated_at = datetime.utcnow()
    db.commit()
