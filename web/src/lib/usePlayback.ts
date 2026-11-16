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
  const unlocked = useRef(false)
  const pending = useRef(false)

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
    if (playingRef.current) requestAnimationFrame(frame)
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
