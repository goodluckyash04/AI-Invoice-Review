import json
import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditEvent, InvoiceJob, InvoiceResult, JobStatus
from app.response import error_response, success_response
from app.schemas import FindingsResponse, InvoiceJobResponse, InvoiceStatusResponse, InvoiceSubmitRequest
from app.services.processor import process_invoice

log = structlog.get_logger()
router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.post("")
def submit_invoice(
    payload: InvoiceSubmitRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    if idempotency_key:
        existing = db.query(InvoiceJob).filter(InvoiceJob.idempotency_key == idempotency_key).first()
        if existing:
            log.info("idempotent_submission", invoice_id=payload.invoice_id, job_id=existing.id)
            return success_response(
                data=InvoiceJobResponse(
                    job_id=existing.id,
                    invoice_id=existing.invoice_id,
                    carrier_id=existing.carrier_id,
                    status=existing.status.value if hasattr(existing.status, "value") else str(existing.status),
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                ).model_dump(mode="json"),
                message="Invoice already submitted (idempotent response)",
                status_code=200,
            )

    job = InvoiceJob(
        id=str(uuid.uuid4()),
        invoice_id=payload.invoice_id,
        carrier_id=payload.carrier_id,
        raw_payload=payload.model_dump_json(),
        status=JobStatus.PENDING,
        idempotency_key=idempotency_key,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)

    audit = AuditEvent(
        job_id=job.id,
        event_type="SUBMITTED",
        detail=json.dumps({"invoice_id": payload.invoice_id, "carrier_id": payload.carrier_id}),
        created_at=datetime.utcnow(),
    )
    db.add(audit)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_invoice, job.id)

    log.info("invoice_submitted", job_id=job.id, invoice_id=payload.invoice_id, carrier_id=payload.carrier_id)
    return success_response(
        data=InvoiceJobResponse(
            job_id=job.id,
            invoice_id=job.invoice_id,
            carrier_id=job.carrier_id,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            created_at=job.created_at,
            updated_at=job.updated_at,
        ).model_dump(mode="json"),
        message="Invoice submitted for processing",
        status_code=201,
    )


@router.get("/{job_id}/status")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(InvoiceJob).filter(InvoiceJob.id == job_id).first()
    if not job:
        return error_response(
            error_message=f"No job found with id={job_id}.",
            message="Job not found",
            status_code=404,
        )
    return success_response(
        data=InvoiceStatusResponse(
            job_id=job.id,
            invoice_id=job.invoice_id,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            failure_reason=job.failure_reason,
            created_at=job.created_at,
            updated_at=job.updated_at,
        ).model_dump(mode="json"),
        message=f"Job status: {job.status}",
    )


@router.get("/{job_id}/findings")
def get_findings(job_id: str, db: Session = Depends(get_db)):
    job = db.query(InvoiceJob).filter(InvoiceJob.id == job_id).first()
    if not job:
        return error_response(
            error_message=f"No job found with id={job_id}.",
            message="Job not found",
            status_code=404,
        )

    if job.status not in (JobStatus.COMPLETED, JobStatus.NEEDS_REVIEW):
        return error_response(
            error_message=f"Findings not yet available. Current status: {job.status}",
            message="Processing not complete",
            status_code=409,
        )

    result: InvoiceResult = job.result
    if not result:
        return error_response(
            error_message="Result record missing despite completed status.",
            message="Internal error",
            status_code=500,
        )

    exceptions = json.loads(result.exceptions or "[]")
    evidence_refs = json.loads(result.evidence_refs or "[]")

    data = FindingsResponse(
        job_id=job.id,
        invoice_id=job.invoice_id,
        outcome=result.outcome,
        exceptions=exceptions,
        disputed_amount=result.disputed_amount,
        explanation=result.explanation,
        evidence_refs=evidence_refs,
    )
    return success_response(data=data.model_dump(), message="Findings retrieved")
