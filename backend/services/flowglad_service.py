"""
Synapse 2.0 Flowglad Service
Automated billing and CPT code generation
"""

import logging
from typing import Optional
from datetime import datetime
import httpx

from config import get_settings
from models.schemas import BillingRequest, BillingResponse, SOAPNote

logger = logging.getLogger(__name__)


# CPT Code mappings for common encounter types
CPT_CODES = {
    # Evaluation & Management - Office Visits
    "new_patient_low": "99202",
    "new_patient_moderate": "99203",
    "new_patient_high": "99204",
    "new_patient_comprehensive": "99205",
    "established_low": "99212",
    "established_moderate": "99213",
    "established_high": "99214",
    "established_comprehensive": "99215",

    # Consultations
    "consultation_low": "99242",
    "consultation_moderate": "99243",
    "consultation_high": "99244",

    # Preventive Care
    "preventive_new_18-39": "99385",
    "preventive_new_40-64": "99386",
    "preventive_established_18-39": "99395",
    "preventive_established_40-64": "99396",
}

# ICD-10 codes for common diagnoses
ICD10_CODES = {
    "migraine": "G43.909",
    "migraine_without_aura": "G43.009",
    "migraine_with_aura": "G43.109",
    "tension_headache": "G44.209",
    "hypertension": "I10",
    "anxiety": "F41.1",
    "depression": "F32.9",
    "back_pain": "M54.5",
    "diabetes_type_2": "E11.9",
}


class FlowgladService:
    """
    Flowglad integration for:
    - CPT code generation based on encounter documentation
    - Invoice creation
    - Revenue cycle management
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize HTTP client"""
        self._client = httpx.AsyncClient(
            base_url=self.settings.flowglad_api_url,
            headers={
                "Authorization": f"Bearer {self.settings.flowglad_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()

    def _determine_complexity(
        self,
        soap_note: SOAPNote,
        duration_minutes: int,
        safety_alerts_count: int
    ) -> str:
        """
        Determine visit complexity for CPT code selection

        Based on 2021 E/M guidelines considering:
        - Medical decision making complexity
        - Time spent
        """
        # Simple heuristic based on visit characteristics
        if duration_minutes >= 40 or safety_alerts_count >= 2:
            return "comprehensive"
        elif duration_minutes >= 25 or safety_alerts_count >= 1:
            return "high"
        elif duration_minutes >= 15:
            return "moderate"
        else:
            return "low"

    def _extract_icd10_codes(self, soap_note: SOAPNote) -> list[str]:
        """Extract ICD-10 codes from SOAP note content"""
        codes = []

        # Check assessment text for known conditions
        assessment_lower = soap_note.assessment.lower()
        subjective_lower = soap_note.subjective.lower()
        combined_text = assessment_lower + " " + subjective_lower

        for condition, code in ICD10_CODES.items():
            if condition.replace("_", " ") in combined_text:
                codes.append(code)

        # Use any pre-set codes
        codes.extend(soap_note.icd10_codes)

        return list(set(codes)) or ["R69"]  # Default: Illness, unspecified

    def generate_cpt_codes(
        self,
        soap_note: SOAPNote,
        duration_minutes: int,
        is_new_patient: bool = False,
        safety_alerts_count: int = 0
    ) -> list[str]:
        """
        Generate appropriate CPT codes for the encounter

        Args:
            soap_note: The SOAP note documentation
            duration_minutes: Total visit duration
            is_new_patient: Whether this is a new patient
            safety_alerts_count: Number of safety alerts during visit

        Returns:
            List of applicable CPT codes
        """
        complexity = self._determine_complexity(
            soap_note, duration_minutes, safety_alerts_count
        )

        patient_type = "new_patient" if is_new_patient else "established"
        code_key = f"{patient_type}_{complexity}"

        cpt_code = CPT_CODES.get(code_key, "99214")  # Default: established, high

        logger.info(f"Generated CPT code: {cpt_code} (complexity: {complexity})")

        return [cpt_code]

    async def create_invoice(
        self,
        billing_request: BillingRequest
    ) -> BillingResponse:
        """
        Create invoice via Flowglad API

        Args:
            billing_request: Billing details

        Returns:
            BillingResponse with invoice details
        """
        logger.info(f"Creating invoice for session: {billing_request.session_id}")

        # Calculate estimated amount based on CPT codes
        # Simplified pricing - in production this would use fee schedules
        base_amounts = {
            "99212": 45.00,
            "99213": 75.00,
            "99214": 110.00,
            "99215": 150.00,
            "99202": 65.00,
            "99203": 100.00,
            "99204": 150.00,
            "99205": 200.00,
        }

        total_amount = sum(
            base_amounts.get(code, 100.00)
            for code in billing_request.cpt_codes
        )

        # Mock response if API not configured
        if not self.settings.flowglad_api_key or not self._client:
            logger.info(f"Mock invoice created: ${total_amount:.2f}")
            return BillingResponse(
                invoice_id=f"INV-{billing_request.session_id[:8].upper()}",
                total_amount=total_amount,
                status="created",
                created_at=datetime.now(),
            )

        try:
            response = await self._client.post(
                "/invoices",
                json={
                    "external_id": billing_request.session_id,
                    "patient_id": billing_request.patient_id,
                    "provider_id": billing_request.provider_id,
                    "service_date": billing_request.service_date.isoformat(),
                    "cpt_codes": billing_request.cpt_codes,
                    "icd10_codes": billing_request.icd10_codes,
                    "duration_minutes": billing_request.duration_minutes,
                    "amount": total_amount,
                }
            )
            response.raise_for_status()
            data = response.json()

            return BillingResponse(
                invoice_id=data["invoice_id"],
                total_amount=data["amount"],
                status=data["status"],
                created_at=datetime.fromisoformat(data["created_at"]),
            )

        except Exception as e:
            logger.error(f"Flowglad API error: {e}")
            # Return mock response on error
            return BillingResponse(
                invoice_id=f"INV-{billing_request.session_id[:8].upper()}",
                total_amount=total_amount,
                status="pending",
                created_at=datetime.now(),
            )

    async def process_end_of_visit(
        self,
        session_id: str,
        patient_id: str,
        provider_id: str,
        soap_note: SOAPNote,
        duration_minutes: int,
        is_new_patient: bool = False,
        safety_alerts_count: int = 0
    ) -> BillingResponse:
        """
        Complete end-of-visit billing workflow

        Generates codes and creates invoice in one call
        """
        # Generate CPT codes
        cpt_codes = self.generate_cpt_codes(
            soap_note, duration_minutes, is_new_patient, safety_alerts_count
        )

        # Extract ICD-10 codes
        icd10_codes = self._extract_icd10_codes(soap_note)

        # Create billing request
        billing_request = BillingRequest(
            session_id=session_id,
            patient_id=patient_id,
            provider_id=provider_id,
            cpt_codes=cpt_codes,
            icd10_codes=icd10_codes,
            duration_minutes=duration_minutes,
        )

        # Create invoice
        return await self.create_invoice(billing_request)
