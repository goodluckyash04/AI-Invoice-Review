# AI Invoice Exception Review System

An intelligent freight invoice auditing system built with FastAPI, PostgreSQL, and Google Gemini (`gemini-3.8-flash`). It parses carrier contracts, matches shipment records, applies deterministic rule-based exception checks, and uses Gemini for natural-language explanations and contract cross-checks. Human reviewers approve or reject flagged invoices through a REST API backed by an immutable audit log.

---

## Architecture & Design

```
Client (HTTP) ──► FastAPI (main.py)
                    ├── POST /invoices          ──► Enqueue InvoiceJob (FastAPI BackgroundTasks)
                    ├── GET  /invoices/{id}/status
                    ├── GET  /invoices/{id}/findings
                    ├── POST /invoices/{id}/review ──► ReviewDecision + AuditEvent
                    └── POST /admin/seed         ──► Seed contracts and shipments

Asynchronous Processor (process_invoice via BackgroundTasks):
  ├── DocumentService     ──► Deterministic regex/line parsing + citations
  ├── ExceptionDetector   ──► Deterministic financial checks (positive overcharges only)
  ├── ChargeCalculator    ──► Pure Python math (no LLM in billing calculations)
  └── LLMService          ──► Gemini API for explanations (offline fallback if key empty)
```

- **Database:** Local PostgreSQL (`psycopg2-binary`) with connection pooling.
- **AI Models:** Google Gemini (`gemini-2.5-flash`) via the `google-genai` SDK. Financial calculations are 100% deterministic Python.
- **Background Processing:** FastAPI built-in `BackgroundTasks` handles invoice auditing immediately after submission without polling loops or worker infrastructure.

---

## Quick Start (Local)

### 1. Prerequisites
- Python 3.12+
- Local PostgreSQL instance running on port `5432` with a database named `mi_test` (e.g. `postgresql://postgres:postgres@localhost:5432/mi_test`)
- Google Gemini API key (optional: system falls back to deterministic explanations if empty)

### 2. Setup & Execution

```bash
cd Mi-test

python -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env

python scripts/seed.py

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## API Usage & Curl Examples

### 1. Submit an Invoice for Processing
```bash
curl -X POST http://localhost:8000/invoices \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: a1b2c3d4-0001" \
  -d '{
    "invoice_id": "INV-ALPHA-2024-001",
    "carrier_id": "alpha",
    "tracking_id": "TRK-ALPHA-001",
    "service_type": "standard",
    "billed_weight_kg": 5.2,
    "billed_amount": 13.71,
    "surcharges": [{"name": "fuel", "amount": 0.71}],
    "invoice_date": "2024-01-20",
    "billing_period_start": "2024-01-01",
    "billing_period_end": "2024-01-31"
  }'
```

### 2. Check Job Processing Status
```bash
curl -s http://localhost:8000/invoices/<JOB_ID>/status
```

### 3. Retrieve Audit Findings and Disputed Amounts
```bash
curl -s http://localhost:8000/invoices/<JOB_ID>/findings
```

### 4. Record Human Review Decision
```bash
curl -X POST http://localhost:8000/invoices/<JOB_ID>/review \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer_id": "analyst-jane",
    "decision": "APPROVED",
    "reason": "Confirmed rate discrepancy against contract section 4.1."
  }'
```

### 5. Inspect Full Audit History
```bash
curl -s http://localhost:8000/invoices/<JOB_ID>/audit
```

---

## Running Evaluation

### Run Benchmark Evaluation Suite
```bash
python scripts/run_eval.py
```

---

## Evaluation Results

| Metric | Target | Actual | Status |
|---|---|---|---|
| **Exception Precision** | ≥ 80.0% | **100.0%** | Pass |
| **Exception Recall** | ≥ 80.0% | **100.0%** | Pass |
| **F1 Score** | ≥ 80.0% | **100.0%** | Pass |
| **Disputed Amount Accuracy (exact within ₹0.01)** | 100.0% | **100.0%** | Pass |
| **Citation Verification (line exists in contract)** | 100.0% | **100.0%** | Pass |
| **Abstention Accuracy (needs_review cases)** | 100.0% | **100.0%** | Pass |
| **Overall Accuracy** | ≥ 95.0% | **100.0%** | Pass |

### Summary of Edge Cases Evaluated:
1. **Undercharge Rule:** Invoices billed below contracted rates (e.g. `INV-ALPHA-2024-009`) are detected and flagged as `RATE_MISMATCH`, with `disputed_amount = ₹0.00` because undercharges do not represent customer overcharges.
2. **Contract Version Overlap:** Shipments falling into overlapping contract windows (Gamma v1 and v2, June 1–5, 2024) trigger `CONTRACT_VERSION_CONFLICT` and safely abstain via `needs_review`.
3. **Missing Shipments:** Invoices without tracking records (`INV-BETA-MISSING-001`) abstain via `needs_review`.
4. **Duplicates:** Repeated invoices or identical tracking ID + amounts are queued and detected with `DUPLICATE_INVOICE`.
5. **Fuel Surcharge Verification:** Invoices with fuel surcharges deviating from contract percentages (`INV-BETA-FUEL-ERR`) trigger `SURCHARGE_MISMATCH`.
6. **Prompt Injection Resilience:** Adversarial contract instruction injections (`carrier_malicious.txt`) tested; positive rates enforced and injection text ignored.

---

## Scope: Implemented, Simplified, Deferred

### Implemented
- Deterministic contract rate extraction with source line numbers and line text citations.
- Deterministic financial calculations in pure Python (LLM never calculates money).
- Six exception categories: rate mismatch, weight discrepancy, unsupported surcharge, surcharge mismatch, duplicate invoice, missing tracking/evidence.
- Multi-carrier contract version overlap resolution (`needs_review` with `CONTRACT_VERSION_CONFLICT`).
- Asynchronous task processing using FastAPI `BackgroundTasks`.
- Full audit history and human review API with double-review conflict prevention.
- Google Gemini API integration with offline fallback when `GEMINI_API_KEY` is empty.