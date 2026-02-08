"use client"

import { useState, useRef, useCallback } from 'react'

/**
 * Audio player that accumulates streamed MP3 chunks and plays them as a
 * single buffer once the stream ends (detected by a 500ms gap between chunks).
 *
 * Individual MP3 stream fragments are too small for decodeAudioData, so we
 * must concatenate them first.
 */
export function useAudioPlayer() {
  const [isPlaying, setIsPlaying] = useState(false)
  const audioContextRef = useRef<AudioContext | null>(null)
  const chunksRef = useRef<ArrayBuffer[]>([])
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const getAudioContext = useCallback(() => {
    if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
      audioContextRef.current = new AudioContext()
    }
    return audioContextRef.current
  }, [])

  const playAccumulated = useCallback(async () => {
    const chunks = chunksRef.current
    chunksRef.current = []

    if (chunks.length === 0) return

    // Concatenate all chunks into a single ArrayBuffer
    const totalLength = chunks.reduce((sum, c) => sum + c.byteLength, 0)
    const combined = new Uint8Array(totalLength)
    let offset = 0
    for (const chunk of chunks) {
      combined.set(new Uint8Array(chunk), offset)
      offset += chunk.byteLength
    }

    const audioContext = getAudioContext()
    // Resume context if suspended (browser autoplay policy)
    if (audioContext.state === 'suspended') {
      await audioContext.resume()
    }

    try {
      setIsPlaying(true)
      const audioBuffer = await audioContext.decodeAudioData(combined.buffer)
      const source = audioContext.createBufferSource()
      source.buffer = audioBuffer
      source.connect(audioContext.destination)

      await new Promise<void>((resolve) => {
        source.onended = () => resolve()
        source.start()
      })
    } catch (err) {
      console.error('Failed to play audio:', err)
    } finally {
      setIsPlaying(false)
    }
  }, [getAudioContext])

  const playAudioChunk = useCallback((audioData: ArrayBuffer) => {
    chunksRef.current.push(audioData)

    // Reset the flush timer — play once chunks stop arriving for 500ms
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current)
    }
    flushTimerRef.current = setTimeout(() => {
      flushTimerRef.current = null
      playAccumulated()
    }, 500)
  }, [playAccumulated])

  const stopPlayback = useCallback(() => {
    chunksRef.current = []
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current)
      flushTimerRef.current = null
    }
    setIsPlaying(false)
  }, [])

  return {
    isPlaying,
    playAudioChunk,
    stopPlayback,
  }
}
