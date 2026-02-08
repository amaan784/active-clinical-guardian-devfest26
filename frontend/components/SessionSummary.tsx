"use client"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  FileText,
  DollarSign,
  Clock,
  CheckCircle,
  Download,
  X,
} from "lucide-react"
import type { EndConsultResponse } from "@/lib/api"

interface SessionSummaryProps {
  data: EndConsultResponse
  onClose: () => void
}

export function SessionSummary({ data, onClose }: SessionSummaryProps) {
  const { soap_note, billing, duration_minutes } = data

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Content */}
      <div className="relative z-10 w-full max-w-2xl mx-4 max-h-[90vh] overflow-auto">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <CheckCircle className="h-6 w-6 text-safe" />
                <div>
                  <CardTitle>Consult Complete</CardTitle>
                  <CardDescription>
                    Session ID: {data.session_id.slice(0, 8)}...
                  </CardDescription>
                </div>
              </div>
              <Button variant="ghost" size="icon" onClick={onClose}>
                <X className="h-5 w-5" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Duration */}
            <div className="flex items-center gap-2 text-muted-foreground">
              <Clock className="h-4 w-4" />
              <span>Duration: {duration_minutes} minutes</span>
            </div>

            {/* SOAP Note */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <FileText className="h-5 w-5" />
                <h3 className="font-semibold">SOAP Note</h3>
              </div>
              <div className="space-y-3 bg-muted rounded-lg p-4">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">
                    Subjective
                  </p>
                  <p className="text-sm">{soap_note.subjective || "—"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">
                    Objective
                  </p>
                  <p className="text-sm">{soap_note.objective || "—"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">
                    Assessment
                  </p>
                  <p className="text-sm">{soap_note.assessment || "—"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">
                    Plan
                  </p>
                  <p className="text-sm">{soap_note.plan || "—"}</p>
                </div>
              </div>
            </div>

            {/* Codes */}
            <div className="flex gap-4">
              <div>
                <p className="text-sm font-medium mb-2">CPT Codes</p>
                <div className="flex flex-wrap gap-1">
                  {soap_note.cpt_codes.map((code, i) => (
                    <Badge key={i} variant="default">
                      {code}
                    </Badge>
                  ))}
                </div>
              </div>
              {soap_note.icd10_codes.length > 0 && (
                <div>
                  <p className="text-sm font-medium mb-2">ICD-10 Codes</p>
                  <div className="flex flex-wrap gap-1">
                    {soap_note.icd10_codes.map((code, i) => (
                      <Badge key={i} variant="secondary">
                        {code}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Billing */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <DollarSign className="h-5 w-5" />
                <h3 className="font-semibold">Billing</h3>
              </div>
              <div className="bg-muted rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">Invoice ID</p>
                    <p className="font-mono">{billing.invoice_id}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-muted-foreground">Amount</p>
                    <p className="text-2xl font-bold">
                      ${billing.amount.toFixed(2)}
                    </p>
                  </div>
                </div>
                <div className="mt-2">
                  <Badge
                    variant={billing.status === "created" ? "safe" : "secondary"}
                  >
                    {billing.status}
                  </Badge>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-2">
              <Button
                className="flex-1"
                onClick={() => {
                  const exportData = {
                    session_id: data.session_id,
                    duration_minutes,
                    soap_note,
                    billing,
                    exported_at: new Date().toISOString(),
                  }
                  const blob = new Blob(
                    [JSON.stringify(exportData, null, 2)],
                    { type: "application/json" }
                  )
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement("a")
                  a.href = url
                  a.download = `clinical-note-${data.session_id.slice(0, 8)}.json`
                  a.click()
                  URL.revokeObjectURL(url)
                }}
              >
                <Download className="h-4 w-4 mr-2" />
                Export Note
              </Button>
              <Button variant="secondary" className="flex-1" onClick={onClose}>
                Start New Consult
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
