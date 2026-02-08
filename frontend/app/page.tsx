"use client"

import { useState, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { PatientCard } from "@/components/PatientCard"
import { TranscriptPanel, TranscriptEntry } from "@/components/TranscriptPanel"
import { SafetyPanel, SafetyAlert } from "@/components/SafetyPanel"
import { ConsultControls } from "@/components/ConsultControls"
import { InterruptionOverlay } from "@/components/InterruptionOverlay"
import { SessionSummary } from "@/components/SessionSummary"
import { useWebSocket } from "@/hooks/useWebSocket"
import { useAudioRecorder } from "@/hooks/useAudioRecorder"
import { useAudioPlayer } from "@/hooks/useAudioPlayer"
import {
  api,
  type PatientData,
  type EndConsultResponse,
  type WebSocketMessage,
} from "@/lib/api"
import { Activity, Brain, Stethoscope, Users } from "lucide-react"

// Demo patients (must match Snowflake/backend demo data)
const DEMO_PATIENTS = [
  { id: "P001", name: "Kevin Patel" },
  { id: "P002", name: "Sarah Johnson" },
]

// Clinical intent from Dedalus analysis
interface ClinicalIntent {
  medications: Array<{ name: string; dosage?: string; action?: string }>
  procedures: Array<{ name: string; action?: string }>
  diagnoses: Array<{ name: string; icd10?: string }>
}

export default function Home() {
  // Session state
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionState, setSessionState] = useState<string>("IDLE")
  const [isPaused, setIsPaused] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  // Patient state
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(null)
  const [patientData, setPatientData] = useState<PatientData | null>(null)

  // Transcript & Safety
  const [transcriptEntries, setTranscriptEntries] = useState<TranscriptEntry[]>([])
  const [safetyAlerts, setSafetyAlerts] = useState<SafetyAlert[]>([])
  const [currentSafetyLevel, setCurrentSafetyLevel] = useState<SafetyAlert["level"]>("SAFE")

  // Interruption state
  const [isInterrupting, setIsInterrupting] = useState(false)
  const [interruptionMessage, setInterruptionMessage] = useState("")

  // Clinical intent (from Dedalus analysis)
  const [clinicalIntent, setClinicalIntent] = useState<ClinicalIntent | null>(null)

  // Session summary
  const [sessionSummary, setSessionSummary] = useState<EndConsultResponse | null>(null)

  // Audio hooks
  const { playAudioChunk } = useAudioPlayer()

  // WebSocket message handler
  const handleWebSocketMessage = useCallback((message: WebSocketMessage) => {
    switch (message.type) {
      case "state_change":
        setSessionState(message.new_state)
        if (message.new_state === "PAUSED") setIsPaused(true)
        if (message.new_state === "LISTENING") setIsPaused(false)
        if (message.new_state === "INTERRUPTING") setIsInterrupting(true)
        break

      case "transcript":
      case "transcript_added":
        setTranscriptEntries((prev) => [
          ...prev,
          {
            id: `t-${Date.now()}`,
            text: message.text,
            speaker: "doctor",
            timestamp: new Date(message.timestamp),
          },
        ])
        break

      case "safety_alert": {
        const alert: SafetyAlert = {
          id: `sa-${Date.now()}`,
          level: message.safety_level,
          message: message.warning || "Safety check completed",
          recommendation: message.recommendation || undefined,
          timestamp: new Date(message.timestamp),
        }
        setSafetyAlerts((prev) => [alert, ...prev])
        setCurrentSafetyLevel(message.safety_level)
        break
      }

      case "clinical_intent":
        // Dedalus has detected clinical actions from the transcript
        setClinicalIntent(message.intent)
        // Show extracted medications as a system note in transcript
        if (message.intent.medications?.length > 0) {
          const medNames = message.intent.medications.map(
            (m) => `${m.name}${m.dosage ? ` ${m.dosage}` : ""}`
          ).join(", ")
          setTranscriptEntries((prev) => [
            ...prev,
            {
              id: `intent-${Date.now()}`,
              text: `[Detected] Medications: ${medNames}`,
              speaker: "system",
              timestamp: new Date(message.timestamp),
            },
          ])
        }
        break

      case "consult_ended":
        // WebSocket-initiated end (via ws "end" command)
        // Build an EndConsultResponse-compatible object for SessionSummary
        setSessionSummary({
          session_id: sessionId || "",
          soap_note: message.soap_note,
          billing: { invoice_id: "pending", amount: 0, status: "pending" },
          duration_minutes: Math.floor(elapsedSeconds / 60),
        })
        setSessionState("COMPLETED")
        break

      case "interruption_start":
        setIsInterrupting(true)
        setInterruptionMessage(message.text || "Clinical alert detected!")
        // Add to transcript as system message
        setTranscriptEntries((prev) => [
          ...prev,
          {
            id: `sys-${Date.now()}`,
            text: `[ALERT] ${message.text}`,
            speaker: "system",
            timestamp: new Date(message.timestamp),
          },
        ])
        break

      case "interruption_end":
        setIsInterrupting(false)
        break
    }
  }, [sessionId, elapsedSeconds])

  // Handle audio data from WebSocket
  const handleAudioData = useCallback((audioData: ArrayBuffer) => {
    playAudioChunk(audioData)
  }, [playAudioChunk])

  // WebSocket hook
  const ws = useWebSocket({
    sessionId: sessionId || "",
    onMessage: handleWebSocketMessage,
    onAudio: handleAudioData,
    onOpen: () => console.log("WebSocket connected"),
    onClose: () => console.log("WebSocket disconnected"),
  })

  // Audio recorder
  const { isRecording, toggleRecording, stopRecording } = useAudioRecorder({
    onAudioChunk: (chunk) => {
      if (ws.isConnected) {
        ws.sendAudio(chunk)
      }
    },
  })

  // Timer effect
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null

    if (sessionId && sessionState === "LISTENING" && !isPaused) {
      interval = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1)
      }, 1000)
    }

    return () => {
      if (interval) clearInterval(interval)
    }
  }, [sessionId, sessionState, isPaused])

  // Select patient
  const handleSelectPatient = async (patientId: string) => {
    try {
      const data = await api.getPatient(patientId)
      setPatientData(data)
      setSelectedPatientId(patientId)
    } catch (error) {
      console.error("Failed to load patient:", error)
    }
  }

  // Start consult
  const handleStartConsult = async () => {
    if (!selectedPatientId) return

    try {
      const response = await api.startConsult(selectedPatientId, "DR001")
      setSessionId(response.session_id)
      setSessionState("LISTENING")
      setElapsedSeconds(0)
      setTranscriptEntries([])
      setSafetyAlerts([])
      setCurrentSafetyLevel("SAFE")
      setClinicalIntent(null)

      // Connect WebSocket after session is created
      setTimeout(() => {
        ws.connect()
      }, 100)
    } catch (error) {
      console.error("Failed to start consult:", error)
    }
  }

  // End consult
  const handleEndConsult = async () => {
    if (!sessionId) return

    try {
      stopRecording()
      const response = await api.endConsult(sessionId)
      setSessionSummary(response)
      ws.disconnect()
      setSessionId(null)
      setSessionState("IDLE")
    } catch (error) {
      console.error("Failed to end consult:", error)
    }
  }

  // Simulate danger for demo
  const handleSimulateDanger = async () => {
    if (!sessionId) return

    try {
      await api.simulateDanger(sessionId, "sumatriptan")
    } catch (error) {
      console.error("Failed to simulate danger:", error)
    }
  }

  // Close session summary
  const handleCloseSummary = () => {
    setSessionSummary(null)
    setPatientData(null)
    setSelectedPatientId(null)
  }

  // Manual transcript input for demo
  const handleManualTranscript = (text: string) => {
    if (ws.isConnected) {
      ws.sendTranscript(text)
    }
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary">
                <Activity className="h-6 w-6 text-primary-foreground" />
              </div>
              <div>
                <h1 className="text-xl font-bold">Synapse 2.0</h1>
                <p className="text-sm text-muted-foreground">
                  The Active Clinical Guardian
                </p>
              </div>
            </div>
            <Badge variant="outline" className="text-sm">
              <Stethoscope className="h-3 w-3 mr-1" />
              Provider: Dr. Smith
            </Badge>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {!sessionId ? (
          // Patient Selection / Start Screen
          <div className="max-w-2xl mx-auto space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Users className="h-5 w-5" />
                  Select Patient
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3">
                  {DEMO_PATIENTS.map((patient) => (
                    <Button
                      key={patient.id}
                      variant={
                        selectedPatientId === patient.id ? "default" : "outline"
                      }
                      className="justify-start h-auto py-3"
                      onClick={() => handleSelectPatient(patient.id)}
                    >
                      <div className="text-left">
                        <p className="font-medium">{patient.name}</p>
                        <p className="text-sm opacity-70">ID: {patient.id}</p>
                      </div>
                    </Button>
                  ))}
                </div>
              </CardContent>
            </Card>

            {patientData && <PatientCard patient={patientData} />}

            <Button
              size="lg"
              className="w-full"
              disabled={!selectedPatientId}
              onClick={handleStartConsult}
            >
              <Stethoscope className="h-5 w-5 mr-2" />
              Start Consultation
            </Button>
          </div>
        ) : (
          // Active Consult Dashboard
          <div className="space-y-4">
            {/* Controls */}
            <ConsultControls
              isRecording={isRecording}
              isPaused={isPaused}
              sessionState={sessionState}
              elapsedSeconds={elapsedSeconds}
              onToggleRecording={toggleRecording}
              onPause={() => ws.pauseSession()}
              onResume={() => ws.resumeSession()}
              onEnd={handleEndConsult}
              onSimulateDanger={handleSimulateDanger}
            />

            {/* Main Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Patient Info & Clinical Intent */}
              <div className="lg:col-span-1 space-y-4">
                {patientData && <PatientCard patient={patientData} />}

                {/* Clinical Intent (Dedalus Analysis) */}
                {clinicalIntent && (clinicalIntent.medications.length > 0 || clinicalIntent.procedures.length > 0 || clinicalIntent.diagnoses.length > 0) && (
                  <Card>
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-2">
                        <Brain className="h-5 w-5 text-primary" />
                        <CardTitle className="text-lg">Clinical Intent</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {clinicalIntent.medications.length > 0 && (
                        <div>
                          <p className="text-sm font-medium text-muted-foreground mb-1">Medications Detected</p>
                          <div className="space-y-1">
                            {clinicalIntent.medications.map((med, i) => (
                              <div key={i} className="flex items-center justify-between rounded-md bg-muted p-2 text-sm">
                                <span className="font-medium">{med.name}</span>
                                <Badge variant="secondary">{med.action || "mentioned"}</Badge>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {clinicalIntent.diagnoses.length > 0 && (
                        <div>
                          <p className="text-sm font-medium text-muted-foreground mb-1">Diagnoses</p>
                          <div className="flex flex-wrap gap-1">
                            {clinicalIntent.diagnoses.map((dx, i) => (
                              <Badge key={i} variant="outline">
                                {dx.name}{dx.icd10 ? ` (${dx.icd10})` : ""}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}
              </div>

              {/* Transcript */}
              <div className="lg:col-span-1">
                <TranscriptPanel
                  entries={transcriptEntries}
                  isRecording={isRecording}
                />
              </div>

              {/* Safety Monitor */}
              <div className="lg:col-span-1">
                <SafetyPanel
                  alerts={safetyAlerts}
                  currentLevel={currentSafetyLevel}
                />
              </div>
            </div>

            {/* Demo: Manual Transcript Input */}
            <Card>
              <CardContent className="p-4">
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Type transcript for demo (e.g., 'I'm prescribing sumatriptan 50mg')"
                    className="flex-1 px-3 py-2 border rounded-md bg-background"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && e.currentTarget.value) {
                        handleManualTranscript(e.currentTarget.value)
                        e.currentTarget.value = ""
                      }
                    }}
                  />
                  <Button
                    variant="secondary"
                    onClick={(e) => {
                      const input = (e.currentTarget.previousElementSibling as HTMLInputElement)
                      if (input?.value) {
                        handleManualTranscript(input.value)
                        input.value = ""
                      }
                    }}
                  >
                    Send
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </main>

      {/* Interruption Overlay */}
      <InterruptionOverlay
        isActive={isInterrupting}
        message={interruptionMessage}
      />

      {/* Session Summary Modal */}
      {sessionSummary && (
        <SessionSummary data={sessionSummary} onClose={handleCloseSummary} />
      )}
    </div>
  )
}
