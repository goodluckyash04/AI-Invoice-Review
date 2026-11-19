from __future__ import annotations

import json
from typing import Optional

import structlog
from google import genai
from google.genai import types

from app.config import settings

log = structlog.get_logger()


class LLMService:
    def __init__(self):
        self._gemini_client = None

    def _get_gemini_client(self):
        key = settings.gemini_api_key
        if not key:
            return None
        if self._gemini_client is None:
            self._gemini_client = genai.Client(api_key=key)
        return self._gemini_client

    def generate_explanation(
        self,
        invoice: dict,
        exceptions: list[dict],
        shipment: Optional[dict],
        contract_terms: Optional[dict],
    ) -> str:
        client = self._get_gemini_client()
        if not client:
            return self._deterministic_fallback(invoice, exceptions)

        try:
            prompt = f"""Analyse the following invoice exceptions and produce a concise explanation
(3-5 sentences) suitable for a human reviewer. Reference specific contract clauses,
shipment data, and amounts where relevant.

Invoice ID: {invoice.get('invoice_id')}
Carrier: {invoice.get('carrier_id')}
Exceptions: {json.dumps(exceptions)}
Shipment: {json.dumps(shipment or {})}
"""
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an invoice auditing assistant. Summarize exceptions clearly.",
                    max_output_tokens=400,
                    temperature=0.2,
                ),
            )
            text = (response.text or "").strip()
            return text if text else self._deterministic_fallback(invoice, exceptions)
        except Exception as e:
            log.warning("llm_explanation_failed", error=str(e))
            return self._deterministic_fallback(invoice, exceptions)

    def extract_contract_terms_sync(self, contract_text: str, carrier_id: str) -> Optional[dict]:
        client = self._get_gemini_client()
        if not client:
            return None

        try:
            prompt = f"""Extract structured rate information from this carrier contract as JSON.
Carrier: {carrier_id}
{contract_text}
"""
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=2000,
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            raw = (response.text or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except Exception as e:
            log.error("contract_extraction_failed", carrier_id=carrier_id, error=str(e))
            return None

    def _deterministic_fallback(self, invoice: dict, exceptions: list[dict]) -> str:
        types = ", ".join(e["exception_type"] for e in exceptions)
        return (
            f"Invoice {invoice.get('invoice_id')} from carrier '{invoice.get('carrier_id')}' "
            f"has {len(exceptions)} exception(s): {types}. "
            "Deterministic checks verified rate and surcharge calculations against contract terms. "
            "Please review the exception details and evidence references."
        )
