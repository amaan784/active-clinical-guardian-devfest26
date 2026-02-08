"use client"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Mic,
  MicOff,
  Play,
  Pause,
  Square,
  Clock,
} from "lucide-react"
import { formatDuration } from "@/lib/utils"

interface ConsultControlsProps {
  isRecording: boolean
  isPaused: boolean
  sessionState: string
  elapsedSeconds: number
  onToggleRecording: () => void
  onPause: () => void
  onResume: () => void
  onEnd: () => void
}

export function ConsultControls({
  isRecording,
  isPaused,
  sessionState,
  elapsedSeconds,
  onToggleRecording,
  onPause,
  onResume,
  onEnd,
}: ConsultControlsProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          {/* Status & Timer */}
          <div className="flex items-center gap-4">
            <Badge
              variant={
                sessionState === "LISTENING"
                  ? "default"
                  : sessionState === "INTERRUPTING"
                  ? "danger"
                  : "secondary"
              }
            >
              {sessionState}
            </Badge>
            <div className="flex items-center gap-2 text-muted-foreground">
              <Clock className="h-4 w-4" />
              <span className="font-mono">{formatDuration(elapsedSeconds)}</span>
            </div>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-2">
            {/* Recording Toggle */}
            <Button
              variant={isRecording ? "danger" : "default"}
              size="icon"
              onClick={onToggleRecording}
            >
              {isRecording ? (
                <MicOff className="h-5 w-5" />
              ) : (
                <Mic className="h-5 w-5" />
              )}
            </Button>

            {/* Pause/Resume */}
            {!isPaused ? (
              <Button variant="secondary" size="icon" onClick={onPause}>
                <Pause className="h-5 w-5" />
              </Button>
            ) : (
              <Button variant="secondary" size="icon" onClick={onResume}>
                <Play className="h-5 w-5" />
              </Button>
            )}

            {/* End Consult */}
            <Button variant="destructive" onClick={onEnd}>
              <Square className="h-4 w-4 mr-2" />
              End Consult
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
