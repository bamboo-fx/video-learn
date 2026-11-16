/** The whole lesson as a script. The word being spoken is highlighted as it plays, and
 * clicking a paragraph jumps there. Owners edit a paragraph in place. */
import { useEffect, useRef } from "react"

import { Textarea } from "@/components/ui/textarea"
import type { Storyboard } from "@/lib/api"
import type { Timeline } from "@/lib/timing"
import { cn } from "@/lib/utils"

interface Props {
  board: Storyboard
  timeline: Timeline
  time: number
  playing: boolean
  activeId: string | null
  editable: boolean
  onJump: (sceneId: string) => void
  onNarration: (sceneId: string, text: string) => void
}

export function Script({ board, timeline, time, playing, activeId, editable, onJump, onNarration }: Props) {
  const activeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (playing) activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [activeId, playing])

  return (
    <div className="flex flex-col gap-1 p-3">
      {board.scenes.map((scene, i) => {
        const t = timeline.scenes[i]
        const active = scene.id === activeId
        const local = time - (t?.start ?? 0)
        return (
          <div
            key={scene.id}
            ref={active ? activeRef : undefined}
            className={cn("rounded-xl border p-3 transition-colors", active ? "border-ember/50 bg-ember-soft/40" : "border-transparent hover:bg-panel-raised/60")}
          >
            <button type="button" onClick={() => onJump(scene.id)} className="mb-1.5 flex w-full items-center gap-2 text-left text-[11px]">
              <span className="font-mono text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
              <span className="truncate font-medium">{scene.heading}</span>
            </button>
            {editable && active && !playing ? (
              <Textarea
                value={scene.narration}
                onChange={(e) => onNarration(scene.id, e.target.value)}
                rows={5}
                maxLength={900}
                aria-label={`Narration for scene ${i + 1}`}
                className="text-sm leading-relaxed"
              />
            ) : (
              <p className="cursor-pointer text-sm leading-relaxed text-muted-foreground" onClick={() => onJump(scene.id)}>
                {active && t
                  ? t.words.map((w, k) => (
                      <span key={k} className={cn(playing && local >= w.start && local < w.end + 0.08 ? "rounded bg-ember/25 text-foreground" : local >= w.end ? "text-foreground" : "")}>
                        {w.text}{" "}
                      </span>
                    ))
                  : scene.narration}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
