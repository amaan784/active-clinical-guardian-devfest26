"""
The Active Clinical Guardian - K2 Think Safety Service
System 2 reasoning for drug interaction validation using K2-Think-V2

K2 Think is accessed via OpenAI-compatible API hosted at api.k2think.ai
Reference: https://api.k2think.ai/v1/chat/completions
"""

import logging
import json
from typing import Optional
import re

from config import get_settings
from models.schemas import SafetyCheckResult, SafetyLevel, PatientData, Medication

logger = logging.getLogger(__name__)

# Conditional import for OpenAI client
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI SDK not available for K2 Think")


# Known dangerous drug interactions database (fallback)
KNOWN_INTERACTIONS = {
    ("SSRI", "Triptan"): {
        "condition": "Serotonin Syndrome Risk",
        "severity": SafetyLevel.DANGER,
        "description": "Concurrent use of triptans with SSRIs may cause serotonin syndrome",
        "recommendation": "Consider alternative migraine treatment such as gepants (ubrogepant) or NSAIDs",
    },
    ("SSRI", "MAOI"): {
        "condition": "Serotonin Syndrome - CRITICAL",
        "severity": SafetyLevel.CRITICAL,
        "description": "Concurrent use is contraindicated - life-threatening serotonin syndrome",
        "recommendation": "STOP - Do not prescribe. Allow 14-day washout period between medications",
    },
    ("Anticoagulant", "NSAID"): {
        "condition": "Increased Bleeding Risk",
        "severity": SafetyLevel.DANGER,
        "description": "NSAIDs increase bleeding risk in patients on anticoagulants",
        "recommendation": "Consider acetaminophen for pain management instead",
    },
    ("ACE Inhibitor", "Potassium Supplement"): {
        "condition": "Hyperkalemia Risk",
        "severity": SafetyLevel.CAUTION,
        "description": "ACE inhibitors can increase potassium levels",
        "recommendation": "Monitor potassium levels closely if supplementation is necessary",
    },
    ("Beta Blocker", "Calcium Channel Blocker"): {
        "condition": "Bradycardia/Heart Block Risk",
        "severity": SafetyLevel.CAUTION,
        "description": "Combined use may cause severe bradycardia",
        "recommendation": "Monitor heart rate and ECG",
    },
}

# Drug class mappings
DRUG_CLASS_MAP = {
    "sertraline": "SSRI",
    "fluoxetine": "SSRI",
    "paroxetine": "SSRI",
    "escitalopram": "SSRI",
    "citalopram": "SSRI",
    "zoloft": "SSRI",
    "prozac": "SSRI",
    "sumatriptan": "Triptan",
    "rizatriptan": "Triptan",
    "eletriptan": "Triptan",
    "imitrex": "Triptan",
    "maxalt": "Triptan",
    "warfarin": "Anticoagulant",
    "coumadin": "Anticoagulant",
    "heparin": "Anticoagulant",
    "eliquis": "Anticoagulant",
    "xarelto": "Anticoagulant",
    "ibuprofen": "NSAID",
    "naproxen": "NSAID",
    "aspirin": "NSAID",
    "advil": "NSAID",
    "aleve": "NSAID",
    "lisinopril": "ACE Inhibitor",
    "enalapril": "ACE Inhibitor",
    "metoprolol": "Beta Blocker",
    "atenolol": "Beta Blocker",
    "propranolol": "Beta Blocker",
    "phenelzine": "MAOI",
    "tranylcypromine": "MAOI",
    "selegiline": "MAOI",
    # Penicillin-class antibiotics (common allergy triggers)
    "penicillin": "Penicillin",
    "amoxicillin": "Penicillin",
    "ampicillin": "Penicillin",
    "augmentin": "Penicillin",
    "piperacillin": "Penicillin",
    # Sulfonamides (common allergy triggers)
    "sulfamethoxazole": "Sulfonamide",
    "bactrim": "Sulfonamide",
    "septra": "Sulfonamide",
    # Other common medications
    "acetaminophen": "Analgesic",
    "tylenol": "Analgesic",
    "amlodipine": "Calcium Channel Blocker",
    "diltiazem": "Calcium Channel Blocker",
    "verapamil": "Calcium Channel Blocker",
    "omeprazole": "PPI",
    "pantoprazole": "PPI",
    "gabapentin": "Anticonvulsant",
    "pregabalin": "Anticonvulsant",
}


# K2 Think prompt template for drug safety reasoning
K2_SAFETY_PROMPT = """You are K2-Think, a medical safety reasoning system. Analyze the following clinical scenario for drug interactions and safety concerns.

PATIENT INFORMATION:
- Current Medications: {current_meds}
- Known Allergies: {allergies}
- Medical History: {history}

DOCTOR'S STATEMENT:
"{transcript}"

RELEVANT CLINICAL GUIDELINES:
{guidelines_text}

TASK:
1. Identify any medications mentioned in the doctor's statement
2. Check for dangerous drug-drug interactions with current medications
3. Check for allergy contraindications
4. Cross-reference with the clinical guidelines above
5. Assess overall safety risk

Respond in JSON format:
{{
    "detected_medications": ["list of medications mentioned"],
    "interactions": [
        {{
            "drugs": ["drug1", "drug2"],
            "severity": "SAFE|CAUTION|DANGER|CRITICAL",
            "condition": "name of interaction",
            "description": "explanation",
            "recommendation": "what to do instead"
        }}
    ],
    "allergy_conflicts": [
        {{
            "drug": "medication",
            "allergy": "allergen",
            "severity": "CRITICAL"
        }}
    ],
    "overall_safety": "SAFE|CAUTION|DANGER|CRITICAL",
    "risk_score": 0.0-1.0,
    "warning_message": "brief warning if any risk",
    "recommendation": "overall recommendation"
}}"""


