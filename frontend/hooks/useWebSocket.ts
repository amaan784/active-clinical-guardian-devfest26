"use client"

import { useState, useEffect, useRef, useCallback } from 'react'
import { api, type WebSocketMessage } from '@/lib/api'

interface UseWebSocketOptions {
  sessionId: string
  onMessage?: (message: WebSocketMessage) => void
  onAudio?: (audioData: ArrayBuffer) => void
  onOpen?: () => void
  onClose?: () => void
  onError?: (error: Event) => void
}

export function useWebSocket({
  sessionId,
  onMessage,
  onAudio,
  onOpen,
  onClose,
  onError,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    const ws = api.createWebSocket(sessionId)

    ws.onopen = () => {
      setIsConnected(true)
      onOpen?.()
    }

    ws.onclose = () => {
      setIsConnected(false)
      onClose?.()
    }

    ws.onerror = (event) => {
      console.error('WebSocket error:', event)
      onError?.(event)
    }

    ws.onmessage = (event) => {
      if (event.data instanceof Blob) {
        // Binary audio data
        event.data.arrayBuffer().then((buffer) => {
          onAudio?.(buffer)
        })
      } else {
        // JSON message
        try {
          const message = JSON.parse(event.data) as WebSocketMessage
          setLastMessage(message)
          onMessage?.(message)
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }
    }

    wsRef.current = ws
  }, [sessionId, onMessage, onAudio, onOpen, onClose, onError])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const sendMessage = useCallback((message: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    }
  }, [])

  const sendAudio = useCallback((audioData: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(audioData)
    }
  }, [])

  const sendTranscript = useCallback((text: string, speaker: string = 'doctor') => {
    sendMessage({ type: 'transcript', text, speaker })
  }, [sendMessage])

  const endSession = useCallback(() => {
    sendMessage({ type: 'end' })
  }, [sendMessage])

  const pauseSession = useCallback(() => {
    sendMessage({ type: 'pause' })
  }, [sendMessage])

  const resumeSession = useCallback(() => {
    sendMessage({ type: 'resume' })
  }, [sendMessage])

  const triggerSafetyCheck = useCallback(() => {
    sendMessage({ type: 'check_safety' })
  }, [sendMessage])

  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return {
    isConnected,
    lastMessage,
    connect,
    disconnect,
    sendMessage,
    sendAudio,
    sendTranscript,
    endSession,
    pauseSession,
    resumeSession,
    triggerSafetyCheck,
  }
}
