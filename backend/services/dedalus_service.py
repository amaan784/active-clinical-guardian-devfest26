"""
Synapse 2.0 Dedalus Labs Service
Agent orchestration using Dedalus SDK and DedalusRunner

Reference: https://github.com/dedalus-labs/dedalus-sdk-python
"""

import logging
from typing import Optional, Any
import json

from config import get_settings

logger = logging.getLogger(__name__)

# Conditional import for Dedalus SDK
try:
    from dedalus_labs import AsyncDedalus
    DEDALUS_AVAILABLE = True
except ImportError:
    DEDALUS_AVAILABLE = False
    logger.warning("Dedalus SDK not available")


class DedalusService:
    """
    Dedalus Labs integration for agent orchestration

    Uses the Dedalus SDK to:
    - Orchestrate multi-step clinical workflows
    - Route to different LLM providers
    - Connect to MCP tools for enhanced capabilities
    - Generate structured clinical documentation
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[AsyncDedalus] = None

    async def initialize(self) -> bool:
        """Initialize the Dedalus client"""
        if not DEDALUS_AVAILABLE:
            logger.warning("Dedalus SDK not available, using local orchestration")
            return True

        if not self.settings.dedalus_api_key:
            logger.info("Dedalus API key not configured, using local orchestration")
            return True

        try:
            self._client = AsyncDedalus(
                api_key=self.settings.dedalus_api_key,
                environment=self.settings.dedalus_environment,
            )
            logger.info("Dedalus client initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Dedalus client: {e}")
            return False

    async def close(self) -> None:
        """Close the Dedalus client"""
        # AsyncDedalus handles cleanup automatically
        pass

    async def generate_soap_note(
        self,
        transcript: str,
        patient_context: dict,
    ) -> dict:
        """
        Generate a SOAP note from transcript using Dedalus

        Args:
            transcript: Full encounter transcript
            patient_context: Patient demographics and history

        Returns:
            Structured SOAP note
        """
        if not self._client:
            # Fallback to local generation
            return self._generate_soap_local(transcript, patient_context)

        try:
            prompt = f"""Generate a structured SOAP note from this clinical encounter.

PATIENT CONTEXT:
{json.dumps(patient_context, indent=2)}

TRANSCRIPT:
{transcript}

Generate a JSON response with this structure:
{{
    "subjective": "patient's chief complaint and history",
    "objective": "examination findings and vitals",
    "assessment": "clinical assessment and diagnoses",
    "plan": "treatment plan and follow-up",
    "icd10_codes": ["list of applicable ICD-10 codes"],
    "cpt_codes": ["list of applicable CPT codes"]
}}"""

            response = await self._client.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",  # Or any available model
                messages=[
                    {
                        "role": "system",
                        "content": "You are a medical documentation specialist. Generate accurate, concise SOAP notes in JSON format."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2048,
            )

            content = response.choices[0].message.content
            # Parse JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())

            return self._generate_soap_local(transcript, patient_context)

        except Exception as e:
            logger.error(f"Dedalus SOAP generation error: {e}")
            return self._generate_soap_local(transcript, patient_context)

    def _generate_soap_local(self, transcript: str, patient_context: dict) -> dict:
        """Local fallback for SOAP note generation"""
        return {
            "subjective": f"Patient encounter transcript: {transcript[:500]}...",
            "objective": "Vitals and examination findings to be documented.",
            "assessment": "Clinical assessment based on encounter.",
            "plan": "Treatment plan as discussed during visit.",
            "icd10_codes": [],
            "cpt_codes": ["99214"],  # Default E/M code
        }

    async def analyze_clinical_intent(
        self,
        transcript_segment: str,
    ) -> dict:
        """
        Analyze a transcript segment to extract clinical intent

        Args:
            transcript_segment: Recent transcript text

        Returns:
            Dict with extracted medications, procedures, diagnoses
        """
        if not self._client:
            return {"medications": [], "procedures": [], "diagnoses": []}

        try:
            response = await self._client.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",
                messages=[
                    {
                        "role": "system",
                        "content": """Extract clinical intent from the transcript. Return JSON:
{
    "medications": [{"name": "drug", "dosage": "amount", "action": "prescribe|discuss|discontinue"}],
    "procedures": [{"name": "procedure", "action": "order|discuss"}],
    "diagnoses": [{"name": "condition", "icd10": "code if known"}]
}"""
                    },
                    {"role": "user", "content": transcript_segment}
                ],
                temperature=0.1,
                max_tokens=1024,
            )

            content = response.choices[0].message.content
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())

        except Exception as e:
            logger.error(f"Clinical intent analysis error: {e}")

        return {"medications": [], "procedures": [], "diagnoses": []}

    async def stream_response(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful clinical assistant.",
    ):
        """
        Stream a response from Dedalus

        Args:
            prompt: User prompt
            system_prompt: System context

        Yields:
            Response chunks
        """
        if not self._client:
            yield "Dedalus not configured. Using local mode."
            return

        try:
            stream = await self._client.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"Dedalus streaming error: {e}")
            yield f"Error: {str(e)}"
