import os
from datetime import datetime, date
from pathlib import Path
import requests
from fastapi import FastAPI, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .db import Base, engine, get_db, SessionLocal
from .models import Approval, AuditLog, Document, ReadReceipt, Revision, User
from .auth import get_current_user, hash_password, require_roles, verify_password
from .ldap import LDAP_PASSWORD_HASH, authenticate_ldap_user, ldap_enabled, list_ldap_users
from .services import audit, make_new_revision_no, publish_revision, save_upload

APP_SECRET = os.getenv("APP_SECRET", "dev-secret")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
ONLYOFFICE_PUBLIC_URL = os.getenv("ONLYOFFICE_PUBLIC_URL", "http://localhost:8082").rstrip("/")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/app/storage"))

app = FastAPI(title="QMS Portal")
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET, same_site="lax")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin_user = os.getenv("INITIAL_ADMIN_USER", "admin")
        admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "admin123")
        exists = db.scalar(select(User).where(User.username == admin_user))
        if not exists:
            db.add(User(username=admin_user, full_name="System Admin", password_hash=hash_password(admin_password), role="admin"))
            db.commit()
    finally:
        db.close()

def current_user_or_none(request: Request, db: Session):
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), q: str = ""):
    user = current_user_or_none(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    stmt = select(Document).order_by(Document.updated_at.desc())
    if q:
        like = f"%{q}%"
        stmt = select(Document).where(or_(Document.code.ilike(like), Document.title.ilike(like), Document.department.ilike(like))).order_by(Document.updated_at.desc())
    documents = db.scalars(stmt).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "documents": documents, "q": q})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "ldap_enabled": ldap_enabled()})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    normalized_username = username.strip().split("\\")[-1].split("@")[0].lower()
    ldap_user = authenticate_ldap_user(normalized_username, password)
    authenticated_by_ldap = ldap_user is not None
    if ldap_user:
        user = db.scalar(select(User).where(User.username == ldap_user.username))
        if not user:
            user = User(
                username=ldap_user.username,
                full_name=ldap_user.full_name,
                password_hash=LDAP_PASSWORD_HASH,
                role="viewer",
                department=ldap_user.department,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.full_name = ldap_user.full_name
            user.department = ldap_user.department
            if user.password_hash == LDAP_PASSWORD_HASH:
                user.is_active = True
            db.commit()
            db.refresh(user)
    else:
        user = db.scalar(select(User).where(User.username == normalized_username))

    if not user or not user.is_active or (not authenticated_by_ldap and not verify_password(password, user.password_hash)):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Kullanıcı adı veya şifre hatalı"}, status_code=401)
    request.session["user_id"] = user.id
    audit(db, user, "login", "user", user.id, "User logged in", request)
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = current_user_or_none(request, db)
    if user:
        audit(db, user, "logout", "user", user.id, "User logged out", request)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin")
    users = db.scalars(select(User).order_by(User.username)).all()
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "ldap_enabled": ldap_enabled(),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )

