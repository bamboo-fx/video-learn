/**
 * The timeline: a ruler, one block per scene (as long as its narration), the caption
 * track, and the playhead. Click or drag anywhere to move the playhead.
 */
import { useLayoutEffect, useRef, useState } from "react"

import type { Storyboard } from "@/lib/api"
import { clock, type Timeline as TL } from "@/lib/timing"
import { cn } from "@/lib/utils"

import type { VoiceState } from "./types"

interface Props {
  timeline: TL
  board: Storyboard
  time: number
  activeId: string | null
  voiceState: (id: string) => VoiceState
  onSeek: (t: number) => void
  onSelect: (id: string) => void
  className?: string
}

const PAD = 16

export function Timeline({ timeline, board, time, activeId, voiceState, onSeek, onSelect, className }: Props) {
  const area = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const dragging = useRef(false)

  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const total = Math.max(timeline.total, 1)
  const pps = width > 0 ? (width - PAD * 2) / total : 0
  const x = (t: number) => PAD + t * pps
  const step = pps * 5 > 46 ? 5 : pps * 10 > 46 ? 10 : 30
  const ticks: number[] = []
  for (let t = 0; t <= total; t += step) ticks.push(t)

  const seekAt = (clientX: number) => {
    const el = area.current
    if (!el || pps === 0) return
    const r = el.getBoundingClientRect()
    onSeek(Math.max(0, Math.min(total, (clientX - r.left - PAD) / pps)))
  }

  return (
    <section aria-label="Timeline" className={cn("border-t border-border bg-panel select-none", className)}>
      <div
        ref={area}
        className="relative h-full cursor-pointer touch-none"
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest("[data-scene-block]")) return
          dragging.current = true
          ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
          seekAt(e.clientX)
        }}
        onPointerMove={(e) => dragging.current && seekAt(e.clientX)}
        onPointerUp={() => (dragging.current = false)}
        role="slider"
        tabIndex={0}
        aria-label="Playhead"
        aria-valuemin={0}
        aria-valuemax={Math.round(total)}
        aria-valuenow={Math.round(time)}
        aria-valuetext={`${clock(time)} of ${clock(total)}`}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") onSeek(time - 2)
          if (e.key === "ArrowRight") onSeek(time + 2)
        }}
      >
        {/* ruler */}
        <div className="absolute inset-x-0 top-0 h-7 border-b border-border/70">
          {ticks.map((t) => (
            <div key={t} className="absolute top-0 h-full" style={{ left: x(t) }}>
              <div className="h-2 w-px bg-muted-foreground/40" />
              <span className="absolute top-2.5 -translate-x-1/2 font-mono text-[10px] text-muted-foreground tabular-nums">{clock(t)}</span>
            </div>
          ))}
        </div>

        {/* scenes */}
        <div className="absolute inset-x-0 top-9 h-[74px]">
          {timeline.scenes.map((s, i) => {
            const scene = board.scenes[i]
            const vs = voiceState(s.id)
            const active = s.id === activeId
            const w = Math.max(6, s.duration * pps - 3)
            return (
              <button
                key={s.id}
                type="button"
                data-scene-block
                onClick={() => onSelect(s.id)}
                className={cn(
                  "absolute top-0 flex h-full flex-col overflow-hidden rounded-[10px] border text-left transition-colors",
                  active ? "border-ember bg-ember-soft" : "border-border bg-panel-raised hover:border-muted-foreground/40",
                )}
                style={{ left: x(s.start) + 1.5, width: w }}
                aria-label={`Scene ${i + 1}: ${scene?.heading}`}
                aria-current={active || undefined}
              >
                <span className="flex items-center gap-1.5 truncate px-2 pt-1.5 text-[11px] font-medium">
                  <span className="font-mono text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                  <span className="truncate">{scene?.heading}</span>
                </span>
                <span className="relative mt-auto mb-1.5 h-6 px-2">
                  {vs.kind === "voiced" ? (
                    s.words.map((wd, k) => (
                      <span
                        key={k}
                        className={cn("absolute bottom-0 w-[2px] rounded-full", active ? "bg-ember" : "bg-muted-foreground/55")}
                        style={{
                          left: 8 + (wd.start / s.duration) * (w - 16),
                          height: 5 + ((wd.text.length * 7 + k * 13) % 17),
                        }}
                      />
                    ))
                  ) : (
                    <span className="absolute inset-x-2 bottom-0 flex h-4 items-center rounded-[5px] bg-[repeating-linear-gradient(135deg,transparent_0_5px,oklch(1_0_0/0.06)_5px_10px)] px-1.5 text-[10px] whitespace-nowrap text-muted-foreground">
                      {vs.kind === "voicing" ? "Voicing…" : vs.kind === "failed" ? "Voice failed" : "No voice yet"}
                    </span>
                  )}
                </span>
              </button>
            )
          })}
        </div>

        {/* captions */}
        <div className="absolute inset-x-0 top-[120px] h-6" aria-hidden>
          {timeline.scenes.flatMap((s) =>
            s.captions.map((c, k) => (
              <div
                key={`${s.id}-${k}`}
                className="absolute top-0 h-full truncate rounded-[5px] border border-border/60 bg-track px-1.5 text-[10px] leading-6 text-muted-foreground"
                style={{ left: x(s.start + c.start), width: Math.max(2, (c.end - c.start) * pps - 2) }}
              >
                {c.text}
              </div>
            )),
          )}
        </div>

        {/* playhead */}
        <div className="pointer-events-none absolute top-0 bottom-0 z-10" style={{ left: x(time) }} aria-hidden>
          <div className="absolute top-0 -ml-[6px] h-3 w-3 rotate-45 rounded-[2px] bg-ember" />
          <div className="absolute top-1 bottom-0 -ml-px w-[2px] bg-ember shadow-[0_0_12px_oklch(0.74_0.165_48/0.7)]" />
        </div>
      </div>
    </section>
  )
}
