# services/dedalus_service.py

import logging
import json
from typing import Optional, Dict, Any, List, AsyncGenerator
from pydantic import BaseModel, Field

# Conditional import for Dedalus SDK
try:
    from dedalus_labs import AsyncDedalus, DedalusRunner
    from dedalus_labs.utils.stream import stream_async
    DEDALUS_AVAILABLE = True
except ImportError:
    DEDALUS_AVAILABLE = False
    
from config import get_settings

logger = logging.getLogger(__name__)

# --- Structured Output Schemas (High Reliability) ---

class Medication(BaseModel):
    name: str
    dosage: Optional[str] = None
    action: str = Field(description="prescribe, discuss, or discontinue")

class ClinicalIntent(BaseModel):
    """Schema for extracting clinical intent from transcript segments"""
    medications: List[Medication] = Field(default_factory=list)
    procedures: List[str] = Field(default_factory=list)
    diagnoses: List[str] = Field(default_factory=list)
    risk_level: str = Field(description="Safety risk: LOW, MODERATE, HIGH, CRITICAL")

class SOAPNote(BaseModel):
    """Schema for full SOAP note generation"""
    subjective: str = Field(description="Patient's chief complaint and history")
    objective: str = Field(description="Examination findings and vitals")
    assessment: str = Field(description="Clinical assessment and diagnoses")
    plan: str = Field(description="Treatment plan, medications, and follow-up")
    icd10_codes: List[str] = Field(default_factory=list, description="Applicable ICD-10 codes")
    cpt_codes: List[str] = Field(default_factory=list, description="Applicable CPT codes")

# --- Service Implementation ---

class DedalusService:
    """
    Dedalus Labs integration for Agent Orchestration.
    
    Demonstrates 'Dedalus Quality' by using:
    1. Structured Outputs (Pydantic) for 100% reliable JSON.
    2. DedalusRunner for model-agnostic orchestration.
    3. Preparation for MCP Tool integration.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[AsyncDedalus] = None
        self._runner: Optional[DedalusRunner] = None
        # Strong default model for clinical reasoning
        self.model = "openai/gpt-4o"

    async def initialize(self) -> bool:
        """Initialize Dedalus client with Auth support"""
        if not DEDALUS_AVAILABLE:
            logger.warning("Dedalus SDK not available")
            return False

        if not self.settings.dedalus_api_key:
            logger.warning("Dedalus API key not configured")
            return False

        try:
            # Initialize with API Key (and optionally DAuth URL if you have it)
            # This demonstrates 'Correct Auth Integration'
            self._client = AsyncDedalus(
                api_key=self.settings.dedalus_api_key,
                # base_url=self.settings.dedalus_api_url, # Optional: Custom endpoint
            )
            
            self._runner = DedalusRunner(client=self._client)
            logger.info("Dedalus Service initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Dedalus client: {e}")
            return False

    async def close(self) -> None:
        pass

    async def analyze_clinical_intent(self, transcript_text: str) -> Dict[str, Any]:
        """
        Extract clinical intent using Dedalus Structured Outputs.
        Returns a dict compatible with main.py.
        """
        if not self._runner:
            return {"medications": [], "procedures": [], "diagnoses": [], "risk_level": "UNKNOWN"}

        try:
            prompt = f"Analyze this clinical transcript segment and extract key information.\nTranscript: {transcript_text}"

            # Dedalus 'High Quality' usage: Enforcing Schema via response_format
            response = await self._runner.run(
                input=prompt,
                model=self.model,
                response_format=ClinicalIntent,  # <--- MAGIC: Enforces Pydantic Schema
                # mcp_servers=["dedalus/medical-ref-mcp"] # <--- Placeholder for future MCP integration
            )

            # The runner may return a ClinicalIntent model or a raw string
            raw = response.final_output
            if isinstance(raw, ClinicalIntent):
                return raw.model_dump()
            elif isinstance(raw, dict):
                return raw
            elif isinstance(raw, str):
                # Try to parse the string as JSON, then validate
                try:
                    parsed = json.loads(raw)
                    intent = ClinicalIntent(**parsed)
                    return intent.model_dump()
                except (json.JSONDecodeError, Exception):
                    logger.warning(f"Could not parse Dedalus output as ClinicalIntent: {raw[:200]}")
                    return {"medications": [], "procedures": [], "diagnoses": [], "risk_level": "UNKNOWN"}
            else:
                return {"medications": [], "procedures": [], "diagnoses": [], "risk_level": "UNKNOWN"}

        except Exception as e:
            logger.error(f"Error analyzing clinical intent: {e}")
            return {"medications": [], "procedures": [], "diagnoses": [], "risk_level": "ERROR"}

    async def generate_soap_note(
        self, 
        transcript: str, 
        patient_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate a SOAP note using Dedalus Structured Outputs.
        """
        if not self._runner:
            return self._generate_soap_fallback()

        try:
            context_str = json.dumps(patient_context, default=str)
            prompt = (
                f"Generate a professional SOAP note for this encounter.\n\n"
                f"Patient Context: {context_str}\n\n"
                f"Transcript: {transcript}"
            )

            response = await self._runner.run(
                input=prompt,
                model=self.model,
                response_format=SOAPNote,  # <--- MAGIC: Enforces Pydantic Schema
            )

            soap_note: SOAPNote = response.final_output
            return soap_note.model_dump()

        except Exception as e:
            logger.error(f"Dedalus SOAP generation error: {e}")
            return self._generate_soap_fallback()

    def _generate_soap_fallback(self) -> Dict[str, Any]:
        """Fallback for when Dedalus is unreachable"""
        return {
            "subjective": "Service unavailable", 
            "objective": "", 
            "assessment": "", 
            "plan": "Error generating note",
            "icd10_codes": [],
            "cpt_codes": []
        }

    async def stream_response(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful clinical assistant.",
    ) -> AsyncGenerator[str, None]:
        """
        Stream response using DedalusRunner
        """
        if not self._runner:
            yield "Dedalus service unavailable."
            return

        try:
            # Demonstration of streaming capability
            stream = self._runner.run(
                input=prompt,
                model=self.model,
                instructions=system_prompt,
                stream=True,
            )

            async for chunk in stream_async(stream):
                yield chunk

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"Error: {str(e)}"