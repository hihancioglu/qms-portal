from datetime import datetime, date
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="viewer")  # admin, quality, approver, editor, viewer
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    doc_type: Mapped[str] = mapped_column(String(80))
    department: Mapped[str] = mapped_column(String(100))
    process: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft, review, approved, published, obsolete
    current_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    created_by = relationship("User")
    revisions = relationship("Revision", back_populates="document", cascade="all, delete-orphan")

class Revision(Base):
    __tablename__ = "revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    revision_no: Mapped[str] = mapped_column(String(20))
    source_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    published_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft, review, approved, published, obsolete
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    prepared_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="revisions")
    prepared_by = relationship("User")
    approvals = relationship("Approval", back_populates="revision", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("document_id", "revision_no", name="uq_document_revision"),)

class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("revisions.id"), index=True)
    step_order: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(100))
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending, approved, rejected
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    revision = relationship("Revision", back_populates="approvals")
    approver = relationship("User")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User")

class ReadReceipt(Base):
    __tablename__ = "read_receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("revisions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    revision = relationship("Revision")
    user = relationship("User")
    __table_args__ = (UniqueConstraint("revision_id", "user_id", name="uq_revision_user_read"),)
