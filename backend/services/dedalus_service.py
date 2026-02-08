"""
Synapse 2.0 Dedalus Labs Service
Agent orchestration using Dedalus SDK and DedalusRunner

Reference: https://docs.dedaluslabs.ai
"""

import logging
import json
from typing import Optional, AsyncGenerator

from config import get_settings

logger = logging.getLogger(__name__)

# Conditional import for Dedalus SDK
try:
    from dedalus_labs import AsyncDedalus, DedalusRunner
    from dedalus_labs.utils.stream import stream_async
    DEDALUS_AVAILABLE = True
except ImportError:
    DEDALUS_AVAILABLE = False
    logger.warning("Dedalus SDK not available")


class DedalusService:
    """
    Dedalus Labs integration for agent orchestration

    Uses the Dedalus SDK with DedalusRunner to:
    - Orchestrate multi-step clinical workflows
    - Route to different LLM providers
    - Connect to MCP tools for enhanced capabilities
    - Generate structured clinical documentation
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[AsyncDedalus] = None
        self._runner: Optional[DedalusRunner] = None

    async def initialize(self) -> bool:
        """Initialize the Dedalus client and runner"""
        if not DEDALUS_AVAILABLE:
            logger.warning("Dedalus SDK not available, using local orchestration")
            return True

        if not self.settings.dedalus_api_key:
            logger.info("Dedalus API key not configured, using local orchestration")
            return True

        try:
            self._client = AsyncDedalus(
                api_key=self.settings.dedalus_api_key,
            )
            self._runner = DedalusRunner(self._client)
            logger.info("Dedalus client and runner initialized successfully")
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
        Generate a SOAP note from transcript using Dedalus DedalusRunner

        Args:
            transcript: Full encounter transcript
            patient_context: Patient demographics and history

        Returns:
            Structured SOAP note
        """
        if not self._runner:
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
}}

IMPORTANT: Return ONLY the JSON object, no other text."""

            response = await self._runner.run(
                input=prompt,
                model=["anthropic/claude-3.5-sonnet"],
                instructions="You are a medical documentation specialist. Generate accurate, concise SOAP notes. Always respond with valid JSON only.",
                stream=False,
            )

            # Extract content from runner response
            content = self._extract_response_text(response)
            if content:
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
        if not self._runner:
            return {"medications": [], "procedures": [], "diagnoses": []}

        try:
            response = await self._runner.run(
                input=f"""Extract clinical intent from this transcript segment. Return JSON only:
{{
    "medications": [{{"name": "drug", "dosage": "amount", "action": "prescribe|discuss|discontinue"}}],
    "procedures": [{{"name": "procedure", "action": "order|discuss"}}],
    "diagnoses": [{{"name": "condition", "icd10": "code if known"}}]
}}

Transcript segment:
{transcript_segment}""",
                model=["anthropic/claude-3.5-sonnet"],
                instructions="Extract clinical intent from medical transcripts. Always respond with valid JSON only.",
                stream=False,
            )

            content = self._extract_response_text(response)
            if content:
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
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response from Dedalus using DedalusRunner

        Args:
            prompt: User prompt
            system_prompt: System context

        Yields:
            Response chunks
        """
        if not self._runner:
            yield "Dedalus not configured. Using local mode."
            return

        try:
            response = await self._runner.run(
                input=prompt,
                model=["anthropic/claude-3.5-sonnet"],
                instructions=system_prompt,
                stream=True,
            )

            async for chunk in stream_async(response):
                yield chunk

        except Exception as e:
            logger.error(f"Dedalus streaming error: {e}")
            yield f"Error: {str(e)}"

    def _extract_response_text(self, response) -> Optional[str]:
        """
        Extract text content from a DedalusRunner response.

        The runner may return different response formats depending on
        the model and configuration. This method handles the common cases.
        """
        if response is None:
            return None

        # If it's already a string, return directly
        if isinstance(response, str):
            return response

        # If it has an output attribute (common runner response)
        if hasattr(response, 'output'):
            return str(response.output)

        # If it has a content attribute
        if hasattr(response, 'content'):
            return str(response.content)

        # If it's dict-like with an output or content key
        if isinstance(response, dict):
            return response.get('output') or response.get('content') or str(response)

        # Last resort: stringify it
        return str(response)
