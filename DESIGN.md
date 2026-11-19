# AI Invoice Exception Review System — Design Document

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                        Client (HTTP)                           │
└───────────────────────────┬────────────────────────────────────┘
                            │  REST API
┌───────────────────────────▼────────────────────────────────────┐
│                    FastAPI Application                         │
│  ┌────────────┐  ┌─────────────┐  ┌────────────────────────┐   │
│  │ /invoices  │  │  /reviews   │  │       /admin           │   │
│  │  router    │  │   router    │  │       router           │   │
│  └─────┬──────┘  └──────┬──────┘  └───────────┬────────────┘   │
│        │                │                     │                │
│  ┌─────▼────────────────▼─────────────────────▼─────────────┐  │
│  │           SQLAlchemy (PostgreSQL)                        │  │
│  │  invoice_jobs │ invoice_results │ review_decisions │     │  │
│  │  audit_events │ contracts       │ shipments        │     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │        FastAPI BackgroundTasks Execution               │    │
│  │   process_invoice(job_id)                              │    │
│  │   ┌──────────────┐ ┌───────────────┐ ┌─────────────┐   │    │
│  │   │  Document    │ │  Exception    │ │   LLM       │   │    │
│  │   │  Service     │ │  Detector     │ │  Service    │   │    │
│  │   │  (contract   │ │ (deterministic│ │  (Gemini    │   │    │
│  │   │   terms)     │ │   rules)      │ │  + fallback)│   │    │
│  │   └──────────────┘ └───────────────┘ └─────────────┘   │    │
│  └────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| `routers/invoices.py` | Accept invoice submissions, enforce idempotency, enqueue `process_invoice`, return status/findings |
| `routers/reviews.py` | Record reviewer decisions, return audit history |
| `routers/admin.py` | Seed contract and shipment data from `data/` |
| `services/processor.py` | Asynchronous processing pipeline triggered by FastAPI `BackgroundTasks` |
| `services/document_service.py` | Load contracts, parse terms + citations deterministically, resolve date/version conflicts |
| `services/charge_calculator.py` | Deterministic rate calculations |
| `services/exception_detector.py` | Rule-based exception identification (rate mismatch, weight discrepancy, surcharges, duplicates) |
| `services/llm_service.py` | Generate natural-language explanations with Google Gemini and offline deterministic fallback |

---

## 2. Data Model

```mermaid
erDiagram
    InvoiceJob {
        string id PK
        string invoice_id
        string carrier_id
        text raw_payload
        string status
        string idempotency_key
        text failure_reason
        datetime created_at
        datetime updated_at
    }
    InvoiceResult {
        string id PK
        string job_id FK
        string outcome
        text exceptions
        float disputed_amount
        text explanation
        text evidence_refs
        text ai_raw_response
        datetime created_at
    }
    ReviewDecision {
        string id PK
        string job_id FK
        string reviewer_id
        string decision
        text reason
        datetime created_at
    }
    AuditEvent {
        string id PK
        string job_id FK
        string event_type
        text detail
        datetime created_at
    }
    Contract {
        string id PK
        string carrier_id
        string version
        date effective_from
        date effective_to
        string content_path
        text extracted_terms
        datetime created_at
    }
    Shipment {
        string id PK
        string tracking_id
        string carrier_id
        string origin
        string destination
        float weight_kg
        string service_type
        int zone
        date ship_date
        date delivered_date
        datetime created_at
    }

    InvoiceJob ||--o| InvoiceResult : "has"
    InvoiceJob ||--o| ReviewDecision : "has"
    InvoiceJob ||--o{ AuditEvent : "has many"
```

## 3. Workflow States

```
                    POST /invoices
                         │
                    ┌────▼─────┐
                    │ PENDING  │
                    └────┬─────┘
                         │  FastAPI BackgroundTasks triggers process_invoice(job_id)
                    ┌────▼──────────┐
                    │  PROCESSING   │
                    └────┬──────────┘
           ┌─────────────┼─────────────────┐
           │             │                 │
    ┌──────▼──────┐  ┌───▼──────────┐  ┌──▼──────┐
    │  COMPLETED  │  │ NEEDS_REVIEW │  │  FAILED │
    │ (outcome=   │  │ (ambiguous/  │  │ (perm.) │
    │  valid or   │  │  missing     │  └─────────┘
    │  exception_ │  │  evidence)   │
    │  detected)  │  └──────┬───────┘
    └──────┬──────┘         │
           │                │  POST /invoices/{id}/review
           └────────┬───────┘
                    │
             ┌──────▼───────┐
             │   REVIEWED   │  (ReviewDecision: APPROVED | REJECTED)
             └──────────────┘
```

**State transition rules:**
- `PENDING → PROCESSING`: Triggered asynchronously by FastAPI `BackgroundTasks` immediately after `POST /invoices`.
- `PROCESSING → COMPLETED | NEEDS_REVIEW`: Set upon successful exception evaluation.
- `PROCESSING → FAILED`: Set if an unrecoverable error occurs during processing.
- `COMPLETED | NEEDS_REVIEW → REVIEWED`: Via `ReviewDecision` creation.
- Once `FAILED`, job cannot be retried without manual intervention.

---