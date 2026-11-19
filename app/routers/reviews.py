import json
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditEvent, InvoiceJob, JobStatus, ReviewDecision, ReviewDecisionEnum
from app.response import error_response, success_response
from app.schemas import AuditEventResponse, ReviewRequest, ReviewResponse

log = structlog.get_logger()
router = APIRouter(prefix="/invoices", tags=["Reviews"])

REVIEWABLE_STATUSES = {JobStatus.COMPLETED, JobStatus.NEEDS_REVIEW}


@router.post("/{job_id}/review")
def submit_review(job_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    job = db.query(InvoiceJob).filter(InvoiceJob.id == job_id).first()
    if not job:
        return error_response(
            error_message=f"No job found with id={job_id}.",
            message="Job not found",
            status_code=404,
        )

    if job.status not in REVIEWABLE_STATUSES:
        return error_response(
            error_message=(
                f"Job cannot be reviewed in status '{job.status}'. "
                f"Only {[s.value for s in REVIEWABLE_STATUSES]} jobs are reviewable."
            ),
            message="Invalid state for review",
            status_code=409,
        )

    if job.review:
        return error_response(
            error_message=(
                f"A review decision ({job.review.decision}) was already recorded "
                f"by '{job.review.reviewer_id}' at {job.review.created_at.isoformat()}."
            ),
            message="Review already submitted",
            status_code=409,
        )

    decision = ReviewDecision(
        job_id=job.id,
        reviewer_id=payload.reviewer_id,
        decision=ReviewDecisionEnum(payload.decision),
        reason=payload.reason,
        created_at=datetime.utcnow(),
    )
    db.add(decision)

    audit = AuditEvent(
        job_id=job.id,
        event_type="REVIEWED",
        detail=json.dumps({
            "reviewer_id": payload.reviewer_id,
            "decision": payload.decision,
            "reason": payload.reason,
        }),
        created_at=datetime.utcnow(),
    )
    db.add(audit)

    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(decision)

    log.info(
        "invoice_reviewed",
        job_id=job_id,
        reviewer_id=payload.reviewer_id,
        decision=payload.decision,
    )
    return success_response(
        data=ReviewResponse.model_validate(decision).model_dump(mode="json"),
        message=f"Review decision '{payload.decision}' recorded successfully",
        status_code=201,
    )


@router.get("/{job_id}/audit")
def get_audit_history(job_id: str, db: Session = Depends(get_db)):
    job = db.query(InvoiceJob).filter(InvoiceJob.id == job_id).first()
    if not job:
        return error_response(
            error_message=f"No job found with id={job_id}.",
            message="Job not found",
            status_code=404,
        )

    events = []
    for evt in job.audit_events:
        detail = None
        if evt.detail:
            try:
                detail = json.loads(evt.detail)
            except json.JSONDecodeError:
                detail = evt.detail
        events.append(
            AuditEventResponse(
                id=evt.id,
                job_id=evt.job_id,
                event_type=evt.event_type,
                detail=detail,
                created_at=evt.created_at,
            ).model_dump(mode="json")
        )

    return success_response(data=events, message=f"{len(events)} audit event(s) found")
