"use client"

import { useState, useRef, useCallback } from 'react'

export function useAudioPlayer() {
  const [isPlaying, setIsPlaying] = useState(false)
  const audioContextRef = useRef<AudioContext | null>(null)
  const audioQueueRef = useRef<ArrayBuffer[]>([])
  const isPlayingRef = useRef(false)

  const getAudioContext = useCallback(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext()
    }
    return audioContextRef.current
  }, [])

  const playAudioChunk = useCallback(async (audioData: ArrayBuffer) => {
    audioQueueRef.current.push(audioData)

    if (isPlayingRef.current) {
      return
    }

    isPlayingRef.current = true
    setIsPlaying(true)

    const audioContext = getAudioContext()

    while (audioQueueRef.current.length > 0) {
      const chunk = audioQueueRef.current.shift()
      if (!chunk) continue

      try {
        const audioBuffer = await audioContext.decodeAudioData(chunk.slice(0))
        const source = audioContext.createBufferSource()
        source.buffer = audioBuffer
        source.connect(audioContext.destination)

        await new Promise<void>((resolve) => {
          source.onended = () => resolve()
          source.start()
        })
      } catch (err) {
        console.error('Failed to play audio chunk:', err)
      }
    }

    isPlayingRef.current = false
    setIsPlaying(false)
  }, [getAudioContext])

  const stopPlayback = useCallback(() => {
    audioQueueRef.current = []
    isPlayingRef.current = false
    setIsPlaying(false)
  }, [])

  return {
    isPlaying,
    playAudioChunk,
    stopPlayback,
  }
}