@app.post("/users")
def create_user(request: Request, username: str = Form(...), full_name: str = Form(...), password: str = Form(...), role: str = Form(...), department: str = Form(""), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(400, "User already exists")
    new_user = User(username=username, full_name=full_name, password_hash=hash_password(password), role=role, department=department or None)
    db.add(new_user)
    db.commit()
    audit(db, user, "create_user", "user", new_user.id, f"Created user {username}", request)
    return RedirectResponse("/users", status_code=303)

@app.post("/users/sync-ldap")
def sync_ldap_users(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin")
    if not ldap_enabled():
        return RedirectResponse("/users?error=LDAP%20ayarlar%C4%B1%20eksik", status_code=303)
    ldap_users = list_ldap_users()
    created = 0
    updated = 0
    for ldap_user in ldap_users:
        existing = db.scalar(select(User).where(User.username == ldap_user.username))
        if existing:
            existing.full_name = ldap_user.full_name
            existing.department = ldap_user.department
            if existing.password_hash == LDAP_PASSWORD_HASH:
                existing.is_active = True
            updated += 1
            continue
        db.add(
            User(
                username=ldap_user.username,
                full_name=ldap_user.full_name,
                password_hash=LDAP_PASSWORD_HASH,
                role="viewer",
                department=ldap_user.department,
            )
        )
        created += 1
    db.commit()
    audit(db, user, "sync_ldap_users", "user", None, f"LDAP sync: {created} created, {updated} updated", request)
    return RedirectResponse(f"/users?message=LDAP%20senkronizasyonu:%20{created}%20yeni,%20{updated}%20g%C3%BCncellendi", status_code=303)

@app.get("/documents/new", response_class=HTMLResponse)
def new_document_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality", "editor")
    return templates.TemplateResponse("document_new.html", {"request": request, "user": user})

@app.post("/documents")
async def create_document(request: Request, code: str = Form(...), title: str = Form(...), doc_type: str = Form(...), department: str = Form(...), process: str = Form(""), change_note: str = Form("İlk yayın"), file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality", "editor")
    if db.scalar(select(Document).where(Document.code == code)):
        raise HTTPException(400, "Doküman kodu zaten var")
    path, original = await save_upload(file, code)
    doc = Document(code=code, title=title, doc_type=doc_type, department=department, process=process or None, created_by_id=user.id)
    db.add(doc)
    db.flush()
    rev = Revision(document_id=doc.id, revision_no="00", source_filename=original, storage_path=path, change_note=change_note, prepared_by_id=user.id)
    db.add(rev)
    db.commit()
    audit(db, user, "create_document", "document", doc.id, f"{code} Rev.00 created", request)
    return RedirectResponse(f"/documents/{doc.id}", status_code=303)

@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_detail(request: Request, doc_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404)
    current_rev = db.get(Revision, doc.current_revision_id) if doc.current_revision_id else None
    audit_logs = db.scalars(select(AuditLog).where(AuditLog.entity_type == "document", AuditLog.entity_id == doc.id).order_by(AuditLog.created_at.desc()).limit(30)).all()
    receipts = []
    if current_rev:
        receipts = db.scalars(select(ReadReceipt).where(ReadReceipt.revision_id == current_rev.id).order_by(ReadReceipt.read_at.desc())).all()
    return templates.TemplateResponse("document_detail.html", {"request": request, "user": user, "doc": doc, "current_rev": current_rev, "audit_logs": audit_logs, "receipts": receipts})

@app.post("/documents/{doc_id}/revision")
async def create_revision(request: Request, doc_id: int, change_note: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality", "editor")
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404)
    last = sorted(doc.revisions, key=lambda r: r.created_at)[-1] if doc.revisions else None
    rev_no = make_new_revision_no(last.revision_no if last else None)
    path, original = await save_upload(file, doc.code)
    rev = Revision(document_id=doc.id, revision_no=rev_no, source_filename=original, storage_path=path, change_note=change_note, prepared_by_id=user.id)
    db.add(rev)
    doc.status = "draft"
    doc.updated_at = datetime.utcnow()
    db.commit()
    audit(db, user, "create_revision", "document", doc.id, f"{doc.code} Rev.{rev_no} created", request)
    return RedirectResponse(f"/documents/{doc.id}", status_code=303)

@app.post("/revisions/{rev_id}/send-review")
def send_review(request: Request, rev_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality", "editor")
    rev = db.get(Revision, rev_id)
    if not rev:
        raise HTTPException(404)
    rev.status = "review"
    rev.document.status = "review"
    rev.updated_at = datetime.utcnow()
    if not rev.approvals:
        db.add_all([
            Approval(revision_id=rev.id, step_order=1, step_name="Kalite İnceleme"),
            Approval(revision_id=rev.id, step_order=2, step_name="Bölüm Onayı"),
            Approval(revision_id=rev.id, step_order=3, step_name="Kalite Yayın Onayı"),
        ])
    db.commit()
    audit(db, user, "send_review", "document", rev.document_id, f"Rev.{rev.revision_no} review started", request)
    return RedirectResponse(f"/documents/{rev.document_id}", status_code=303)

@app.post("/approvals/{approval_id}/act")
def act_approval(request: Request, approval_id: int, action: str = Form(...), note: str = Form(""), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality", "approver")
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404)
    rev = approval.revision
    previous_pending = [a for a in rev.approvals if a.step_order < approval.step_order and a.status == "pending"]
    if previous_pending:
        raise HTTPException(400, "Önce önceki onay adımı tamamlanmalı")
    approval.status = "approved" if action == "approve" else "rejected"
    approval.note = note or None
    approval.approver_id = user.id
    approval.acted_at = datetime.utcnow()
    if action == "reject":
        rev.status = "draft"
        rev.document.status = "draft"
    elif all(a.status == "approved" for a in rev.approvals):
        rev.status = "approved"
        rev.document.status = "approved"
    db.commit()
    audit(db, user, f"approval_{approval.status}", "document", rev.document_id, f"{approval.step_name}: {note}", request)
    return RedirectResponse(f"/documents/{rev.document_id}", status_code=303)

@app.post("/revisions/{rev_id}/publish")
def publish(request: Request, rev_id: int, effective_date: str = Form(""), review_due_date: str = Form(""), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality")
    rev = db.get(Revision, rev_id)
    if not rev:
        raise HTTPException(404)
    if rev.status != "approved" and user.role != "admin":
        raise HTTPException(400, "Sadece onaylı revizyon yayınlanabilir")
    rev.effective_date = date.fromisoformat(effective_date) if effective_date else None
    rev.review_due_date = date.fromisoformat(review_due_date) if review_due_date else None
    publish_revision(db, rev.document, rev)
    audit(db, user, "publish", "document", rev.document_id, f"Rev.{rev.revision_no} published", request)
    return RedirectResponse(f"/documents/{rev.document_id}", status_code=303)

@app.get("/revisions/{rev_id}/download")
def download_revision(request: Request, rev_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    rev = db.get(Revision, rev_id)
    if not rev:
        raise HTTPException(404)
    path = rev.published_path if rev.status == "published" and rev.published_path else rev.storage_path
    audit(db, user, "download", "document", rev.document_id, f"Rev.{rev.revision_no} downloaded", request)
    return FileResponse(path, filename=Path(path).name)

@app.post("/revisions/{rev_id}/read")
def mark_read(request: Request, rev_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    rev = db.get(Revision, rev_id)
    if not rev or rev.status != "published":
        raise HTTPException(404)
    existing = db.scalar(select(ReadReceipt).where(ReadReceipt.revision_id == rev.id, ReadReceipt.user_id == user.id))
    if not existing:
        db.add(ReadReceipt(revision_id=rev.id, user_id=user.id))
        db.commit()
        audit(db, user, "read_receipt", "document", rev.document_id, f"Rev.{rev.revision_no} read confirmed", request)
    return RedirectResponse(f"/documents/{rev.document_id}", status_code=303)

@app.get("/files/revision/{rev_id}")
def file_for_onlyoffice(rev_id: int, db: Session = Depends(get_db)):
    rev = db.get(Revision, rev_id)
    if not rev:
        raise HTTPException(404)
    return FileResponse(rev.storage_path, filename=rev.source_filename)

@app.get("/documents/{doc_id}/edit/{rev_id}", response_class=HTMLResponse)
def edit_document(request: Request, doc_id: int, rev_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality", "editor")
    rev = db.get(Revision, rev_id)
    if not rev or rev.document_id != doc_id:
        raise HTTPException(404)
    ext = Path(rev.source_filename).suffix.lower().lstrip(".") or "docx"
    config = {
        "document": {
            "fileType": ext,
            "key": f"rev-{rev.id}-{int(rev.updated_at.timestamp())}",
            "title": rev.source_filename,
            "url": f"{PUBLIC_BASE_URL}/files/revision/{rev.id}",
        },
        "documentType": "word" if ext in ["docx", "doc", "odt", "pdf"] else "cell" if ext in ["xlsx", "xls", "ods"] else "slide",
        "editorConfig": {
            "callbackUrl": f"{PUBLIC_BASE_URL}/onlyoffice/callback/{rev.id}",
            "lang": "tr",
            "user": {"id": str(user.id), "name": user.full_name},
        },
        "height": "100%",
        "width": "100%",
    }
    audit(db, user, "edit_open", "document", doc_id, f"Rev.{rev.revision_no} opened in editor", request)
    return templates.TemplateResponse("editor.html", {"request": request, "user": user, "doc": rev.document, "rev": rev, "onlyoffice_url": ONLYOFFICE_PUBLIC_URL, "config": config})

@app.post("/onlyoffice/callback/{rev_id}")
def onlyoffice_callback(rev_id: int, payload: dict, db: Session = Depends(get_db)):
    rev = db.get(Revision, rev_id)
    if not rev:
        return JSONResponse({"error": 1})
    status = payload.get("status")
    # 2 = document ready for saving, 6 = force save
    if status in [2, 6] and payload.get("url"):
        r = requests.get(payload["url"], timeout=30)
        r.raise_for_status()
        with open(rev.storage_path, "wb") as f:
            f.write(r.content)
        rev.updated_at = datetime.utcnow()
        db.commit()
        audit(db, None, "onlyoffice_save", "document", rev.document_id, f"Rev.{rev.revision_no} saved by callback")
    return JSONResponse({"error": 0})

@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_roles(user, "admin", "quality")
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
    return templates.TemplateResponse("audit.html", {"request": request, "user": user, "logs": logs})
