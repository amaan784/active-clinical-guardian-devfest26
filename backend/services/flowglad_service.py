"""
Synapse 2.0 Flowglad Service
Automated billing and CPT code generation

Reference: https://docs.flowglad.com/quickstart

Flowglad integration uses:
- FLOWGLAD_SECRET_KEY for authentication
- customerExternalId from YOUR database (not Flowglad's)
- useBilling hook for feature access checking
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
    # Evaluation & Management - Office Visits (2021 Guidelines)
    "new_patient_low": "99202",        # 15-29 min
    "new_patient_moderate": "99203",   # 30-44 min
    "new_patient_high": "99204",       # 45-59 min
    "new_patient_comprehensive": "99205",  # 60-74 min
    "established_low": "99212",        # 10-19 min
    "established_moderate": "99213",   # 20-29 min
    "established_high": "99214",       # 30-39 min
    "established_comprehensive": "99215",  # 40-54 min

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
    - Invoice creation via Flowglad API
    - Revenue cycle management

    Uses Flowglad's REST API with customerExternalId pattern
    where the customer ID is from YOUR database, not Flowglad's.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize HTTP client with Flowglad authentication"""
        if not self.settings.flowglad_api_key:
            logger.error("Flowglad API key not configured — set FLOWGLAD_API_KEY in .env")
            return

        self._client = httpx.AsyncClient(
            base_url=self.settings.flowglad_api_url,
            headers={
                "Authorization": f"Bearer {self.settings.flowglad_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        logger.info("Flowglad client initialized")

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
        - Total time on date of encounter
        - Medical decision making complexity
        """
        # Time-based determination (2021 guidelines)
        if duration_minutes >= 40 or safety_alerts_count >= 2:
            return "comprehensive"
        elif duration_minutes >= 30 or safety_alerts_count >= 1:
            return "high"
        elif duration_minutes >= 20:
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

    async def get_customer(self, customer_external_id: str) -> Optional[dict]:
        """
        Get or create a customer in Flowglad

        Uses customerExternalId which is the ID from YOUR database
        """
        if not self._client:
            raise RuntimeError("Flowglad not configured — set FLOWGLAD_API_KEY in .env")

        try:
            # Check if customer exists
            response = await self._client.get(
                f"/customers/{customer_external_id}"
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                # Create new customer
                return await self.create_customer(customer_external_id)
            else:
                logger.error(f"Flowglad get customer error: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Flowglad customer lookup error: {e}")
            return None

    async def create_customer(self, customer_external_id: str, details: dict = None) -> Optional[dict]:
        """
        Create a new customer in Flowglad

        Args:
            customer_external_id: Your app's customer/patient ID
            details: Customer details (name, email, etc.)
        """
        if not self._client:
            raise RuntimeError("Flowglad not configured — set FLOWGLAD_API_KEY in .env")

        try:
            response = await self._client.post(
                "/customers",
                json={
                    "externalId": customer_external_id,
                    **(details or {}),
                }
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Flowglad create customer error: {e}")
            return None

    async def create_invoice(
        self,
        billing_request: BillingRequest
    ) -> BillingResponse:
        """
        Create invoice via Flowglad API

        Args:
            billing_request: Billing details including CPT/ICD codes

        Returns:
            BillingResponse with invoice details
        """
        logger.info(f"Creating invoice for session: {billing_request.session_id}")

        # Calculate estimated amount based on CPT codes
        # Simplified pricing - in production use fee schedules
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

        if not self._client:
            raise RuntimeError("Flowglad not configured — set FLOWGLAD_API_KEY in .env")

        try:
            # Ensure customer exists
            await self.get_customer(billing_request.patient_id)

            # Create invoice
            response = await self._client.post(
                "/invoices",
                json={
                    "customerExternalId": billing_request.patient_id,
                    "externalId": billing_request.session_id,
                    "items": [
                        {
                            "description": f"CPT {code}",
                            "quantity": 1,
                            "unitPrice": base_amounts.get(code, 100.00),
                            "metadata": {
                                "cpt_code": code,
                                "service_date": billing_request.service_date.isoformat(),
                            }
                        }
                        for code in billing_request.cpt_codes
                    ],
                    "metadata": {
                        "session_id": billing_request.session_id,
                        "provider_id": billing_request.provider_id,
                        "icd10_codes": billing_request.icd10_codes,
                        "duration_minutes": billing_request.duration_minutes,
                    },
                }
            )
            response.raise_for_status()
            data = response.json()

            return BillingResponse(
                invoice_id=data.get("id", f"INV-{billing_request.session_id[:8]}"),
                total_amount=data.get("total", total_amount),
                status=data.get("status", "created"),
                created_at=datetime.fromisoformat(data["createdAt"]) if "createdAt" in data else datetime.now(),
            )

        except Exception as e:
            logger.error(f"Flowglad API error: {e}")
            raise

    async def check_feature_access(
        self,
        customer_external_id: str,
        feature_name: str
    ) -> bool:
        """
        Check if customer has access to a feature

        Uses Flowglad's useBilling pattern with checkFeatureAccess
        """
        if not self._client:
            raise RuntimeError("Flowglad not configured — set FLOWGLAD_API_KEY in .env")

        try:
            response = await self._client.get(
                f"/customers/{customer_external_id}/features/{feature_name}"
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("hasAccess", False)
            return False

        except Exception as e:
            logger.error(f"Feature access check error: {e}")
            return True  # Fail open for hackathon

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

    async def get_billing_summary(self, patient_id: str) -> dict:
        """Get billing summary for a patient"""
        if not self._client:
            raise RuntimeError("Flowglad not configured — set FLOWGLAD_API_KEY in .env")

        try:
            response = await self._client.get(
                f"/customers/{patient_id}/invoices"
            )
            response.raise_for_status()
            invoices = response.json()

            total = sum(inv.get("total", 0) for inv in invoices)
            pending = sum(inv.get("total", 0) for inv in invoices if inv.get("status") == "pending")
            paid = sum(inv.get("total", 0) for inv in invoices if inv.get("status") == "paid")

            return {
                "total_invoices": len(invoices),
                "total_amount": total,
                "pending_amount": pending,
                "paid_amount": paid,
            }

        except Exception as e:
            logger.error(f"Billing summary error: {e}")
            return {
                "total_invoices": 0,
                "total_amount": 0.0,
                "pending_amount": 0.0,
                "paid_amount": 0.0,
            }
