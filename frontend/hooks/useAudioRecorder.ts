"use client"

import { useState, useRef, useCallback } from 'react'

interface UseAudioRecorderOptions {
  onAudioChunk?: (chunk: ArrayBuffer) => void
  sampleRate?: number
}

export function useAudioRecorder({
  onAudioChunk,
  sampleRate = 16000,
}: UseAudioRecorderOptions = {}) {
  const [isRecording, setIsRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  const startRecording = useCallback(async () => {
    try {
      setError(null)

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })

      streamRef.current = stream

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus',
      })

      mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && onAudioChunk) {
          const buffer = await event.data.arrayBuffer()
          onAudioChunk(buffer)
        }
      }

      mediaRecorder.onerror = (event) => {
        console.error('MediaRecorder error:', event)
        setError('Recording error occurred')
      }

      mediaRecorderRef.current = mediaRecorder
      mediaRecorder.start(250) // Chunk every 250ms
      setIsRecording(true)

    } catch (err) {
      console.error('Failed to start recording:', err)
      setError('Failed to access microphone')
    }
  }, [onAudioChunk, sampleRate])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }

    setIsRecording(false)
  }, [])

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }, [isRecording, startRecording, stopRecording])

  return {
    isRecording,
    error,
    startRecording,
    stopRecording,
    toggleRecording,
  }
}
