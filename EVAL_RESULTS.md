# AI Invoice Exception Review System — Evaluation Results

> **Generated on:** 2026-11-19 02:53:20 UTC  
> **Evaluation Mode:** Deterministic Rule Engine + Ground Truth Benchmark

---

## 1. Executive Summary

| Metric | Target | Actual | Status |
|---|---|---|---|
| **Exception Precision** | ≥ 80.0% | **100.0%** | Pass |
| **Exception Recall** | ≥ 80.0% | **100.0%** | Pass |
| **F1 Score** | ≥ 80.0% | **100.0%** | Pass |
| **Disputed Amount Accuracy (exact within ₹0.01)** | 100.0% | **100.0%** | Pass |
| **Citation Verification (line exists in contract)** | 100.0% | **100.0%** | Pass |
| **Abstention Accuracy (needs_review cases)** | 100.0% | **100.0%** | Pass |
| **Overall Accuracy** | ≥ 95.0% | **100.0%** | Pass |

---

## 2. Test Cases Covered

- **Alpha Carrier:** Baseline standard, express, overnight, undercharge exception (₹0 disputed), rate overcharge, weight discrepancy, unsupported surcharge, missing tracking ID.
- **Beta Carrier:** Valid baseline delivery, missing shipment record (`needs_review`), wrong fuel surcharge amount (`SURCHARGE_MISMATCH`), duplicate submission (`DUPLICATE_INVOICE`).
- **Gamma Carrier:** Standard delivery under Gamma v1, overlapping contract versions active on ship date (`CONTRACT_VERSION_CONFLICT` -> `needs_review`).
- **Prompt Injection Resilience:** Adversarial contract instruction injection (`carrier_malicious.txt`) tested and verified; positive rates enforced and injection text ignored.

---

## 3. Invoice Evaluation Breakdown

| Invoice ID | Carrier | Expected Outcome | Actual Outcome | Exp. Disputed | Act. Disputed | Exceptions Detected | Status |
|---|---|---|---|---|---|---|---|
| `INV-ALPHA-2024-001` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-002` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-003` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-004` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-005` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-006` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-007` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-008` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-ALPHA-2024-009` | `alpha` | `exception_detected` | `exception_detected` | ₹0.00 | ₹0.00 | RATE_MISMATCH, SURCHARGE_MISMATCH | **PASS** |
| `INV-ALPHA-2024-010` | `alpha` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-BETA-2024-001` | `beta` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-BETA-MISSING-001` | `beta` | `needs_review` | `needs_review` | ₹0.00 | ₹0.00 | MISSING_EVIDENCE | **PASS** |
| `INV-BETA-FUEL-ERR` | `beta` | `exception_detected` | `exception_detected` | ₹15.50 | ₹15.50 | SURCHARGE_MISMATCH | **PASS** |
| `INV-BETA-DUP-001` | `beta` | `exception_detected` | `exception_detected` | ₹27.98 | ₹27.98 | DUPLICATE_INVOICE | **PASS** |
| `INV-GAMMA-2024-001` | `gamma` | `valid` | `valid` | ₹0.00 | ₹0.00 | — | **PASS** |
| `INV-GAMMA-OVERLAP-001` | `gamma` | `needs_review` | `needs_review` | ₹0.00 | ₹0.00 | CONTRACT_VERSION_CONFLICT | **PASS** |
| `INV-EXCEPTION-001` | `alpha` | `exception_detected` | `exception_detected` | ₹40.00 | ₹40.00 | RATE_MISMATCH | **PASS** |
| `INV-EXCEPTION-002` | `alpha` | `exception_detected` | `exception_detected` | ₹86.51 | ₹86.51 | WEIGHT_DISCREPANCY | **PASS** |
| `INV-EXCEPTION-003` | `alpha` | `exception_detected` | `exception_detected` | ₹25.00 | ₹25.00 | UNSUPPORTED_SURCHARGE | **PASS** |
| `INV-EXCEPTION-004` | `alpha` | `needs_review` | `needs_review` | ₹0.00 | ₹0.00 | MISSING_TRACKING_ID | **PASS** |

---

## 4. Observations & Tradeoffs

1. **Undercharge Rule:** Invoices billed below contracted rates (e.g. `INV-ALPHA-2024-009`) are detected and flagged as `RATE_MISMATCH`, but have `disputed_amount = ₹0.00` because undercharges do not represent customer overcharges.
2. **Contract Version Overlap:** Dates overlapping between Gamma v1 and Gamma v2 (June 1–5, 2024) successfully trigger `CONTRACT_VERSION_CONFLICT` and abstain via `needs_review` without manual guesswork.
3. **Citation Integrity:** Every rate lookup references exact contract line numbers and literal line strings from `.txt` contract files.
