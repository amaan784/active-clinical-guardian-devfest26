"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { User, AlertTriangle, Pill } from "lucide-react"
import type { PatientData } from "@/lib/api"

interface PatientCardProps {
  patient: PatientData
}

export function PatientCard({ patient }: PatientCardProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
            <User className="h-5 w-5 text-primary" />
          </div>
          <div>
            <CardTitle className="text-lg">{patient.name}</CardTitle>
            <p className="text-sm text-muted-foreground">
              ID: {patient.patient_id}
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Allergies */}
        {patient.allergies.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="h-4 w-4 text-danger" />
              <span className="text-sm font-medium text-danger">Allergies</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {patient.allergies.map((allergy, i) => (
                <Badge key={i} variant="danger">
                  {allergy}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Current Medications */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Pill className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium">Current Medications</span>
          </div>
          <div className="space-y-2">
            {patient.current_medications.map((med, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-md bg-muted p-2 text-sm"
              >
                <span className="font-medium">{med.name}</span>
                <span className="text-muted-foreground">
                  {med.dosage} - {med.frequency}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Medical History */}
        {patient.medical_history.length > 0 && (
          <div>
            <p className="text-sm font-medium mb-2">Medical History</p>
            <div className="flex flex-wrap gap-1">
              {patient.medical_history.map((condition, i) => (
                <Badge key={i} variant="secondary">
                  {condition}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
