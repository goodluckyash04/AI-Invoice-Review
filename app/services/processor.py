import json
from datetime import datetime
from typing import Optional

import structlog

from app.db import SessionLocal
from app.models import AuditEvent, Contract, InvoiceJob, InvoiceResult, JobStatus, Outcome, Shipment
from app.services.document_service import ContractService
from app.services.exception_detector import ExceptionDetector
from app.services.llm_service import LLMService

log = structlog.get_logger()


def process_invoice(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(InvoiceJob).filter(InvoiceJob.id == job_id).first()
        if not job:
            return

        job.status = JobStatus.PROCESSING
        job.updated_at = datetime.utcnow()
        db.commit()

        invoice = json.loads(job.raw_payload)

        duplicate_detected = False
        other_jobs = db.query(InvoiceJob).filter(InvoiceJob.id != job.id).all()
        for oj in other_jobs:
            if oj.invoice_id == invoice.get("invoice_id"):
                duplicate_detected = True
                break
            try:
                op = json.loads(oj.raw_payload)
                if (
                    op.get("tracking_id")
                    and op.get("tracking_id") == invoice.get("tracking_id")
                    and abs(float(op.get("billed_amount", 0)) - float(invoice.get("billed_amount", 0))) < 0.01
                ):
                    duplicate_detected = True
                    break
            except Exception:
                pass

        tracking_id = invoice.get("tracking_id")
        shipment_dict: Optional[dict] = None
        shipment_row: Optional[Shipment] = None
        if tracking_id:
            shipment_row = db.query(Shipment).filter(Shipment.tracking_id == tracking_id).first()
            if shipment_row:
                shipment_dict = {
                    "tracking_id": shipment_row.tracking_id,
                    "carrier_id": shipment_row.carrier_id,
                    "weight_kg": shipment_row.weight_kg,
                    "zone": shipment_row.zone,
                    "service_type": shipment_row.service_type,
                    "ship_date": str(shipment_row.ship_date),
                }

        contract_service = ContractService(db)
        contract_overlap = False
        contract_terms: Optional[dict] = None

        if shipment_row:
            contract, conflict_reason = contract_service.resolve_contract_for_date(job.carrier_id, shipment_row.ship_date)
            if conflict_reason == "CONTRACT_VERSION_CONFLICT":
                contract_overlap = True
            elif contract:
                contract_terms = contract_service.get_extracted_terms(contract)
                if contract_terms is None:
                    llm = LLMService()
                    contract_terms = contract_service.extract_and_store_terms(contract, llm)

        detector = ExceptionDetector()
        seen_ids = {invoice.get("invoice_id")} if duplicate_detected else set()

        detection_result = detector.detect(
            invoice=invoice,
            shipment=shipment_dict,
            contract_terms=contract_terms,
            seen_invoice_ids=seen_ids,
            contract_overlap=contract_overlap,
        )

        llm = LLMService()
        explanation = llm.generate_explanation(
            invoice=invoice,
            exceptions=detection_result["exceptions"],
            shipment=shipment_dict,
            contract_terms=contract_terms,
        )

        outcome_map = {
            "valid": Outcome.VALID,
            "exception_detected": Outcome.EXCEPTION_DETECTED,
            "needs_review": Outcome.NEEDS_REVIEW,
        }
        outcome = outcome_map.get(detection_result["outcome"], Outcome.NEEDS_REVIEW)

        result = db.query(InvoiceResult).filter(InvoiceResult.job_id == job_id).first()
        if result:
            result.outcome = outcome
            result.exceptions = json.dumps(detection_result["exceptions"])
            result.disputed_amount = detection_result.get("disputed_amount")
            result.explanation = explanation
            result.evidence_refs = json.dumps(detection_result.get("evidence_refs", []))
            result.ai_raw_response = explanation
        else:
            result = InvoiceResult(
                job_id=job_id,
                outcome=outcome,
                exceptions=json.dumps(detection_result["exceptions"]),
                disputed_amount=detection_result.get("disputed_amount"),
                explanation=explanation,
                evidence_refs=json.dumps(detection_result.get("evidence_refs", [])),
                ai_raw_response=explanation,
                created_at=datetime.utcnow(),
            )
            db.add(result)

        job.status = JobStatus.NEEDS_REVIEW if outcome == Outcome.NEEDS_REVIEW else JobStatus.COMPLETED
        job.updated_at = datetime.utcnow()

        audit = AuditEvent(
            job_id=job_id,
            event_type="COMPLETED",
            detail=json.dumps({
                "outcome": detection_result["outcome"],
                "exception_count": len(detection_result["exceptions"]),
                "disputed_amount": detection_result.get("disputed_amount"),
            }),
            created_at=datetime.utcnow(),
        )
        db.add(audit)
        db.commit()

        log.info(
            "invoice_processed",
            job_id=job_id,
            outcome=detection_result["outcome"],
            disputed_amount=detection_result.get("disputed_amount"),
        )
    except Exception as e:
        db.rollback()
        log.error("invoice_processing_failed", job_id=job_id, error=str(e))
        try:
            job = db.query(InvoiceJob).filter(InvoiceJob.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.failure_reason = str(e)
                job.updated_at = datetime.utcnow()
                audit = AuditEvent(
                    job_id=job_id,
                    event_type="FAILED",
                    detail=json.dumps({"reason": str(e)[:500]}),
                    created_at=datetime.utcnow(),
                )
                db.add(audit)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
