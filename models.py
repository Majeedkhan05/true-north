"""ORM models + Pydantic request/response schemas.

Tables: brokerages, documents, audit_logs  (mirror of schema.sql).
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ===========================================================================
#  ORM models
# ===========================================================================
class Brokerage(Base):
    __tablename__ = "brokerages"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    language = Column(String, nullable=False, default="en")  # 'en' | 'fr'
    postal_code = Column(String, nullable=True)
    plan = Column(String, nullable=False, default="starter")  # starter|pro|enterprise
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="inactive")  # active|inactive|past_due|canceled
    # Quota: doc_limit = NULL means unlimited (enterprise). docs_used resets each
    # billing cycle (see reset_quota_if_new_cycle()).
    doc_limit = Column(Integer, nullable=True, default=100)
    docs_used = Column(Integer, nullable=False, default=0)
    quota_period_start = Column(DateTime(timezone=True), default=_now)
    created_at = Column(DateTime(timezone=True), default=_now)

    documents = relationship("Document", back_populates="brokerage")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    brokerage_id = Column(String, ForeignKey("brokerages.id"), nullable=False, index=True)
    file_hash = Column(String, nullable=False, index=True)  # SHA256 for dedup
    file_path = Column(String, nullable=True)  # Supabase storage path
    extracted_json = Column(JSON, nullable=True)
    confidence_score = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="processed")  # processed|approved|failed
    draft_email = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    compliance = Column(JSON, nullable=True)      # Feature 4: validation results
    opportunities = Column(JSON, nullable=True)   # Feature 5: recommendations
    created_at = Column(DateTime(timezone=True), default=_now)

    brokerage = relationship("Brokerage", back_populates="documents")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brokerage_id = Column(String, ForeignKey("brokerages.id"), nullable=True, index=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=True, index=True)
    action = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=_now)
    ip_address = Column(String, nullable=True)


# ===========================================================================
#  Pydantic schemas (API contracts)
# ===========================================================================
class BrokerageCreate(BaseModel):
    email: EmailStr
    name: str
    postal_code: Optional[str] = None
    plan: str = Field(default="starter", pattern="^(starter|pro|enterprise)$")
    language: Optional[str] = None  # auto-derived from postal code if omitted


class BrokerageOut(BaseModel):
    id: str
    email: str
    name: str
    language: str
    postal_code: Optional[str]
    plan: str
    status: str
    doc_limit: Optional[int]
    docs_used: int
    stripe_customer_id: Optional[str]
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    brokerage_id: str
    file_hash: str
    file_path: Optional[str]
    extracted_json: Optional[dict[str, Any]]
    confidence_score: Optional[float]
    status: str
    draft_email: Optional[str]
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class ProcessResult(BaseModel):
    status: str = "SUCCESS"  # n8n contract: 200 -> SUCCESS
    document_id: str
    extracted_json: dict[str, Any]
    draft_email: str
    confidence_score: float
    duplicate: bool = False
    # Fields the n8n control plane routes on (top-level, non-PII)
    language: str = "en"
    broker_email: Optional[str] = None
    approval_token: Optional[str] = None


class ApprovalResult(BaseModel):
    status: str  # approved | already_approved
    document_id: str
    language: str = "en"


class RetryRequest(BaseModel):
    document_id: Optional[str] = None


class CheckDuplicateRequest(BaseModel):
    brokerage_id: str
    file_hash: str


class CheckDuplicateResult(BaseModel):
    duplicate: bool
    document_id: Optional[str] = None


class AuditEvent(BaseModel):
    brokerage_id: Optional[str] = None
    document_id: Optional[str] = None
    action: str
    ip_address: Optional[str] = None


class ApproveResult(BaseModel):
    document_id: str
    status: str
    approved_at: dt.datetime


class RenewalTask(Base):
    """Feature 3: renewal workflow — one task per policy approaching expiry."""
    __tablename__ = "renewal_tasks"
    id            = Column(String, primary_key=True, default=_uuid)
    brokerage_id  = Column(String, nullable=False, index=True)
    document_id   = Column(String, nullable=False)
    policy_number = Column(String, nullable=True)
    named_insured = Column(String, nullable=True)
    expiry_date   = Column(String, nullable=False)
    status        = Column(String, nullable=False, default="pending")  # pending|approved|sent|completed|overdue
    draft_email   = Column(Text, nullable=True)
    language      = Column(String, nullable=False, default="en")
    created_at    = Column(DateTime(timezone=True), default=_now)
    updated_at    = Column(DateTime(timezone=True), default=_now, onupdate=_now)
