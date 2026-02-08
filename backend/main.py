"""
Synapse 2.0 - The Active Clinical Guardian
Main FastAPI Application

This is the central orchestrator that manages:
- WebSocket connections for real-time audio streaming
- Clinical agent state management
- Integration with Snowflake, K2, ElevenLabs, and Flowglad
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import get_settings
from agents.clinical_agent import ClinicalAgent, AgentState
from services.snowflake_service import SnowflakeService
from services.k2_service import K2SafetyService
from services.elevenlabs_service import ElevenLabsService, AudioStreamProcessor
from services.flowglad_service import FlowgladService
from models.schemas import SafetyCheckResult, PatientData

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global service instances
snowflake_service: Optional[SnowflakeService] = None
k2_service: Optional[K2SafetyService] = None
elevenlabs_service: Optional[ElevenLabsService] = None
flowglad_service: Optional[FlowgladService] = None

# Active sessions tracking
active_sessions: dict[str, ClinicalAgent] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global snowflake_service, k2_service, elevenlabs_service, flowglad_service

    # Startup
    logger.info("Initializing Synapse 2.0 services...")

    snowflake_service = SnowflakeService()
    await snowflake_service.connect()

    k2_service = K2SafetyService()
    await k2_service.initialize()

    elevenlabs_service = ElevenLabsService()
    await elevenlabs_service.initialize()

    flowglad_service = FlowgladService()
    await flowglad_service.initialize()

    logger.info("All services initialized successfully")

    yield

    # Shutdown
    logger.info("Shutting down Synapse 2.0...")

    if snowflake_service:
        await snowflake_service.disconnect()
    if k2_service:
        await k2_service.close()
    if elevenlabs_service:
        await elevenlabs_service.close()
    if flowglad_service:
        await flowglad_service.close()

    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Synapse 2.0",
    description="The Active Clinical Guardian - Real-time clinical safety monitoring",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Models ---

class StartConsultRequest(BaseModel):
    patient_id: str
    provider_id: str


class StartConsultResponse(BaseModel):
    session_id: str
    patient_name: str
    status: str


class TranscriptInput(BaseModel):
    session_id: str
    text: str
    speaker: str = "doctor"


class EndConsultResponse(BaseModel):
    session_id: str
    soap_note: dict
    billing: dict
    duration_minutes: int


# --- REST Endpoints ---

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Synapse 2.0",
        "status": "operational",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "services": {
            "snowflake": snowflake_service is not None,
            "k2": k2_service is not None,
            "elevenlabs": elevenlabs_service is not None,
            "flowglad": flowglad_service is not None,
        },
        "active_sessions": len(active_sessions),
    }


@app.post("/api/consult/start", response_model=StartConsultResponse)
async def start_consult(request: StartConsultRequest):
    """Start a new consultation session"""
    logger.info(f"Starting consult for patient: {request.patient_id}")

    # Get patient data from Snowflake
    patient_data = await snowflake_service.get_patient_data(request.patient_id)

    if not patient_data:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Create clinical agent
    agent = ClinicalAgent(
        patient_id=request.patient_id,
        provider_id=request.provider_id,
        patient_data=patient_data,
        safety_check_interval=get_settings().safety_check_interval,
    )

    # Start the consultation
    await agent.start_consult()

    # Store in active sessions
    active_sessions[agent.session_id] = agent

    logger.info(f"Consult started: {agent.session_id}")

    return StartConsultResponse(
        session_id=agent.session_id,
        patient_name=patient_data.name,
        status="active",
    )


@app.post("/api/consult/{session_id}/transcript")
async def add_transcript(session_id: str, input_data: TranscriptInput):
    """Add transcript text to an active session (for non-WebSocket usage)"""
    agent = active_sessions.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found")

    await agent.add_transcript(input_data.text, input_data.speaker)

    return {"status": "added", "buffer_length": len(agent._transcript_buffer)}


@app.post("/api/consult/{session_id}/check-safety")
async def trigger_safety_check(session_id: str):
    """Manually trigger a safety check"""
    agent = active_sessions.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found")

    transcript_buffer = agent.get_transcript_buffer()
    if not transcript_buffer:
        return {"status": "no_content", "message": "No transcript to check"}

    # Run safety check
    result = await k2_service.check_safety(
        transcript_text=transcript_buffer,
        patient_data=agent.patient_data,
    )

    # Process the result through the agent
    await agent.process_safety_result(result)

    return {
        "status": "checked",
        "safety_level": result.safety_level.value,
        "requires_interruption": result.requires_interruption,
        "warning": result.warning_message,
    }


@app.post("/api/consult/{session_id}/end", response_model=EndConsultResponse)
async def end_consult(session_id: str):
    """End a consultation and generate billing"""
    agent = active_sessions.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found")

    # End the consultation
    soap_note = await agent.end_consult()

    # Calculate duration
    duration = datetime.now() - agent.session.start_time
    duration_minutes = int(duration.total_seconds() / 60)

    # Generate billing
    billing_response = await flowglad_service.process_end_of_visit(
        session_id=session_id,
        patient_id=agent.patient_id,
        provider_id=agent.provider_id,
        soap_note=soap_note,
        duration_minutes=duration_minutes,
        safety_alerts_count=len(agent.session.safety_checks),
    )

    # Save to Snowflake
    await snowflake_service.save_session_record({
        "session_id": session_id,
        "patient_id": agent.patient_id,
        "provider_id": agent.provider_id,
        "start_time": agent.session.start_time,
        "end_time": datetime.now(),
        "transcript": agent.get_full_transcript(),
        "soap_note": json.dumps(soap_note.model_dump()),
        "billing_info": json.dumps(billing_response.model_dump()),
    })

    # Remove from active sessions
    del active_sessions[session_id]

    return EndConsultResponse(
        session_id=session_id,
        soap_note=soap_note.model_dump(),
        billing={
            "invoice_id": billing_response.invoice_id,
            "amount": billing_response.total_amount,
            "status": billing_response.status,
        },
        duration_minutes=duration_minutes,
    )


@app.get("/api/consult/{session_id}/status")
async def get_session_status(session_id: str):
    """Get current session status"""
    agent = active_sessions.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found")

    return agent.get_session_info()


@app.get("/api/patients/{patient_id}")
async def get_patient(patient_id: str):
    """Get patient data"""
    patient = await snowflake_service.get_patient_data(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return patient.model_dump()


# --- WebSocket Endpoints ---

@app.websocket("/ws/consult/{session_id}")
async def websocket_consult(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time consultation

    Handles:
    - Audio streaming (binary)
    - Transcript updates (JSON)
    - Safety alerts (JSON)
    - Voice interruptions (binary audio)
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for session: {session_id}")

    agent = active_sessions.get(session_id)
    if not agent:
        await websocket.close(code=4004, reason="Session not found")
        return

    # Audio processor for buffering
    audio_processor = AudioStreamProcessor()

    # Set up agent callbacks
    async def on_state_change(old_state: AgentState, new_state: AgentState):
        await websocket.send_json({
            "type": "state_change",
            "old_state": old_state.value,
            "new_state": new_state.value,
            "timestamp": datetime.now().isoformat(),
        })

    async def on_safety_alert(result: SafetyCheckResult):
        await websocket.send_json({
            "type": "safety_alert",
            "safety_level": result.safety_level.value,
            "risk_score": result.risk_score,
            "warning": result.warning_message,
            "recommendation": result.recommendation,
            "requires_interruption": result.requires_interruption,
            "timestamp": datetime.now().isoformat(),
        })

    async def on_interruption(warning_text: str):
        await websocket.send_json({
            "type": "interruption_start",
            "text": warning_text,
            "timestamp": datetime.now().isoformat(),
        })

        # Generate and stream interruption audio
        async for audio_chunk in elevenlabs_service.speak_interruption(warning_text):
            await websocket.send_bytes(audio_chunk)

        await websocket.send_json({
            "type": "interruption_end",
            "timestamp": datetime.now().isoformat(),
        })

    agent.set_callbacks(
        on_state_change=on_state_change,
        on_safety_alert=on_safety_alert,
        on_interruption=on_interruption,
    )

    # Background task for periodic safety checks
    async def safety_check_loop():
        while agent.state not in [AgentState.COMPLETED, AgentState.ERROR]:
            await asyncio.sleep(get_settings().safety_check_interval)

            if agent.state == AgentState.LISTENING and agent._transcript_buffer:
                buffer_text = agent.get_transcript_buffer()
                if buffer_text.strip():
                    result = await k2_service.check_safety(
                        transcript_text=buffer_text,
                        patient_data=agent.patient_data,
                    )
                    await agent.process_safety_result(result)
                    agent.clear_transcript_buffer()

    safety_task = asyncio.create_task(safety_check_loop())

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            # Handle binary audio data
            if "bytes" in message:
                audio_data = message["bytes"]
                complete_utterance = audio_processor.add_chunk(audio_data)

                if complete_utterance:
                    # Transcribe the audio
                    transcript = await elevenlabs_service.transcribe_audio(complete_utterance)
                    if transcript:
                        await agent.add_transcript(transcript)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": transcript,
                            "timestamp": datetime.now().isoformat(),
                        })

            # Handle JSON messages
            elif "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "transcript":
                    # Direct transcript input (for demo/testing)
                    await agent.add_transcript(
                        data.get("text", ""),
                        data.get("speaker", "doctor")
                    )
                    await websocket.send_json({
                        "type": "transcript_added",
                        "text": data.get("text"),
                        "timestamp": datetime.now().isoformat(),
                    })

                elif msg_type == "pause":
                    await agent.pause_consult()

                elif msg_type == "resume":
                    await agent.resume_consult()

                elif msg_type == "end":
                    soap_note = await agent.end_consult()
                    await websocket.send_json({
                        "type": "consult_ended",
                        "soap_note": soap_note.model_dump(),
                        "timestamp": datetime.now().isoformat(),
                    })
                    break

                elif msg_type == "check_safety":
                    # Manual safety check trigger
                    buffer_text = agent.get_transcript_buffer()
                    if buffer_text:
                        result = await k2_service.check_safety(
                            transcript_text=buffer_text,
                            patient_data=agent.patient_data,
                        )
                        await agent.process_safety_result(result)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        safety_task.cancel()
        try:
            await safety_task
        except asyncio.CancelledError:
            pass


@app.websocket("/ws/audio-only")
async def websocket_audio_only(websocket: WebSocket):
    """
    Simplified WebSocket for audio-only streaming

    For testing audio I/O without full session management
    """
    await websocket.accept()
    logger.info("Audio-only WebSocket connected")

    audio_processor = AudioStreamProcessor()

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message:
                audio_data = message["bytes"]
                complete_utterance = audio_processor.add_chunk(audio_data)

                if complete_utterance:
                    transcript = await elevenlabs_service.transcribe_audio(complete_utterance)
                    if transcript:
                        await websocket.send_json({
                            "type": "transcript",
                            "text": transcript,
                        })

    except WebSocketDisconnect:
        logger.info("Audio-only WebSocket disconnected")


# --- Demo/Test Endpoints ---

@app.post("/api/demo/simulate-danger")
async def simulate_danger(session_id: str, drug_name: str = "sumatriptan"):
    """
    Simulate a dangerous prescription for demo purposes

    Injects a transcript segment mentioning a dangerous drug
    """
    agent = active_sessions.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found")

    # Inject dangerous prescription text
    demo_text = f"I'm going to prescribe {drug_name} 50mg for your migraine."
    await agent.add_transcript(demo_text)

    # Trigger safety check
    result = await k2_service.check_safety(
        transcript_text=demo_text,
        patient_data=agent.patient_data,
    )

    await agent.process_safety_result(result)

    return {
        "demo_text": demo_text,
        "safety_result": result.model_dump(),
    }


@app.get("/api/demo/speak")
async def demo_speak(text: str = "Doctor, this is a test of the voice interruption system."):
    """Test text-to-speech"""
    chunks = []
    async for chunk in elevenlabs_service.speak_interruption(text):
        chunks.append(len(chunk))

    return {
        "text": text,
        "audio_chunks": len(chunks),
        "total_bytes": sum(chunks),
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
