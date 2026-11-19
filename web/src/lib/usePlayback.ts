/**
 * Plays a timeline. One <audio> element follows the scene under the playhead:
 * voiced scenes play their clip (and the clip's clock drives the playhead, so captions
 * stay on the words), and scenes with no voice yet advance on a plain clock.
 */
import { useCallback, useEffect, useRef, useState } from "react"

import { LEAD, sceneAt, type Timeline } from "./timing"

/** 80 ms of silence. Played once inside the tap that starts playback, because iOS Safari
 * only lets an audio element play later if it first played during a user gesture. */
const SILENCE = "data:audio/mpeg;base64,SUQzBAAAAAAAIlRTU0UAAAAOAAADTGF2ZjYyLjMuMTAwAAAAAAAAAAAAAAD/83DAAAAAAAAAAAAASW5mbwAAAA8AAAAGAAADKQBaWlpaWlpaWlpaWlpaWlpae3t7e3t7e3t7e3t7e3t7e3ucnJycnJycnJycnJycnJycvb29vb29vb29vb29vb29vb3e3t7e3t7e3t7e3t7e3t7e3v////////////////////8AAAAATGF2YzYyLjExAAAAAAAAAAAAAAAAJARRAAAAAAAAAymyj04oAAAAAAAAAAAAAAAAAP/zQMQAAAADSAAAAABMQU1FMy4xMDBVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NCxFsAAANIAAAAAFVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NAxKQAAANIAAAAAFVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/80LEowAAA0gAAAAAVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/80DEpAAAA0gAAAAAVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/zQsSjAAADSAAAAABVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQ=="

/** The speeds on offer. The voice keeps its pitch at every one of them. */
export const RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] as const

const RATE_KEY = "video-learn.rate"

/** The speed this browser last chose: someone who watches at 2x wants the next lesson at 2x too. */
function storedRate(): number {
  try {
    const r = Number(localStorage.getItem(RATE_KEY))
    return (RATES as readonly number[]).includes(r) ? r : 1
  } catch {
    return 1 // storage is blocked (a private window, say)
  }
}

export interface Playback {
  time: number
  playing: boolean
  play: () => void
  pause: () => void
  toggle: () => void
  seek: (t: number) => void
  /** jump by this many seconds (negative goes back), without stopping playback */
  skip: (by: number) => void
  /** playback speed, 1 = normal */
  rate: number
  setRate: (rate: number) => void
  /** set when the browser refused to play a clip */
  audioError: string | null
}

export function usePlayback(timeline: Timeline): Playback {
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [audioError, setAudioError] = useState<string | null>(null)
  const [rate, setRateState] = useState(storedRate)

  const timeRef = useRef(0)
  const rateRef = useRef(rate)
  const playingRef = useRef(false)
  const timelineRef = useRef(timeline)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const lastFrame = useRef<number | null>(null)
  const rafId = useRef<number | null>(null)
  const unlocked = useRef(false)
  const pending = useRef(false)

  timelineRef.current = timeline

  useEffect(() => {
    const audio = new Audio()
    audio.preload = "auto"
    // a new src resets playbackRate to the default, so the default follows the chosen speed too
    audio.defaultPlaybackRate = rateRef.current
    audio.playbackRate = rateRef.current
    audioRef.current = audio
    return () => {
      // leaving the editor stops everything, including a frame already scheduled
      playingRef.current = false
      if (rafId.current !== null) cancelAnimationFrame(rafId.current)
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
    // Lesson seconds since the last frame. A voiced stretch follows the clip's own clock
    // (which the browser runs at playbackRate); everything else advances by this.
    const dt = (lastFrame.current === null ? 0 : Math.min(0.1, (now - lastFrame.current) / 1000)) * rateRef.current
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
      if (audio.playbackRate !== rateRef.current) audio.playbackRate = rateRef.current
      if (!audio.src.endsWith(url)) {
        audio.src = url
        audio.playbackRate = rateRef.current
        audio.currentTime = want
      } else if (Math.abs(audio.currentTime - want) > 0.3 && !audio.seeking) {
        audio.currentTime = want
      }
      if (audio.ended) {
        // the clip finished a hair before its measured duration: move on to the tail
        t = Math.max(t + dt, scene.start + audioEnd)
      } else if (audio.paused) {
        if (!pending.current) {
          pending.current = true
          audio.play().then(
            () => (pending.current = false),
            (e: unknown) => {
              pending.current = false
              setAudioError(e instanceof Error && e.name === "NotAllowedError" ? "Tap play again to hear the voice." : "The audio didn't play.")
              playingRef.current = false
              setPlaying(false)
            },
          )
        }
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
    if (playingRef.current) rafId.current = requestAnimationFrame(frame)
  }, [])

  const play = useCallback(() => {
    const tl = timelineRef.current
    if (!tl.total) return
    if (timeRef.current >= tl.total - 0.05) timeRef.current = 0
    setAudioError(null)
    const audio = audioRef.current
    if (audio && !unlocked.current) {
      audio.src = SILENCE
      audio.play().then(
        () => (unlocked.current = true),
        () => {},
      )
    }
    playingRef.current = true
    setPlaying(true)
    lastFrame.current = null
    rafId.current = requestAnimationFrame(frame)
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

  const skip = useCallback((by: number) => seek(timeRef.current + by), [seek])

  const setRate = useCallback((next: number) => {
    const r = Math.max(RATES[0], Math.min(RATES[RATES.length - 1], next))
    rateRef.current = r
    setRateState(r)
    const audio = audioRef.current
    if (audio) {
      audio.defaultPlaybackRate = r
      audio.playbackRate = r
    }
    try {
      localStorage.setItem(RATE_KEY, String(r))
    } catch {
      // not remembered, but it still applies to this lesson
    }
  }, [])

  const toggle = useCallback(() => (playingRef.current ? pause() : play()), [pause, play])

  return { time, playing, play, pause, toggle, seek, skip, rate, setRate, audioError }
}
