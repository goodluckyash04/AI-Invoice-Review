from __future__ import annotations

from typing import Any, Optional

import structlog

from app.services.charge_calculator import ChargeCalculator

log = structlog.get_logger()

TOLERANCE = 0.50
WEIGHT_TOLERANCE_KG = 0.1


class ExceptionDetector:
    def __init__(self):
        self.calculator = ChargeCalculator()

    def detect(
        self,
        invoice: dict,
        shipment: Optional[dict],
        contract_terms: Optional[dict],
        seen_invoice_ids: set[str],
        contract_overlap: bool = False,
    ) -> dict[str, Any]:
        exceptions: list[dict] = []
        evidence_refs: list[str] = []
        total_disputed = 0.0

        invoice_id = invoice.get("invoice_id", "")

        if not invoice.get("tracking_id"):
            exceptions.append({
                "exception_type": "MISSING_TRACKING_ID",
                "description": "Invoice has no tracking ID; cannot match to a shipment record.",
                "expected_value": "A valid tracking ID",
                "actual_value": None,
                "disputed_amount": 0.0,
                "evidence_ref": "Invoice payload – tracking_id field",
            })
            return self._build_result(exceptions, 0.0, evidence_refs, force_review=True)

        if invoice_id in seen_invoice_ids:
            billed_total = float(invoice.get("billed_amount", 0.0))
            exceptions.append({
                "exception_type": "DUPLICATE_INVOICE",
                "description": f"Invoice ID '{invoice_id}' has already been submitted or shares tracking ID with identical amount.",
                "expected_value": "Unique invoice submission",
                "actual_value": invoice_id,
                "disputed_amount": billed_total,
                "evidence_ref": "Database – invoice_jobs table",
            })
            total_disputed += billed_total
            return self._build_result(exceptions, total_disputed, evidence_refs, force_review=False)

        if shipment is None:
            exceptions.append({
                "exception_type": "MISSING_EVIDENCE",
                "description": f"No shipment record found for tracking_id='{invoice.get('tracking_id')}'.",
                "expected_value": "Matching shipment record",
                "actual_value": None,
                "disputed_amount": 0.0,
                "evidence_ref": "Database – shipments table",
            })
            return self._build_result(exceptions, 0.0, evidence_refs, force_review=True)

        if contract_overlap:
            exceptions.append({
                "exception_type": "CONTRACT_VERSION_CONFLICT",
                "description": "Multiple overlapping contract versions found for shipment date. Human review required.",
                "expected_value": "Single active contract version",
                "actual_value": "Multiple overlapping versions",
                "disputed_amount": 0.0,
                "evidence_ref": "Database – contracts table",
            })
            return self._build_result(exceptions, 0.0, evidence_refs, force_review=True)

        if contract_terms is None:
            exceptions.append({
                "exception_type": "MISSING_EVIDENCE",
                "description": "No applicable contract terms found for this carrier and shipment date.",
                "expected_value": "Valid carrier contract in effect on ship_date",
                "actual_value": None,
                "disputed_amount": 0.0,
                "evidence_ref": "Database – contracts table",
            })
            return self._build_result(exceptions, 0.0, evidence_refs, force_review=True)

        billed_weight = float(invoice.get("billed_weight_kg", 0))
        actual_weight = float(shipment.get("weight_kg", 0))
        zone = int(shipment.get("zone", 1))
        service_type = invoice.get("service_type", "standard")

        weight_diff = abs(billed_weight - actual_weight)
        if weight_diff > WEIGHT_TOLERANCE_KG:
            raw_disputed = self._weight_disputed(billed_weight, actual_weight, zone, service_type, contract_terms)
            disputed = max(0.0, raw_disputed) if raw_disputed is not None else 0.0
            exceptions.append({
                "exception_type": "WEIGHT_DISCREPANCY",
                "description": (
                    f"Billed weight {billed_weight} kg differs from shipment record "
                    f"{actual_weight} kg by {weight_diff:.2f} kg."
                ),
                "expected_value": actual_weight,
                "actual_value": billed_weight,
                "disputed_amount": disputed,
                "evidence_ref": f"Shipment record – tracking_id={shipment.get('tracking_id')}",
            })
            total_disputed += disputed
            evidence_refs.append(f"Shipment record tracking_id={shipment.get('tracking_id')}")

        expected = self.calculator.calculate_expected_charges(billed_weight, service_type, zone, contract_terms)
        surcharges_sum = sum(float(s.get("amount", 0)) for s in invoice.get("surcharges", []))
        billed_base = float(invoice.get("billed_amount", 0)) - surcharges_sum
        base_diff = round(billed_base - expected["base_charge"], 2)

        if abs(base_diff) > TOLERANCE:
            rate_disputed = max(0.0, base_diff)
            exceptions.append({
                "exception_type": "RATE_MISMATCH",
                "description": (
                    f"Billed base charge ₹{billed_base:.2f} does not match expected "
                    f"₹{expected['base_charge']:.2f} (rate ₹{expected['base_rate']}/kg, "
                    f"zone {zone}, {service_type})."
                ),
                "expected_value": expected["base_charge"],
                "actual_value": billed_base,
                "disputed_amount": rate_disputed,
                "evidence_ref": f"Contract – carrier {invoice.get('carrier_id')} rate table zone {zone}",
            })
            total_disputed += rate_disputed
            evidence_refs.append(f"Contract carrier={invoice.get('carrier_id')} zone={zone} service={service_type}")

        allowed = set(s.lower() for s in contract_terms.get("allowed_surcharges", []))
        fuel_pct = float(contract_terms.get("fuel_surcharge_pct", 0))

        for surcharge in invoice.get("surcharges", []):
            sname = surcharge.get("name", "").lower()
            samount = float(surcharge.get("amount", 0))

            if sname not in allowed:
                exceptions.append({
                    "exception_type": "UNSUPPORTED_SURCHARGE",
                    "description": f"Surcharge '{sname}' (₹{samount:.2f}) is not permitted under the contract.",
                    "expected_value": f"One of: {sorted(allowed)}",
                    "actual_value": sname,
                    "disputed_amount": samount,
                    "evidence_ref": f"Contract – allowed_surcharges clause, carrier={invoice.get('carrier_id')}",
                })
                total_disputed += samount
                evidence_refs.append(f"Contract surcharge clause carrier={invoice.get('carrier_id')}")
            elif sname == "fuel":
                expected_fuel = round(expected["base_charge"] * (fuel_pct / 100.0), 2)
                fuel_diff = round(samount - expected_fuel, 2)
                if abs(fuel_diff) > TOLERANCE:
                    fuel_disputed = max(0.0, fuel_diff)
                    exceptions.append({
                        "exception_type": "SURCHARGE_MISMATCH",
                        "description": (
                            f"Billed fuel surcharge ₹{samount:.2f} does not match contract rate "
                            f"{fuel_pct}% of base charge (expected ₹{expected_fuel:.2f})."
                        ),
                        "expected_value": expected_fuel,
                        "actual_value": samount,
                        "disputed_amount": fuel_disputed,
                        "evidence_ref": f"Contract – fuel surcharge {fuel_pct}%",
                    })
                    total_disputed += fuel_disputed
                    evidence_refs.append(f"Contract fuel surcharge clause carrier={invoice.get('carrier_id')}")

        return self._build_result(exceptions, total_disputed, evidence_refs)

    def _weight_disputed(self, billed_kg, actual_kg, zone, service_type, contract_terms):
        try:
            billed_charge = self.calculator.calculate_expected_charges(billed_kg, service_type, zone, contract_terms)
            actual_charge = self.calculator.calculate_expected_charges(actual_kg, service_type, zone, contract_terms)
            diff = billed_charge["total_expected"] - actual_charge["total_expected"]
            return round(max(0.0, diff), 2)
        except Exception:
            return 0.0

    def _build_result(self, exceptions, total_disputed, evidence_refs, force_review=False):
        if not exceptions:
            outcome = "valid"
            disputed_amount = None
        elif force_review:
            outcome = "needs_review"
            disputed_amount = round(total_disputed, 2) if total_disputed > 0 else 0.0
        else:
            outcome = "exception_detected"
            disputed_amount = round(total_disputed, 2) if total_disputed > 0 else 0.0

        return {
            "outcome": outcome,
            "exceptions": exceptions,
            "disputed_amount": disputed_amount,
            "evidence_refs": list(set(evidence_refs)),
        }
