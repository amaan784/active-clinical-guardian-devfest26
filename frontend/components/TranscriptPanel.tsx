"use client"

import { useRef, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { FileText } from "lucide-react"
import { formatTime } from "@/lib/utils"

export interface TranscriptEntry {
  id: string
  text: string
  speaker: "doctor" | "patient" | "system"
  timestamp: Date
}

interface TranscriptPanelProps {
  entries: TranscriptEntry[]
  isRecording?: boolean
}

export function TranscriptPanel({ entries, isRecording }: TranscriptPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new entries arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [entries])

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            <CardTitle className="text-lg">Live Transcript</CardTitle>
          </div>
          {isRecording && (
            <div className="flex items-center gap-2">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
              </span>
              <span className="text-sm text-muted-foreground">Recording</span>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[400px] pr-4">
          {entries.length === 0 ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <p>Transcript will appear here...</p>
            </div>
          ) : (
            <div className="space-y-3">
              {entries.map((entry) => (
                <div
                  key={entry.id}
                  className={`flex flex-col gap-1 animate-slide-in ${
                    entry.speaker === "system"
                      ? "bg-muted/50 rounded-md p-2"
                      : ""
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={
                        entry.speaker === "doctor"
                          ? "default"
                          : entry.speaker === "patient"
                          ? "secondary"
                          : "outline"
                      }
                    >
                      {entry.speaker}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatTime(entry.timestamp)}
                    </span>
                  </div>
                  <p className={`text-sm pl-1 ${entry.id.startsWith("partial-") ? "italic text-muted-foreground" : ""}`}>{entry.text}</p>
                </div>
              ))}
              <div ref={scrollRef} />
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
