"""
Synapse 2.0 Pydantic Schemas
All data models for the clinical safety system
"""

from pydantic import BaseModel, Field
from typing import Optional, Union
from datetime import datetime, date
from enum import Enum


class SafetyLevel(str, Enum):
    """Safety classification levels"""
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"


class Medication(BaseModel):
    """Patient medication record"""
    name: str
    dosage: str
    frequency: str
    start_date: Optional[datetime] = None
    prescriber: Optional[str] = None
    drug_class: Optional[str] = None  # e.g., "SSRI", "Triptan", "NSAID"


class PatientData(BaseModel):
    """Complete patient record from Snowflake"""
    patient_id: str
    name: str
    date_of_birth: Union[date, datetime]
    allergies: list[str] = Field(default_factory=list)
    current_medications: list[Medication] = Field(default_factory=list)
    medical_history: list[str] = Field(default_factory=list)
    recent_diagnoses: list[str] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    """A segment of transcribed speech"""
    text: str
    speaker: str = "doctor"  # "doctor" or "patient"
    timestamp: datetime = Field(default_factory=datetime.now)
    confidence: float = 1.0


class SafetyCheckResult(BaseModel):
    """Result from K2 Think safety validation"""
    safety_level: SafetyLevel
    risk_score: float = Field(ge=0.0, le=1.0)
    detected_medications: list[str] = Field(default_factory=list)
    interactions: list[dict] = Field(default_factory=list)
    warning_message: Optional[str] = None
    recommendation: Optional[str] = None
    requires_interruption: bool = False


class SOAPNote(BaseModel):
    """Structured SOAP Note for documentation"""
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    icd10_codes: list[str] = Field(default_factory=list)
    cpt_codes: list[str] = Field(default_factory=list)


class ConsultSession(BaseModel):
    """A complete consultation session"""
    session_id: str
    patient_id: str
    provider_id: str
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    safety_checks: list[SafetyCheckResult] = Field(default_factory=list)
    soap_note: Optional[SOAPNote] = None
    status: str = "active"  # "active", "paused", "completed"


class BillingRequest(BaseModel):
    """Request to Flowglad for billing"""
    session_id: str
    patient_id: str
    provider_id: str
    cpt_codes: list[str]
    icd10_codes: list[str]
    service_date: datetime = Field(default_factory=datetime.now)
    duration_minutes: int


class BillingResponse(BaseModel):
    """Response from Flowglad billing"""
    invoice_id: str
    total_amount: float
    status: str
    created_at: datetime


class WebSocketMessage(BaseModel):
    """WebSocket message format"""
    type: str  # "audio", "transcript", "safety_alert", "command", "status"
    payload: dict
    timestamp: datetime = Field(default_factory=datetime.now)
