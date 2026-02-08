"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Shield, AlertTriangle, AlertOctagon, CheckCircle } from "lucide-react"
import { formatTime } from "@/lib/utils"

export interface SafetyAlert {
  id: string
  level: "SAFE" | "CAUTION" | "DANGER" | "CRITICAL"
  message: string
  recommendation?: string
  timestamp: Date
}

interface SafetyPanelProps {
  alerts: SafetyAlert[]
  currentLevel: "SAFE" | "CAUTION" | "DANGER" | "CRITICAL"
}

const levelConfig = {
  SAFE: {
    icon: CheckCircle,
    color: "text-safe",
    bg: "bg-safe/10",
    badge: "safe" as const,
  },
  CAUTION: {
    icon: AlertTriangle,
    color: "text-caution",
    bg: "bg-caution/10",
    badge: "caution" as const,
  },
  DANGER: {
    icon: AlertOctagon,
    color: "text-danger",
    bg: "bg-danger/10",
    badge: "danger" as const,
  },
  CRITICAL: {
    icon: AlertOctagon,
    color: "text-critical",
    bg: "bg-critical/10",
    badge: "critical" as const,
  },
}

export function SafetyPanel({ alerts, currentLevel }: SafetyPanelProps) {
  const config = levelConfig[currentLevel]
  const StatusIcon = config.icon

  return (
    <Card
      className={`h-full transition-colors ${
        currentLevel !== "SAFE" ? config.bg : ""
      }`}
    >
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            <CardTitle className="text-lg">Safety Monitor</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <StatusIcon className={`h-5 w-5 ${config.color}`} />
            <Badge variant={config.badge}>{currentLevel}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[400px] pr-4">
          {alerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
              <CheckCircle className="h-8 w-8 text-safe" />
              <p>No safety alerts</p>
            </div>
          ) : (
            <div className="space-y-3">
              {alerts.map((alert) => {
                const alertConfig = levelConfig[alert.level]
                const AlertIcon = alertConfig.icon

                return (
                  <div
                    key={alert.id}
                    className={`rounded-lg p-3 animate-slide-in ${alertConfig.bg}`}
                  >
                    <div className="flex items-start gap-3">
                      <AlertIcon
                        className={`h-5 w-5 mt-0.5 ${alertConfig.color}`}
                      />
                      <div className="flex-1 space-y-1">
                        <div className="flex items-center justify-between">
                          <Badge variant={alertConfig.badge}>
                            {alert.level}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {formatTime(alert.timestamp)}
                          </span>
                        </div>
                        <p className="text-sm font-medium">{alert.message}</p>
                        {alert.recommendation && (
                          <p className="text-sm text-muted-foreground">
                            {alert.recommendation}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
