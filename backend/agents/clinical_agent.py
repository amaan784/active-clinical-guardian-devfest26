"""
Synapse 2.0 Clinical Agent
Dedalus-style state machine for managing clinical encounter flow
"""

import asyncio
from enum import Enum
from typing import Optional, Callable, Any
from datetime import datetime
import uuid
import logging

from models.schemas import (
    ConsultSession,
    TranscriptSegment,
    SafetyCheckResult,
    SafetyLevel,
    SOAPNote,
    PatientData,
)

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    """Clinical agent states following Dedalus ADK pattern"""
    IDLE = "IDLE"                       # Waiting for consult to start
    LISTENING = "LISTENING"             # Actively transcribing
    PROCESSING = "PROCESSING"           # Running safety check
    INTERRUPTING = "INTERRUPTING"       # Delivering voice warning
    PAUSED = "PAUSED"                   # Doctor paused the session
    FINALIZING = "FINALIZING"           # Generating SOAP note & billing
    COMPLETED = "COMPLETED"             # Session ended
    ERROR = "ERROR"                     # Error state


class ClinicalAgent:
    """
    The Active Clinical Guardian Agent

    Manages the state of a clinical encounter, orchestrating:
    - Real-time transcription buffering
    - Periodic safety checks
    - Voice interruptions for dangerous conditions
    - Final documentation and billing
    """

    def __init__(
        self,
        patient_id: str,
        provider_id: str,
        patient_data: Optional[PatientData] = None,
        safety_check_interval: float = 5.0,
    ):
        self.session_id = str(uuid.uuid4())
        self.patient_id = patient_id
        self.provider_id = provider_id
        self.patient_data = patient_data
        self.safety_check_interval = safety_check_interval

        # State management
        self._state = AgentState.IDLE
        self._previous_state = AgentState.IDLE

        # Session data
        self.session = ConsultSession(
            session_id=self.session_id,
            patient_id=patient_id,
            provider_id=provider_id,
        )

        # Transcript buffer for current processing window
        self._transcript_buffer: list[str] = []
        self._full_transcript: list[TranscriptSegment] = []

        # Safety check tracking
        self._last_safety_check: Optional[datetime] = None
        self._pending_interruption: Optional[SafetyCheckResult] = None

        # Callbacks for external integrations
        self._on_state_change: Optional[Callable[[AgentState, AgentState], Any]] = None
        self._on_safety_alert: Optional[Callable[[SafetyCheckResult], Any]] = None
        self._on_interruption: Optional[Callable[[str], Any]] = None

        # Background tasks
        self._safety_check_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> AgentState:
        """Current agent state"""
        return self._state

    def _set_state(self, new_state: AgentState) -> None:
        """Transition to a new state with logging and callbacks"""
        if new_state == self._state:
            return

        self._previous_state = self._state
        self._state = new_state

        logger.info(f"Agent state transition: {self._previous_state} -> {new_state}")

        if self._on_state_change:
            asyncio.create_task(
                self._safe_callback(
                    self._on_state_change,
                    self._previous_state,
                    new_state
                )
            )

    async def _safe_callback(self, callback: Callable, *args) -> None:
        """Execute callback safely, catching any errors"""
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Callback error: {e}")

    # --- Event Handlers ---

    def set_callbacks(
        self,
        on_state_change: Optional[Callable[[AgentState, AgentState], Any]] = None,
        on_safety_alert: Optional[Callable[[SafetyCheckResult], Any]] = None,
        on_interruption: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """Register callback handlers for agent events"""
        self._on_state_change = on_state_change
        self._on_safety_alert = on_safety_alert
        self._on_interruption = on_interruption

    # --- State Transitions ---

    async def start_consult(self) -> None:
        """Begin the consultation session"""
        if self._state != AgentState.IDLE:
            raise ValueError(f"Cannot start consult from state: {self._state}")

        self.session.start_time = datetime.now()
        self._set_state(AgentState.LISTENING)

        # Start the background safety check loop
        self._safety_check_task = asyncio.create_task(self._safety_check_loop())

        logger.info(f"Consult started: {self.session_id}")

    async def pause_consult(self) -> None:
        """Pause the consultation"""
        if self._state not in [AgentState.LISTENING, AgentState.PROCESSING]:
            return

        self._set_state(AgentState.PAUSED)

    async def resume_consult(self) -> None:
        """Resume a paused consultation"""
        if self._state != AgentState.PAUSED:
            return

        self._set_state(AgentState.LISTENING)

    async def end_consult(self) -> SOAPNote:
        """End the consultation and generate final documentation"""
        if self._state == AgentState.COMPLETED:
            return self.session.soap_note

        # Cancel safety check loop
        if self._safety_check_task:
            self._safety_check_task.cancel()
            try:
                await self._safety_check_task
            except asyncio.CancelledError:
                pass

        self._set_state(AgentState.FINALIZING)

        # Generate SOAP note from transcript
        soap_note = await self._generate_soap_note()
        self.session.soap_note = soap_note
        self.session.end_time = datetime.now()
        self.session.status = "completed"

        self._set_state(AgentState.COMPLETED)

        logger.info(f"Consult ended: {self.session_id}")
        return soap_note

    # --- Transcript Processing ---

    async def add_transcript(self, text: str, speaker: str = "doctor") -> None:
        """Add transcribed text to the session"""
        if self._state not in [AgentState.LISTENING, AgentState.PROCESSING]:
            logger.warning(f"Cannot add transcript in state: {self._state}")
            return

        segment = TranscriptSegment(text=text, speaker=speaker)
        self._full_transcript.append(segment)
        self._transcript_buffer.append(text)
        self.session.transcript_segments.append(segment)

    def get_transcript_buffer(self) -> str:
        """Get the current transcript buffer for processing"""
        return " ".join(self._transcript_buffer)

    def clear_transcript_buffer(self) -> None:
        """Clear the transcript buffer after processing"""
        self._transcript_buffer.clear()

    def get_full_transcript(self) -> str:
        """Get the complete transcript as a string"""
        return " ".join(seg.text for seg in self._full_transcript)

    # --- Safety Check Loop ---

    async def _safety_check_loop(self) -> None:
        """Background loop for periodic safety checks"""
        while self._state in [AgentState.LISTENING, AgentState.PROCESSING, AgentState.PAUSED]:
            await asyncio.sleep(self.safety_check_interval)

            if self._state == AgentState.LISTENING and self._transcript_buffer:
                await self._run_safety_check()

    async def _run_safety_check(self) -> None:
        """Execute a safety check on the current buffer"""
        if not self._transcript_buffer:
            return

        self._set_state(AgentState.PROCESSING)

        # Get buffer content
        buffer_text = self.get_transcript_buffer()

        logger.info(f"Running safety check on: {buffer_text[:100]}...")

        # This will be replaced with actual K2 + Snowflake integration
        # Placeholder for now - actual implementation in the service layer
        self._last_safety_check = datetime.now()

        # Clear the buffer after processing
        self.clear_transcript_buffer()

        # Return to listening state
        self._set_state(AgentState.LISTENING)

    async def process_safety_result(self, result: SafetyCheckResult) -> None:
        """Process a safety check result from the safety service"""
        self.session.safety_checks.append(result)

        if self._on_safety_alert:
            await self._safe_callback(self._on_safety_alert, result)

        if result.requires_interruption:
            await self._trigger_interruption(result)

    async def _trigger_interruption(self, result: SafetyCheckResult) -> None:
        """Trigger a voice interruption for dangerous conditions"""
        self._set_state(AgentState.INTERRUPTING)
        self._pending_interruption = result

        warning_text = result.warning_message or self._generate_warning_text(result)

        logger.warning(f"INTERRUPTION TRIGGERED: {warning_text}")

        if self._on_interruption:
            await self._safe_callback(self._on_interruption, warning_text)

        # After interruption, return to listening
        self._set_state(AgentState.LISTENING)
        self._pending_interruption = None

    def _generate_warning_text(self, result: SafetyCheckResult) -> str:
        """Generate warning text for voice interruption"""
        if result.interactions:
            interaction = result.interactions[0]
            drugs = interaction.get("drugs", [])
            condition = interaction.get("condition", "potential interaction")
            return f"Doctor, wait. {condition} detected between {' and '.join(drugs)}. Please review before proceeding."

        return f"Doctor, safety alert: {result.recommendation or 'Please review the current prescription.'}"

    # --- Documentation Generation ---

    async def _generate_soap_note(self) -> SOAPNote:
        """Generate SOAP note from the transcript"""
        # This will be enhanced with AI-powered note generation
        # Placeholder implementation
        full_text = self.get_full_transcript()

        return SOAPNote(
            subjective=f"Patient encounter transcript: {full_text[:500]}...",
            objective="Vitals and examination findings to be added.",
            assessment="Clinical assessment pending review.",
            plan="Treatment plan as discussed.",
            icd10_codes=[],
            cpt_codes=["99214"],  # Default office visit code
        )

    # --- Session Info ---

    def get_session_info(self) -> dict:
        """Get current session information"""
        return {
            "session_id": self.session_id,
            "patient_id": self.patient_id,
            "provider_id": self.provider_id,
            "state": self._state.value,
            "start_time": self.session.start_time.isoformat() if self.session.start_time else None,
            "transcript_length": len(self._full_transcript),
            "safety_checks_count": len(self.session.safety_checks),
            "has_pending_interruption": self._pending_interruption is not None,
        }
