/**
 * Synapse 2.0 API Client
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface PatientData {
  patient_id: string
  name: string
  date_of_birth: string
  allergies: string[]
  current_medications: Medication[]
  medical_history: string[]
  recent_diagnoses: string[]
}

export interface Medication {
  name: string
  dosage: string
  frequency: string
  drug_class?: string
}

export interface StartConsultResponse {
  session_id: string
  patient_name: string
  status: string
}

export interface EndConsultResponse {
  session_id: string
  soap_note: SOAPNote
  billing: BillingInfo
  duration_minutes: number
}

export interface SOAPNote {
  subjective: string
  objective: string
  assessment: string
  plan: string
  icd10_codes: string[]
  cpt_codes: string[]
}

export interface BillingInfo {
  invoice_id: string
  amount: number
  status: string
}

export interface SafetyAlertMessage {
  type: 'safety_alert'
  safety_level: 'SAFE' | 'CAUTION' | 'DANGER' | 'CRITICAL'
  risk_score: number
  warning: string | null
  recommendation: string | null
  requires_interruption: boolean
  timestamp: string
}

export interface TranscriptMessage {
  type: 'transcript' | 'transcript_added'
  text: string
  timestamp: string
}

export interface StateChangeMessage {
  type: 'state_change'
  old_state: string
  new_state: string
  timestamp: string
}

export interface ClinicalIntentMessage {
  type: 'clinical_intent'
  intent: {
    medications: Array<{ name: string; dosage?: string; action?: string }>
    procedures: Array<{ name: string; action?: string }>
    diagnoses: Array<{ name: string; icd10?: string }>
  }
  timestamp: string
}

export interface ConsultEndedMessage {
  type: 'consult_ended'
  soap_note: SOAPNote
  timestamp: string
}

export interface InterruptionMessage {
  type: 'interruption_start' | 'interruption_end'
  text?: string
  timestamp: string
}

export type WebSocketMessage =
  | SafetyAlertMessage
  | TranscriptMessage
  | StateChangeMessage
  | ClinicalIntentMessage
  | ConsultEndedMessage
  | InterruptionMessage

class SynapseAPI {
  private baseUrl: string

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl
  }

  async getPatient(patientId: string): Promise<PatientData> {
    const response = await fetch(`${this.baseUrl}/api/patients/${patientId}`)
    if (!response.ok) {
      throw new Error(`Failed to get patient: ${response.statusText}`)
    }
    return response.json()
  }

  async startConsult(patientId: string, providerId: string): Promise<StartConsultResponse> {
    const response = await fetch(`${this.baseUrl}/api/consult/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patient_id: patientId, provider_id: providerId }),
    })
    if (!response.ok) {
      throw new Error(`Failed to start consult: ${response.statusText}`)
    }
    return response.json()
  }

  async endConsult(sessionId: string): Promise<EndConsultResponse> {
    const response = await fetch(`${this.baseUrl}/api/consult/${sessionId}/end`, {
      method: 'POST',
    })
    if (!response.ok) {
      throw new Error(`Failed to end consult: ${response.statusText}`)
    }
    return response.json()
  }

  async getSessionStatus(sessionId: string): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.baseUrl}/api/consult/${sessionId}/status`)
    if (!response.ok) {
      throw new Error(`Failed to get session status: ${response.statusText}`)
    }
    return response.json()
  }

  async triggerSafetyCheck(sessionId: string): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.baseUrl}/api/consult/${sessionId}/check-safety`, {
      method: 'POST',
    })
    if (!response.ok) {
      throw new Error(`Failed to trigger safety check: ${response.statusText}`)
    }
    return response.json()
  }

  async simulateDanger(sessionId: string, drugName: string = 'sumatriptan'): Promise<Record<string, unknown>> {
    const response = await fetch(
      `${this.baseUrl}/api/demo/simulate-danger?session_id=${sessionId}&drug_name=${drugName}`,
      { method: 'POST' }
    )
    if (!response.ok) {
      throw new Error(`Failed to simulate danger: ${response.statusText}`)
    }
    return response.json()
  }

  createWebSocket(sessionId: string): WebSocket {
    const wsUrl = this.baseUrl.replace('http', 'ws')
    return new WebSocket(`${wsUrl}/ws/consult/${sessionId}`)
  }
}

export const api = new SynapseAPI()
