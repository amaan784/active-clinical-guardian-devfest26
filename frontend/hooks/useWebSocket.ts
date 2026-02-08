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
  /** Max reconnect attempts before giving up (default: 5) */
  maxReconnectAttempts?: number
}

const RECONNECT_BASE_DELAY = 1000 // 1s, then 2s, 4s, 8s, 16s

export function useWebSocket({
  sessionId,
  onMessage,
  onAudio,
  onOpen,
  onClose,
  onError,
  maxReconnectAttempts = 5,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null)
  const intentionalCloseRef = useRef(false)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    // Clean up any existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null // prevent reconnect on manual close
      wsRef.current.close()
    }

    intentionalCloseRef.current = false
    const ws = api.createWebSocket(sessionId)

    ws.onopen = () => {
      setIsConnected(true)
      reconnectAttemptsRef.current = 0 // reset on successful connect
      onOpen?.()
    }

    ws.onclose = () => {
      setIsConnected(false)
      onClose?.()

      // Auto-reconnect if the close was not intentional
      if (
        !intentionalCloseRef.current &&
        reconnectAttemptsRef.current < maxReconnectAttempts
      ) {
        const delay = RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttemptsRef.current)
        console.log(
          `WebSocket closed unexpectedly. Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1}/${maxReconnectAttempts})...`
        )
        reconnectTimerRef.current = setTimeout(() => {
          reconnectAttemptsRef.current += 1
          connect()
        }, delay)
      }
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
  }, [sessionId, onMessage, onAudio, onOpen, onClose, onError, maxReconnectAttempts])

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    reconnectAttemptsRef.current = 0
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
      intentionalCloseRef.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
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
