from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

import structlog
from sqlalchemy.orm import Session

from app.models import Contract

log = structlog.get_logger()


def parse_date_string(text: str) -> Optional[date]:
    if not text:
        return None
    cleaned = text.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return None


class ContractService:
    CONTRACT_VERSION_MAP = {
        "carrier_alpha": ("alpha", "v1"),
        "carrier_beta": ("beta", "v1"),
        "carrier_gamma_v1": ("gamma", "v1"),
        "carrier_gamma": ("gamma", "v2"),
    }

    def __init__(self, db: Session):
        self.db = db

    def parse_contract_text(self, text: str) -> dict:
        lines = text.splitlines()
        base_rates: dict[str, dict[str, dict[str, float]]] = {}
        citations: dict[str, dict[str, any]] = {}
        brackets = ["0-10", "10-50", "50-100", "100+"]

        current_service: Optional[str] = None
        fuel_pct = 5.0
        allowed_surcharges = ["fuel"]

        m_eff = re.search(r"Effective Date:\s*([^\n\r]+)", text)
        m_exp = re.search(r"Expiry Date:\s*([^\n\r]+)", text)
        effective_from = parse_date_string(m_eff.group(1)) if m_eff else None
        effective_to = parse_date_string(m_exp.group(1)) if m_exp else None

        for idx, line in enumerate(lines, 1):
            clean = line.strip()
            lower = clean.lower()

            if "standard delivery" in lower and "rates" in lower or lower.startswith("3.1 standard") or lower.startswith("4.1 standard"):
                current_service = "standard"
                if current_service not in base_rates:
                    base_rates[current_service] = {}
            elif "express delivery" in lower and "rates" in lower or lower.startswith("3.2 express") or lower.startswith("4.2 express"):
                current_service = "express"
                if current_service not in base_rates:
                    base_rates[current_service] = {}
            elif "overnight delivery" in lower and "rates" in lower or lower.startswith("3.3 overnight") or lower.startswith("4.3 overnight"):
                current_service = "overnight"
                if current_service not in base_rates:
                    base_rates[current_service] = {}

            if current_service and "|" in clean:
                parts = [p.strip() for p in clean.split("|")]
                if len(parts) >= 5 and parts[0].isdigit():
                    zone = parts[0]
                    try:
                        rates = [float(p) for p in parts[1:5]]
                        base_rates[current_service][zone] = dict(zip(brackets, rates))
                        for b, r in zip(brackets, rates):
                            citations[f"{current_service}_{zone}_{b}"] = {
                                "line_no": idx,
                                "line_text": clean,
                                "rate": r,
                            }
                    except ValueError:
                        pass

            m_fuel = re.search(r"Rate:\s*([\d\.]+)%", clean)
            if m_fuel:
                fuel_pct = float(m_fuel.group(1))
                citations["fuel_surcharge_pct"] = {"line_no": idx, "line_text": clean, "rate": fuel_pct}

            if "residential" in lower and ("flat" in lower or "rate:" in lower or "usd" in lower or "inr" in lower):
                if "residential" not in allowed_surcharges:
                    allowed_surcharges.append("residential")
                citations["residential_surcharge"] = {"line_no": idx, "line_text": clean}

        return {
            "base_rates": base_rates,
            "fuel_surcharge_pct": fuel_pct,
            "allowed_surcharges": allowed_surcharges,
            "effective_from": str(effective_from) if effective_from else None,
            "effective_to": str(effective_to) if effective_to else None,
            "citations": citations,
        }

    def validate_terms_and_citations(self, terms: dict, contract_text: str) -> bool:
        if not terms or not isinstance(terms, dict):
            return False

        base_rates = terms.get("base_rates")
        if not base_rates or not isinstance(base_rates, dict):
            return False

        for stype, zones in base_rates.items():
            if not isinstance(zones, dict) or not zones:
                return False
            for zone, brackets in zones.items():
                if not isinstance(brackets, dict) or not brackets:
                    return False
                for bracket, rate in brackets.items():
                    try:
                        r = float(rate)
                        if r <= 0:
                            log.warning("invalid_rate_non_positive", service=stype, zone=zone, bracket=bracket, rate=r)
                            return False
                    except (TypeError, ValueError):
                        return False

        contract_lines = contract_text.splitlines()
        citations = terms.get("citations", {})
        if not citations:
            return False

        for key, cite in citations.items():
            line_no = cite.get("line_no")
            quoted_text = cite.get("line_text")
            if not isinstance(line_no, int) or line_no < 1 or line_no > len(contract_lines):
                log.warning("citation_line_out_of_bounds", key=key, line_no=line_no)
                return False
            actual_line = contract_lines[line_no - 1].strip()
            if quoted_text and quoted_text not in actual_line and actual_line not in quoted_text:
                log.warning("citation_mismatch", key=key, quoted=quoted_text, actual=actual_line)
                return False

        return True

    def load_contract_file(self, path: Path) -> int:
        stem = path.stem
        meta_match = self.CONTRACT_VERSION_MAP.get(stem)
        if not meta_match:
            for k, val in self.CONTRACT_VERSION_MAP.items():
                if stem.startswith(k):
                    meta_match = val
                    break
        if not meta_match:
            log.warning("unknown_contract_file", path=str(path))
            return 0

        carrier_id, version = meta_match

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            log.error("cannot_read_contract", path=str(path), error=str(e))
            return 0

        m_eff = re.search(r"Effective Date:\s*([^\n\r]+)", content)
        m_exp = re.search(r"Expiry Date:\s*([^\n\r]+)", content)
        effective_from = parse_date_string(m_eff.group(1)) if m_eff else date(2024, 1, 1)
        effective_to = parse_date_string(m_exp.group(1)) if m_exp else date(2024, 12, 31)

        existing = (
            self.db.query(Contract)
            .filter(Contract.carrier_id == carrier_id, Contract.version == version)
            .first()
        )
        if existing:
            existing.effective_from = effective_from
            existing.effective_to = effective_to
            existing.content_path = str(path)
            self.db.commit()
            return 0

        contract = Contract(
            id=str(uuid.uuid4()),
            carrier_id=carrier_id,
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
            content_path=str(path),
            extracted_terms=None,
            created_at=datetime.utcnow(),
        )
        self.db.add(contract)
        self.db.commit()
        log.info("contract_loaded", carrier_id=carrier_id, version=version, effective_from=str(effective_from), effective_to=str(effective_to))
        return 1

    def get_extracted_terms(self, contract: Contract) -> Optional[dict]:
        if not contract.extracted_terms:
            return None
        try:
            return json.loads(contract.extracted_terms)
        except json.JSONDecodeError:
            log.error("corrupt_extracted_terms", contract_id=contract.id)
            return None

    def extract_and_store_terms(self, contract: Contract, llm_service=None) -> Optional[dict]:
        try:
            with open(contract.content_path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            log.error("contract_file_read_error", path=contract.content_path, error=str(e))
            return None

        terms = self.parse_contract_text(text)

        if not self.validate_terms_and_citations(terms, text):
            log.warning("contract_terms_validation_failed", contract_id=contract.id)
            return None

        if llm_service is not None:
            try:
                llm_raw = llm_service.extract_contract_terms_sync(text, contract.carrier_id)
                if llm_raw and isinstance(llm_raw, dict) and "fuel_surcharge_pct" in llm_raw:
                    log.info("llm_cross_check_succeeded", carrier_id=contract.carrier_id)
            except Exception as e:
                log.info("llm_cross_check_skipped", reason=str(e))

        contract.extracted_terms = json.dumps(terms)
        self.db.commit()
        log.info("terms_extracted_and_stored", contract_id=contract.id, carrier_id=contract.carrier_id)
        return terms

    def resolve_contract_for_date(self, carrier_id: str, ship_date: date) -> Tuple[Optional[Contract], Optional[str]]:
        contracts = (
            self.db.query(Contract)
            .filter(Contract.carrier_id == carrier_id)
            .all()
        )
        applicable = [
            c for c in contracts
            if c.effective_from <= ship_date and (c.effective_to is None or c.effective_to >= ship_date)
        ]
        if len(applicable) == 1:
            return applicable[0], None
        elif len(applicable) > 1:
            log.warning(
                "contract_version_conflict",
                carrier_id=carrier_id,
                ship_date=str(ship_date),
                versions=[c.version for c in applicable],
            )
            return None, "CONTRACT_VERSION_CONFLICT"
        else:
            return None, "NO_CONTRACT_FOUND"

    def get_applicable_contract(self, carrier_id: str, ship_date: date) -> Optional[Contract]:
        contract, _ = self.resolve_contract_for_date(carrier_id, ship_date)
        return contract
