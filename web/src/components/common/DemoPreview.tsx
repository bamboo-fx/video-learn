/**
 * The example lesson, shown on the home page as what you'll get: its real scenes, drawn by
 * the real stage, stepping through on their own. Clicking it opens the full example.
 * No audio, no API. Holds still under reduced motion.
 */
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { Play } from "lucide-react"
import { useEffect, useState } from "react"

import { Stage } from "@/components/stage/Stage"
import type { Storyboard } from "@/lib/api"
import { navigate } from "@/lib/router"
import { cn } from "@/lib/utils"
import demo from "../../../../shared/demo-lesson.json"

const board = demo.storyboard as Storyboard

export function DemoPreview({ className }: { className?: string }) {
  const reduce = useReducedMotion()
  const [i, setI] = useState(0)
  const scenes = board.scenes

  useEffect(() => {
    if (reduce) return
    const t = setInterval(() => setI((n) => (n + 1) % scenes.length), 3800)
    return () => clearInterval(t)
  }, [reduce, scenes.length])

  const scene = scenes[i]

  return (
    <figure className={cn("flex flex-col gap-3", className)}>
      <a
        href="/demo"
        onClick={(e) => {
          e.preventDefault()
          navigate("/demo")
        }}
        aria-label={`Watch the example lesson: ${board.title}`}
        className="group relative block overflow-hidden rounded-[14px] shadow-[0_0_0_1px_oklch(1_0_0/0.07),0_30px_70px_-35px_oklch(0_0_0/0.9)]"
      >
        <div className="relative aspect-video bg-paper">
          <AnimatePresence initial={false}>
            <motion.div
              key={scene.id}
              className="absolute inset-0"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.6 }}
            >
              <Stage scene={scene} index={i} count={scenes.length} lessonTitle={board.title} thumb={false} />
            </motion.div>
          </AnimatePresence>
        </div>
        <span className="absolute inset-0 flex items-center justify-center bg-ink/0 transition-colors duration-300 group-hover:bg-ink/25 group-focus-visible:bg-ink/25">
          <span className="flex size-14 scale-90 items-center justify-center rounded-full bg-ember text-primary-foreground opacity-0 shadow-xl transition-all duration-300 group-hover:scale-100 group-hover:opacity-100 group-focus-visible:scale-100 group-focus-visible:opacity-100">
            <Play className="ml-0.5 size-5 fill-current" aria-hidden />
          </span>
        </span>
      </a>
      <figcaption className="flex items-center gap-3 text-xs text-muted-foreground">
        <button
          type="button"
          onClick={() => navigate("/demo")}
          className="inline-flex shrink-0 items-center gap-1.5 font-medium text-foreground transition-colors hover:text-ember"
        >
          <Play className="size-3 fill-current text-ember" aria-hidden /> Example
        </button>
        <span className="min-w-0 flex-1 truncate font-mono">{demo.repo}</span>
        <span className="flex shrink-0 gap-1" aria-hidden>
          {scenes.map((s, k) => (
            <span key={s.id} className={cn("h-1 rounded-full transition-all duration-500", k === i ? "w-4 bg-ember" : "w-1 bg-muted-foreground/40")} />
          ))}
        </span>
      </figcaption>
    </figure>
  )
}
