/** Ask Claude to change the lesson. It edits the storyboard through small tools, so the
 * answer is a list of concrete changes you can see (and undo by hand), not a new video. */
import { ArrowUp, Loader2, Sparkles, Wand2 } from "lucide-react"
import { useId, useState } from "react"

import { Problem } from "@/components/common/bits"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ApiError, type EditResult, type Scene } from "@/lib/api"
import { cn } from "@/lib/utils"

const SUGGESTIONS = {
  scene: ["Use simpler words", "Add an analogy", "Make it shorter", "Turn it into steps"],
  lesson: ["Add a worked example", "Explain it for a beginner", "Add a check-your-understanding scene", "Tighten the whole thing"],
}

interface Turn {
  instruction: string
  scope: string
  result?: EditResult
  error?: string
}

interface Props {
  scene: Scene | null
  sceneIndex: number
  aiEdit: ((instruction: string, sceneId: string | null) => Promise<EditResult>) | null
  unavailable?: string
  onJump: (sceneId: string) => void
  sceneName: (sceneId: string) => string
}

export function AskAI({ scene, sceneIndex, aiEdit, unavailable, onJump, sceneName }: Props) {
  const [scope, setScope] = useState<"scene" | "lesson">("scene")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const inputId = useId()

  const submit = async (instruction: string) => {
    if (!aiEdit || !instruction.trim() || busy) return
    const sceneId = scope === "scene" ? (scene?.id ?? null) : null
    const label = sceneId ? `Scene ${sceneIndex + 1}` : "Whole lesson"
    setBusy(true)
    setText("")
    setTurns((t) => [{ instruction, scope: label }, ...t])
    try {
      const result = await aiEdit(instruction.trim(), sceneId)
      setTurns((t) => [{ instruction, scope: label, result }, ...t.slice(1)])
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "The edit didn't go through. Try again."
      setTurns((t) => [{ instruction, scope: label, error: message }, ...t.slice(1)])
    } finally {
      setBusy(false)
    }
  }

  if (!aiEdit) {
    return (
      <div className="p-4">
        <div className="rounded-xl border border-border bg-panel-raised/50 p-4 text-sm text-muted-foreground">
          <Wand2 className="mb-2 size-4 text-ember" aria-hidden />
          {unavailable ?? "Asking the AI for changes isn't available here."}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <ToggleGroup
        type="single"
        value={scope}
        onValueChange={(v) => v && setScope(v as "scene" | "lesson")}
        variant="outline"
        size="sm"
        spacing={0}
        className="w-full"
        aria-label="What to change"
      >
        <ToggleGroupItem value="scene" className="flex-1" disabled={!scene}>
          Scene {sceneIndex + 1}
        </ToggleGroupItem>
        <ToggleGroupItem value="lesson" className="flex-1">
          Whole lesson
        </ToggleGroupItem>
      </ToggleGroup>

      <form
        className="rounded-2xl border border-border bg-panel-raised/60 p-2 focus-within:border-ember/50"
        onSubmit={(e) => {
          e.preventDefault()
          submit(text)
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          What should change?
        </label>
        <Textarea
          id={inputId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              submit(text)
            }
          }}
          rows={3}
          maxLength={600}
          placeholder={scope === "scene" ? `What should change in “${scene?.heading ?? "this scene"}”?` : "What should change in the lesson?"}
          className="resize-none border-0 bg-transparent text-sm shadow-none focus-visible:ring-0 dark:bg-transparent"
          disabled={busy}
        />
        <div className="flex justify-end">
          <Button type="submit" size="icon-sm" disabled={busy || !text.trim()} aria-label="Ask for this change">
            {busy ? <Loader2 className="animate-spin" /> : <ArrowUp />}
          </Button>
        </div>
      </form>

      <div className="flex flex-wrap gap-1.5">
        {SUGGESTIONS[scope].map((s) => (
          <button
            key={s}
            type="button"
            disabled={busy}
            onClick={() => submit(s)}
            className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-ember/40 hover:text-foreground disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      <ol className="flex flex-col gap-3" aria-live="polite">
        {turns.map((t, i) => (
          <li key={turns.length - i} className="rounded-xl border border-border p-3 text-sm">
            <p className="text-xs text-muted-foreground">
              {t.scope} · <span className="text-foreground">{t.instruction}</span>
            </p>
            {t.error ? (
              <div className="mt-2">
                <Problem title="That edit didn't happen">{t.error}</Problem>
              </div>
            ) : t.result ? (
              <div className="mt-2">
                <p className="flex gap-2">
                  <Sparkles className="mt-0.5 size-3.5 shrink-0 text-ember" aria-hidden />
                  <span>{t.result.summary}</span>
                </p>
                {t.result.changes.length ? (
                  <ul className="mt-2 flex flex-col gap-1">
                    {t.result.changes.map((c, k) => (
                      <li key={k}>
                        <button
                          type="button"
                          disabled={c.kind === "deleted"}
                          onClick={() => onJump(c.scene_id)}
                          className={cn(
                            "flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors",
                            c.kind !== "deleted" && "hover:bg-panel-raised",
                          )}
                        >
                          <span className={cn("rounded px-1.5 py-px font-mono text-[10px] uppercase", KIND[c.kind])}>{c.kind}</span>
                          <span className="min-w-0 flex-1 text-muted-foreground">
                            <span className="text-foreground">{sceneName(c.scene_id)}</span> {c.note}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground" role="status">
                <Loader2 className="size-3.5 animate-spin" aria-hidden /> Claude is reading the lesson and making the change…
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

const KIND: Record<string, string> = {
  updated: "bg-ember-soft text-ember",
  inserted: "bg-ok/15 text-ok",
  deleted: "bg-destructive/15 text-destructive",
  moved: "bg-muted text-muted-foreground",
}