class K2SafetyService:
    """
    K2 Think integration for System 2 reasoning on drug safety

    Uses K2-Think-V2 model via OpenAI-compatible API for:
    - Drug-drug interactions
    - Drug-allergy contraindications
    - Dosage safety
    - Clinical guideline compliance

    Falls back to rule-based checking if K2 is unavailable.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[AsyncOpenAI] = None
        self._use_k2 = False

    async def initialize(self) -> None:
        """Initialize the K2 Think client via OpenAI-compatible API"""
        if not OPENAI_AVAILABLE:
            logger.warning("OpenAI SDK not available, using rule-based fallback")
            return

        if not self.settings.k2_base_url:
            logger.info("K2 base URL not configured, using rule-based fallback")
            return

        if not self.settings.k2_api_key:
            logger.info("K2 API key not configured, using rule-based fallback")
            return

        try:
            self._client = AsyncOpenAI(
                api_key=self.settings.k2_api_key,
                base_url=self.settings.k2_base_url,
            )
            self._use_k2 = True
            logger.info(f"K2 Think client initialized: {self.settings.k2_base_url}")
        except Exception as e:
            logger.error(f"Failed to initialize K2 client: {e}")

    async def close(self) -> None:
        """Close the client"""
        if self._client:
            await self._client.close()

    def _extract_medications_from_text(self, text: str) -> list[str]:
        """Extract medication names from transcript text"""
        text_lower = text.lower()
        found_medications = []

        for drug_name in DRUG_CLASS_MAP.keys():
            if drug_name in text_lower:
                found_medications.append(drug_name)

        # Also look for common prescription patterns
        patterns = [
            r"prescrib(?:e|ing)\s+(\w+)",
            r"start(?:ing)?\s+(?:on\s+)?(\w+)",
            r"(\w+)\s+\d+\s*mg",
            r"give\s+(?:them\s+)?(\w+)",
            r"try\s+(\w+)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if match in DRUG_CLASS_MAP:
                    found_medications.append(match)

        return list(set(found_medications))

    def _get_drug_class(self, drug_name: str) -> Optional[str]:
        """Get the drug class for a medication"""
        return DRUG_CLASS_MAP.get(drug_name.lower())

    def _check_interactions_rule_based(
        self,
        new_medications: list[str],
        current_medications: list[Medication]
    ) -> list[dict]:
        """Rule-based interaction checking (fallback)"""
        interactions = []

        current_classes = set()
        for med in current_medications:
            if med.drug_class:
                current_classes.add(med.drug_class)
            else:
                drug_class = self._get_drug_class(med.name)
                if drug_class:
                    current_classes.add(drug_class)

        new_classes = set()
        for drug in new_medications:
            drug_class = self._get_drug_class(drug)
            if drug_class:
                new_classes.add(drug_class)

        for new_class in new_classes:
            for current_class in current_classes:
                key1 = (new_class, current_class)
                key2 = (current_class, new_class)

                interaction = KNOWN_INTERACTIONS.get(key1) or KNOWN_INTERACTIONS.get(key2)
                if interaction:
                    interactions.append({
                        "drugs": [new_class, current_class],
                        "condition": interaction["condition"],
                        "severity": interaction["severity"],
                        "description": interaction["description"],
                        "recommendation": interaction["recommendation"],
                    })

        return interactions

    async def _check_with_k2_think(
        self,
        transcript_text: str,
        patient_data: PatientData,
        clinical_guidelines: Optional[list[dict]] = None,
    ) -> Optional[dict]:
        """Use K2 Think for advanced reasoning"""
        if not self._client or not self._use_k2:
            return None

        try:
            # Format patient data for prompt
            current_meds = ", ".join(
                f"{m.name} {m.dosage}" for m in patient_data.current_medications
            )
            allergies = ", ".join(patient_data.allergies) or "None"
            history = ", ".join(patient_data.medical_history) or "None"

            # Format clinical guidelines from Snowflake RAG
            if clinical_guidelines:
                guidelines_text = "\n".join(
                    f"- [{g['source']}] {g['title']}: {g['content']}"
                    for g in clinical_guidelines
                )
            else:
                guidelines_text = "No specific guidelines retrieved."

            prompt = K2_SAFETY_PROMPT.format(
                current_meds=current_meds,
                allergies=allergies,
                history=history,
                transcript=transcript_text,
                guidelines_text=guidelines_text,
            )

            # Call K2 Think via hosted OpenAI-compatible API
            response = await self._client.chat.completions.create(
                model=self.settings.k2_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are K2-Think, a medical safety reasoning assistant. Always respond with valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=1.0,
                max_tokens=2048,
            )

            # Parse the response
            content = response.choices[0].message.content
            # Extract JSON from response (K2 may include thinking tokens)
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())

            logger.warning("K2 response did not contain valid JSON")
            return None

        except Exception as e:
            logger.error(f"K2 Think API error: {e}")
            return None

    async def check_safety(
        self,
        transcript_text: str,
        patient_data: PatientData,
        clinical_guidelines: Optional[list[dict]] = None
    ) -> SafetyCheckResult:
        """
        Perform comprehensive safety check

        Uses K2 Think for advanced reasoning if available,
        falls back to rule-based checking otherwise.

        Args:
            transcript_text: Current transcript buffer
            patient_data: Patient's medical record
            clinical_guidelines: Relevant clinical guidelines from Snowflake

        Returns:
            SafetyCheckResult with risk analysis
        """
        logger.info(f"Running safety check on transcript: {transcript_text[:100]}...")

        # Try K2 Think first for advanced reasoning
        if self._use_k2:
            k2_result = await self._check_with_k2_think(transcript_text, patient_data, clinical_guidelines)
            if k2_result:
                logger.info("Using K2 Think reasoning result")
                return SafetyCheckResult(
                    safety_level=SafetyLevel(k2_result.get("overall_safety", "SAFE")),
                    risk_score=float(k2_result.get("risk_score", 0.0)),
                    detected_medications=k2_result.get("detected_medications", []),
                    interactions=k2_result.get("interactions", []),
                    warning_message=k2_result.get("warning_message"),
                    recommendation=k2_result.get("recommendation"),
                    requires_interruption=k2_result.get("overall_safety") in ["DANGER", "CRITICAL"],
                )

        # Fallback to rule-based checking
        logger.info("Using rule-based safety checking")

        detected_medications = self._extract_medications_from_text(transcript_text)

        if detected_medications:
            logger.info(f"Detected medications in transcript: {detected_medications}")
        else:
            logger.info("No known medications detected in transcript, checking allergies only")

        # Check for drug interactions (only if medications were detected)
        interactions = self._check_interactions_rule_based(
            detected_medications,
            patient_data.current_medications
        ) if detected_medications else []

        # Check for allergy conflicts (against detected medications)
        allergy_conflicts = []
        for drug in detected_medications:
            drug_class = self._get_drug_class(drug)
            for allergy in patient_data.allergies:
                allergy_lower = allergy.lower()
                # Direct name match (e.g. "penicillin" vs allergy "Penicillin")
                if allergy_lower in drug.lower() or drug.lower() in allergy_lower:
                    allergy_conflicts.append({
                        "drug": drug,
                        "allergy": allergy,
                        "severity": SafetyLevel.CRITICAL,
                    })
                # Class match (e.g. drug "amoxicillin" → class "Penicillin" vs allergy "Penicillin")
                elif drug_class and allergy_lower in drug_class.lower():
                    allergy_conflicts.append({
                        "drug": drug,
                        "allergy": allergy,
                        "severity": SafetyLevel.CRITICAL,
                    })

        # Also scan raw transcript for allergy keywords even if no drug was detected
        # This catches cases like typing just "Penicillin" without a prescription verb
        if not allergy_conflicts:
            transcript_lower = transcript_text.lower()
            for allergy in patient_data.allergies:
                if allergy.lower() in transcript_lower:
                    allergy_conflicts.append({
                        "drug": allergy,
                        "allergy": allergy,
                        "severity": SafetyLevel.CRITICAL,
                    })

        # Determine overall safety level
        if allergy_conflicts:
            safety_level = SafetyLevel.CRITICAL
            risk_score = 1.0
            warning = f"ALLERGY ALERT: Patient is allergic to {allergy_conflicts[0]['allergy']}!"
        elif interactions:
            severities = [i["severity"] for i in interactions]
            if SafetyLevel.CRITICAL in severities:
                safety_level = SafetyLevel.CRITICAL
                risk_score = 1.0
            elif SafetyLevel.DANGER in severities:
                safety_level = SafetyLevel.DANGER
                risk_score = 0.8
            else:
                safety_level = SafetyLevel.CAUTION
                risk_score = 0.5

            primary_interaction = interactions[0]
            warning = f"{primary_interaction['condition']}: {primary_interaction['description']}"
        else:
            safety_level = SafetyLevel.SAFE
            risk_score = 0.1
            warning = None

        requires_interruption = safety_level in [SafetyLevel.DANGER, SafetyLevel.CRITICAL]

        result = SafetyCheckResult(
            safety_level=safety_level,
            risk_score=risk_score,
            detected_medications=detected_medications,
            interactions=interactions,
            warning_message=warning,
            recommendation=interactions[0]["recommendation"] if interactions else None,
            requires_interruption=requires_interruption,
        )

        if requires_interruption:
            logger.warning(f"SAFETY ALERT: {result.warning_message}")

        return result
