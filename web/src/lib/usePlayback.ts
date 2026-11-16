/**
 * Plays a timeline. One <audio> element follows the scene under the playhead:
 * voiced scenes play their clip (and the clip's clock drives the playhead, so captions
 * stay on the words), and scenes with no voice yet advance on a plain clock.
 */
import { useCallback, useEffect, useRef, useState } from "react"

import { LEAD, sceneAt, type Timeline } from "./timing"

export interface Playback {
  time: number
  playing: boolean
  play: () => void
  pause: () => void
  toggle: () => void
  seek: (t: number) => void
  /** set when the browser refused to play a clip */
  audioError: string | null
}

export function usePlayback(timeline: Timeline): Playback {
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [audioError, setAudioError] = useState<string | null>(null)

  const timeRef = useRef(0)
  const playingRef = useRef(false)
  const timelineRef = useRef(timeline)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const lastFrame = useRef<number | null>(null)

  timelineRef.current = timeline

  useEffect(() => {
    const audio = new Audio()
    audio.preload = "auto"
    audioRef.current = audio
    return () => {
      audio.pause()
      audio.src = ""
    }
  }, [])

  // keep the playhead inside the lesson when scenes are removed or shortened
  useEffect(() => {
    if (timeRef.current > timeline.total) {
      timeRef.current = Math.max(0, timeline.total - 0.01)
      setTime(timeRef.current)
    }
  }, [timeline.total])

  const stopAudio = () => {
    const a = audioRef.current
    if (a && !a.paused) a.pause()
  }

  const frame = useCallback((now: number) => {
    if (!playingRef.current) return
    const tl = timelineRef.current
    const audio = audioRef.current!
    const dt = lastFrame.current === null ? 0 : Math.min(0.1, (now - lastFrame.current) / 1000)
    lastFrame.current = now

    let t = timeRef.current
    const scene = sceneAt(tl, t)
    if (!scene) {
      playingRef.current = false
      setPlaying(false)
      return
    }
    const local = t - scene.start
    const url = scene.voice?.url
    const audioEnd = LEAD + (scene.voice?.duration ?? 0)

    if (url && local >= LEAD && local < audioEnd) {
      const want = local - LEAD
      if (!audio.src.endsWith(url)) {
        audio.src = url
        audio.currentTime = want
      } else if (Math.abs(audio.currentTime - want) > 0.3 && !audio.seeking) {
        audio.currentTime = want
      }
      if (audio.ended) {
        // the clip finished a hair before its measured duration: move on to the tail
        t = Math.max(t + dt, scene.start + audioEnd)
      } else if (audio.paused) {
        audio.play().catch((e: unknown) => {
          setAudioError(e instanceof Error ? e.message : "The browser wouldn't play the audio.")
        })
        t += dt
      } else {
        t = scene.start + LEAD + audio.currentTime
      }
    } else {
      stopAudio()
      if (url && !audio.src.endsWith(url)) {
        audio.src = url // preload the clip during the lead-in
      }
      t += dt
    }

    if (t >= tl.total) {
      t = tl.total
      playingRef.current = false
      setPlaying(false)
      stopAudio()
    }
    timeRef.current = t
    setTime(t)
    if (playingRef.current) requestAnimationFrame(frame)
  }, [])

  const play = useCallback(() => {
    const tl = timelineRef.current
    if (!tl.total) return
    if (timeRef.current >= tl.total - 0.05) timeRef.current = 0
    setAudioError(null)
    playingRef.current = true
    setPlaying(true)
    lastFrame.current = null
    requestAnimationFrame(frame)
  }, [frame])

  const pause = useCallback(() => {
    playingRef.current = false
    setPlaying(false)
    stopAudio()
  }, [])

  const seek = useCallback((t: number) => {
    const clamped = Math.max(0, Math.min(t, timelineRef.current.total))
    timeRef.current = clamped
    setTime(clamped)
    const audio = audioRef.current
    if (audio) audio.pause()
  }, [])

  const toggle = useCallback(() => (playingRef.current ? pause() : play()), [pause, play])

  return { time, playing, play, pause, toggle, seek, audioError }
}
