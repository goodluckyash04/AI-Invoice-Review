import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db import Base


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class Outcome(str, enum.Enum):
    VALID = "valid"
    EXCEPTION_DETECTED = "exception_detected"
    NEEDS_REVIEW = "needs_review"


class ReviewDecisionEnum(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def _uuid() -> str:
    return str(uuid.uuid4())


class InvoiceJob(Base):
    __tablename__ = "invoice_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    invoice_id = Column(String, nullable=False, index=True)
    carrier_id = Column(String, nullable=False)
    raw_payload = Column(Text, nullable=False)
    status = Column(
        Enum(JobStatus, native_enum=False),
        default=JobStatus.PENDING,
        nullable=False,
        index=True,
    )
    idempotency_key = Column(String, nullable=True, unique=True)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    result = relationship("InvoiceResult", back_populates="job", uselist=False)
    review = relationship("ReviewDecision", back_populates="job", uselist=False)
    audit_events = relationship("AuditEvent", back_populates="job", order_by="AuditEvent.created_at")


class InvoiceResult(Base):
    __tablename__ = "invoice_results"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("invoice_jobs.id"), nullable=False, unique=True)
    outcome = Column(Enum(Outcome, native_enum=False), nullable=False)
    exceptions = Column(Text, nullable=True)
    disputed_amount = Column(Float, nullable=True)
    explanation = Column(Text, nullable=True)
    evidence_refs = Column(Text, nullable=True)
    ai_raw_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("InvoiceJob", back_populates="result")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("invoice_jobs.id"), nullable=False, unique=True)
    reviewer_id = Column(String, nullable=False)
    decision = Column(Enum(ReviewDecisionEnum, native_enum=False), nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("InvoiceJob", back_populates="review")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("invoice_jobs.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("InvoiceJob", back_populates="audit_events")


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(String, primary_key=True, default=_uuid)
    carrier_id = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    content_path = Column(String, nullable=False)
    extracted_terms = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(String, primary_key=True, default=_uuid)
    tracking_id = Column(String, unique=True, nullable=False, index=True)
    carrier_id = Column(String, nullable=False)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    weight_kg = Column(Float, nullable=False)
    service_type = Column(String, nullable=False)
    zone = Column(Integer, nullable=False)
    ship_date = Column(Date, nullable=False)
    delivered_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
