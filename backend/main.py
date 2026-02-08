"""
The Active Clinical Guardian
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
from services.elevenlabs_service import ElevenLabsService
from services.dedalus_service import DedalusService
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
dedalus_service: Optional[DedalusService] = None
flowglad_service: Optional[FlowgladService] = None

# Active sessions tracking
active_sessions: dict[str, ClinicalAgent] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global snowflake_service, k2_service, elevenlabs_service, dedalus_service, flowglad_service

    # Startup
    logger.info("Initializing services...")

    snowflake_service = SnowflakeService()
    await snowflake_service.connect()

    k2_service = K2SafetyService()
    await k2_service.initialize()

    elevenlabs_service = ElevenLabsService()
    await elevenlabs_service.initialize()

    dedalus_service = DedalusService()
    await dedalus_service.initialize()

    flowglad_service = FlowgladService()
    await flowglad_service.initialize()

    logger.info("All services initialized successfully")

    yield

    # Shutdown
    logger.info("Shutting down...")

    if snowflake_service:
        await snowflake_service.disconnect()
    if k2_service:
        await k2_service.close()
    if elevenlabs_service:
        await elevenlabs_service.close()
    if dedalus_service:
        await dedalus_service.close()
    if flowglad_service:
        await flowglad_service.close()

    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="The Active Clinical Guardian",
    description="Real-time clinical safety monitoring",
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


# --- Orchestrated Safety Pipeline ---
# Dedalus sits at the center of every safety check:
#   1. Dedalus: analyze_clinical_intent → extract medications, procedures, diagnoses
#   2. Snowflake RAG: search guidelines using targeted query from Dedalus output
#   3. K2 Think: reason over patient data + guidelines + Dedalus intent
#   4. ElevenLabs: voice interruption if DANGER/CRITICAL

async def orchestrate_safety_check(
    transcript_text: str,
    agent: ClinicalAgent,
) -> SafetyCheckResult:
    """
    Full orchestrated safety check pipeline with Dedalus as the coordinator.
    """
    patient_data = agent.patient_data

    # ── Step 1: Dedalus extracts clinical intent ──
    # Instead of dumping raw transcript to RAG, Dedalus parses what the doctor
    # is actually doing: prescribing, ordering, diagnosing
    intent = await dedalus_service.analyze_clinical_intent(transcript_text)

    # ── Step 2: Build targeted RAG query from Dedalus output ──
    # Use the extracted medications + patient's current meds to form a precise
    # search query instead of the raw transcript blob
    med_names = [m.get("name", "") for m in intent.get("medications", [])]
    current_med_names = [m.name for m in patient_data.current_medications]
    current_classes = [m.drug_class for m in patient_data.current_medications if m.drug_class]

    if med_names:
        # Targeted query: "sumatriptan sertraline SSRI interaction safety"
        rag_query = " ".join(med_names + current_med_names + current_classes + ["interaction", "safety"])
        logger.info(f"Dedalus extracted medications: {med_names} → RAG query: {rag_query}")
    else:
        # Fallback: use raw transcript if Dedalus didn't find anything
        rag_query = transcript_text
        logger.info("No medications extracted by Dedalus, using raw transcript for RAG")

    # ── Step 3: Snowflake RAG search with targeted query ──
    guidelines = await snowflake_service.search_clinical_guidelines(
        query=rag_query, limit=3,
    )

    # ── Step 4: K2 Think reasons over the full context ──
    result = await k2_service.check_safety(
        transcript_text=transcript_text,
        patient_data=patient_data,
        clinical_guidelines=guidelines,
    )

    return result


# --- REST Endpoints ---

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "The Active Clinical Guardian",
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

    # Run orchestrated safety pipeline (Dedalus → Snowflake RAG → K2)
    result = await orchestrate_safety_check(transcript_buffer, agent)

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

    # Calculate duration
    duration = datetime.now() - agent.session.start_time
    duration_minutes = int(duration.total_seconds() / 60)

    # Generate SOAP note via Dedalus (or fallback)
    patient_context = agent.patient_data.model_dump(mode="json") if agent.patient_data else {}
    full_transcript = agent.get_full_transcript()

    soap_dict = await dedalus_service.generate_soap_note(
        transcript=full_transcript,
        patient_context=patient_context,
    )

    # End the consultation with the generated SOAP note
    # Note: agent.end_consult expects the raw dict which DedalusService now returns
    soap_note = await agent.end_consult(soap_data=soap_dict)

    # Generate billing (graceful fallback if Flowglad is unreachable)
    try:
        billing_response = await flowglad_service.process_end_of_visit(
            session_id=session_id,
            patient_id=agent.patient_id,
            provider_id=agent.provider_id,
            soap_note=soap_note,
            duration_minutes=duration_minutes,
            safety_alerts_count=len(agent.session.safety_checks),
        )
        billing_info = {
            "invoice_id": billing_response.invoice_id,
            "amount": billing_response.total_amount,
            "status": billing_response.status,
        }
    except Exception as e:
        logger.error(f"Billing generation failed (non-fatal): {e}")
        billing_info = {
            "invoice_id": f"INV-{session_id[:8].upper()}",
            "amount": 0,
            "status": "billing_unavailable",
        }

    # Save to Snowflake (non-fatal if it fails)
    try:
        await snowflake_service.save_session_record({
            "session_id": session_id,
            "patient_id": agent.patient_id,
            "provider_id": agent.provider_id,
            "start_time": agent.session.start_time,
            "end_time": datetime.now(),
            "transcript": agent.get_full_transcript(),
            "soap_note": json.dumps(soap_note.model_dump()),
            "safety_alerts": json.dumps([sc.model_dump() for sc in agent.session.safety_checks]),
            "billing_info": json.dumps(billing_info),
        })
    except Exception as e:
        logger.error(f"Failed to save session to Snowflake (non-fatal): {e}")

    # Remove from active sessions (may already be removed by WS handler)
    active_sessions.pop(session_id, None)

    return EndConsultResponse(
        session_id=session_id,
        soap_note=soap_note.model_dump(),
        billing=billing_info,
        duration_minutes=duration_minutes,
    )


@app.get("/api/consult/{session_id}/status")
async def get_session_status(session_id: str):
    """Get current session status"""
    agent = active_sessions.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not found")

    return agent.get_session_info()


@app.get("/api/patients")
async def list_patients():
    """Get all patients from Snowflake"""
    patients = await snowflake_service.list_patients()
    return patients


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
    WebSocket endpoint for real-time consultation.
    
    This endpoint establishes a persistent connection with ElevenLabs Scribe v2
    to handle real-time streaming transcription and safety checks.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for session: {session_id}")

    agent = active_sessions.get(session_id)
    if not agent:
        await websocket.close(code=4004, reason="Session not found")
        return

    # Callback to handle incoming text from ElevenLabs stream
    async def on_transcript_text(text: str, is_final: bool):
        # 1. Send to Frontend immediately
        try:
            await websocket.send_json({
                "type": "transcript",
                "text": text,
                "is_final": is_final,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error(f"Error sending transcript to WS: {e}")

        # 2. Logic for Final/Committed text
        if is_final:
            # Add to agent memory
            await agent.add_transcript(text)
            
            # Run Orchestrated Safety Check (Dedalus -> Snowflake -> K2)
            # We use the committed text chunk for immediate analysis
            result = await orchestrate_safety_check(text, agent)
            
            # Process result (triggers on_safety_alert callback if needed)
            await agent.process_safety_result(result)

    # Set up agent callbacks (to send alerts back to frontend)
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

        # Generate and stream interruption audio via ElevenLabs
        try:
            async for audio_chunk in elevenlabs_service.speak_interruption(warning_text):
                await websocket.send_bytes(audio_chunk)
        except Exception as e:
            logger.error(f"TTS streaming in interruption failed (non-fatal): {e}")

        await websocket.send_json({
            "type": "interruption_end",
            "timestamp": datetime.now().isoformat(),
        })

    # Register the agent callbacks
    agent.set_callbacks(
        on_state_change=on_state_change,
        on_safety_alert=on_safety_alert,
        on_interruption=on_interruption,
    )

    # Start the ElevenLabs Transcription Stream (per-session connection)
    scribe_connection = await elevenlabs_service.start_transcription_stream(on_transcript_text)

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            # Handle binary audio data -> Push to ElevenLabs Stream
            if "bytes" in message:
                audio_bytes = message["bytes"]
                logger.debug(f"Audio chunk received: {len(audio_bytes)} bytes")
                await elevenlabs_service.send_audio_chunk(scribe_connection, audio_bytes)

            # Handle JSON messages (Control signals)
            elif "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "transcript":
                    # Text input manually sent from frontend
                    text = data.get("text", "")
                    speaker = data.get("speaker", "doctor")
                    await agent.add_transcript(text, speaker)

                    # Echo back to frontend so it appears in the transcript panel
                    await websocket.send_json({
                        "type": "transcript",
                        "text": text,
                        "is_final": True,
                        "timestamp": datetime.now().isoformat(),
                    })

                    # Run safety pipeline on manual text (same as committed Scribe text)
                    if speaker == "doctor" and text.strip():
                        result = await orchestrate_safety_check(text, agent)
                        await agent.process_safety_result(result)

                elif msg_type == "pause":
                    await agent.pause_consult()

                elif msg_type == "resume":
                    await agent.resume_consult()

                elif msg_type == "end":
                    # Similar logic to endpoint: Generate Note & Billing
                    ws_patient_context = agent.patient_data.model_dump(mode="json") if agent.patient_data else {}
                    ws_transcript = agent.get_full_transcript()
                    
                    ws_soap_dict = await dedalus_service.generate_soap_note(
                        transcript=ws_transcript,
                        patient_context=ws_patient_context,
                    )
                    soap_note = await agent.end_consult(soap_data=ws_soap_dict)

                    # Billing
                    ws_duration = datetime.now() - agent.session.start_time
                    ws_duration_minutes = int(ws_duration.total_seconds() / 60)
                    try:
                        ws_billing = await flowglad_service.process_end_of_visit(
                            session_id=session_id,
                            patient_id=agent.patient_id,
                            provider_id=agent.provider_id,
                            soap_note=soap_note,
                            duration_minutes=ws_duration_minutes,
                            safety_alerts_count=len(agent.session.safety_checks),
                        )
                        ws_billing_info = {
                            "invoice_id": ws_billing.invoice_id,
                            "amount": ws_billing.total_amount,
                            "status": ws_billing.status,
                        }
                    except Exception:
                        ws_billing_info = {"invoice_id": "ERROR", "amount": 0, "status": "error"}

                    await websocket.send_json({
                        "type": "consult_ended",
                        "soap_note": soap_note.model_dump(),
                        "billing": ws_billing_info,
                        "timestamp": datetime.now().isoformat(),
                    })
                    
                    if session_id in active_sessions:
                        del active_sessions[session_id]
                    break

                elif msg_type == "check_safety":
                    # Manual trigger
                    buffer_text = agent.get_transcript_buffer()
                    if buffer_text:
                        result = await orchestrate_safety_check(buffer_text, agent)
                        await agent.process_safety_result(result)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Cleanup the per-session ElevenLabs stream when WS closes
        await elevenlabs_service.close_transcription_stream(scribe_connection)


@app.websocket("/ws/audio-only")
async def websocket_audio_only(websocket: WebSocket):
    """
    Simplified WebSocket for testing audio streaming.
    Uses the same ElevenLabs streaming pipeline.
    """
    await websocket.accept()
    logger.info("Audio-only WebSocket connected")

    async def on_transcript_text(text: str, is_final: bool):
        await websocket.send_json({
            "type": "transcript",
            "text": text,
            "is_final": is_final
        })

    audio_scribe_conn = await elevenlabs_service.start_transcription_stream(on_transcript_text)

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message:
                await elevenlabs_service.send_audio_chunk(audio_scribe_conn, message["bytes"])

    except WebSocketDisconnect:
        logger.info("Audio-only WebSocket disconnected")
    finally:
        await elevenlabs_service.close_transcription_stream(audio_scribe_conn)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )