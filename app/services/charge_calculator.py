from __future__ import annotations

from typing import Any


class ChargeCalculator:
    def calculate_expected_charges(
        self,
        billed_weight_kg: float,
        service_type: str,
        zone: int,
        contract_terms: dict,
    ) -> dict[str, Any]:
        result = {
            "base_rate": 0.0,
            "base_charge": 0.0,
            "fuel_surcharge": 0.0,
            "other_surcharges": {},
            "total_expected": 0.0,
            "weight_bracket": "",
            "zone": zone,
            "service_type": service_type,
        }

        base_rates = contract_terms.get("base_rates", {})
        stype_rates = base_rates.get(service_type, base_rates.get("standard", {}))
        zone_rates = stype_rates.get(str(zone), stype_rates.get("1", {}))

        bracket, rate = self._find_bracket(billed_weight_kg, zone_rates)
        result["weight_bracket"] = bracket
        result["base_rate"] = rate
        result["base_charge"] = round(rate * billed_weight_kg, 2)

        fuel_pct = float(contract_terms.get("fuel_surcharge_pct", 0))
        result["fuel_surcharge"] = round(result["base_charge"] * fuel_pct / 100, 2)

        total = result["base_charge"] + result["fuel_surcharge"]
        result["total_expected"] = round(total, 2)

        return result

    def _find_bracket(self, weight_kg: float, zone_rates: dict) -> tuple[str, float]:
        parsed: list[tuple[float, float, str, float]] = []
        for label, rate in zone_rates.items():
            if label.endswith("+"):
                lower = float(label[:-1])
                parsed.append((lower, float("inf"), label, float(rate)))
            elif "-" in label:
                parts = label.split("-")
                parsed.append((float(parts[0]), float(parts[1]), label, float(rate)))

        parsed.sort(key=lambda x: x[0])

        for lower, upper, label, rate in parsed:
            if lower <= weight_kg < upper:
                return label, rate

        if parsed:
            return parsed[-1][2], parsed[-1][3]
        return "unknown", 0.0

    def calculate_disputed_amount(
        self,
        billed_amount: float,
        expected_total: float,
    ) -> float:
        return round(billed_amount - expected_total, 2)
