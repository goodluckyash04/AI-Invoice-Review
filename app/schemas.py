from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


class SurchargeItem(BaseModel):
    name: str
    amount: float = Field(..., ge=0)


class InvoiceSubmitRequest(BaseModel):
    invoice_id: str = Field(..., min_length=1, max_length=100)
    carrier_id: str = Field(..., min_length=1, max_length=50)
    tracking_id: Optional[str] = None
    service_type: str = Field(..., pattern="^(standard|express|overnight)$")
    billed_weight_kg: float = Field(..., gt=0)
    billed_amount: float = Field(..., ge=0)
    surcharges: List[SurchargeItem] = Field(default_factory=list)
    invoice_date: date
    billing_period_start: date
    billing_period_end: date

    @field_validator("carrier_id")
    @classmethod
    def normalise_carrier(cls, v: str) -> str:
        return v.strip().lower()


class InvoiceJobResponse(BaseModel):
    job_id: str
    invoice_id: str
    carrier_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class InvoiceStatusResponse(BaseModel):
    job_id: str
    invoice_id: str
    status: str
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ExceptionItem(BaseModel):
    exception_type: str
    description: str
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None
    disputed_amount: Optional[float] = None
    evidence_ref: Optional[str] = None


class FindingsResponse(BaseModel):
    job_id: str
    invoice_id: str
    outcome: str
    exceptions: List[ExceptionItem] = []
    disputed_amount: Optional[float] = None
    explanation: Optional[str] = None
    evidence_refs: List[str] = []


class ReviewRequest(BaseModel):
    reviewer_id: str = Field(..., min_length=1, max_length=100)
    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    reason: Optional[str] = None


class ReviewResponse(BaseModel):
    id: str
    job_id: str
    reviewer_id: str
    decision: str
    reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditEventResponse(BaseModel):
    id: str
    job_id: str
    event_type: str
    detail: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SeedResponse(BaseModel):
    contracts_loaded: int
    shipments_loaded: int
    message: str
