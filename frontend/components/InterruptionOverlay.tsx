"use client"

import { useEffect, useState } from "react"
import { AlertOctagon, Volume2 } from "lucide-react"

interface InterruptionOverlayProps {
  isActive: boolean
  message: string
}

export function InterruptionOverlay({ isActive, message }: InterruptionOverlayProps) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (isActive) {
      setVisible(true)
    } else {
      // Delay hiding for animation
      const timer = setTimeout(() => setVisible(false), 300)
      return () => clearTimeout(timer)
    }
  }, [isActive])

  if (!visible) return null

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center transition-opacity duration-300 ${
        isActive ? "opacity-100" : "opacity-0"
      }`}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-danger/20 backdrop-blur-sm" />

      {/* Content */}
      <div className="relative z-10 max-w-lg mx-4">
        <div className="bg-danger rounded-lg p-8 shadow-2xl animate-pulse-danger">
          <div className="flex flex-col items-center text-center gap-4">
            <div className="flex items-center gap-3">
              <AlertOctagon className="h-10 w-10 text-white" />
              <Volume2 className="h-8 w-8 text-white animate-pulse" />
            </div>

            <h2 className="text-2xl font-bold text-white">
              CLINICAL ALERT
            </h2>

            <p className="text-lg text-white/90">
              {message}
            </p>

            <div className="flex items-center gap-2 text-white/70 text-sm">
              <Volume2 className="h-4 w-4" />
              <span>Voice alert playing...</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
