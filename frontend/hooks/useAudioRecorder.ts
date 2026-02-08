"use client"

import { useState, useRef, useCallback } from 'react'

interface UseAudioRecorderOptions {
  onAudioChunk?: (chunk: ArrayBuffer) => void
  /** Target sample rate for output PCM (default 16000 Hz) */
  sampleRate?: number
}

/**
 * Downsample Float32 audio from `srcRate` to `dstRate` using linear interpolation.
 * Returns a new Float32Array at the target rate.
 */
function downsampleFloat32(buffer: Float32Array, srcRate: number, dstRate: number): Float32Array {
  if (srcRate === dstRate) return buffer
  const ratio = srcRate / dstRate
  const newLength = Math.round(buffer.length / ratio)
  const result = new Float32Array(newLength)
  for (let i = 0; i < newLength; i++) {
    const srcIndex = i * ratio
    const low = Math.floor(srcIndex)
    const high = Math.min(low + 1, buffer.length - 1)
    const frac = srcIndex - low
    result[i] = buffer[low] * (1 - frac) + buffer[high] * frac
  }
  return result
}

/**
 * Convert Float32 samples (range -1..1) to Int16 PCM ArrayBuffer.
 */
function float32ToInt16(float32: Float32Array): ArrayBuffer {
  const int16 = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
  }
  return int16.buffer
}

/**
 * Audio recorder hook that outputs raw PCM 16-bit mono at the target sample rate.
 *
 * Uses the Web Audio API (AudioContext + ScriptProcessorNode) instead of
 * MediaRecorder so the output is uncompressed PCM — exactly what the
 * ElevenLabs Scribe v2 Realtime SDK expects (AudioFormat.PCM_16000).
 */
export function useAudioRecorder({
  onAudioChunk,
  sampleRate = 16000,
}: UseAudioRecorderOptions = {}) {
  const [isRecording, setIsRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const streamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)

  const startRecording = useCallback(async () => {
    try {
      setError(null)

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })

      streamRef.current = stream

      // Create AudioContext (browser picks native sample rate, e.g. 44100 or 48000)
      const audioCtx = new AudioContext()
      audioCtxRef.current = audioCtx

      const source = audioCtx.createMediaStreamSource(stream)
      sourceRef.current = source

      // ScriptProcessorNode: bufferSize 4096 gives ~85ms chunks at 48kHz
      const processor = audioCtx.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (e) => {
        if (!onAudioChunk) return
        const inputData = e.inputBuffer.getChannelData(0) // Float32, mono
        const downsampled = downsampleFloat32(inputData, audioCtx.sampleRate, sampleRate)
        const pcmBuffer = float32ToInt16(downsampled)
        onAudioChunk(pcmBuffer)
      }

      source.connect(processor)
      processor.connect(audioCtx.destination) // required for onaudioprocess to fire

      setIsRecording(true)
    } catch (err) {
      console.error('Failed to start recording:', err)
      setError('Failed to access microphone')
    }
  }, [onAudioChunk, sampleRate])

  const stopRecording = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }

    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }

    if (audioCtxRef.current) {
      audioCtxRef.current.close()
      audioCtxRef.current = null
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
