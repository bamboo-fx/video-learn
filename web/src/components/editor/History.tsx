/** The lesson's history: every version of the storyboard, newest first, like the commits on
 * a branch. Look at any of them on the stage, or go back to one. Going back adds a version
 * on top instead of deleting the ones after it, so it can always be undone. */
import { Eye, GitCommitVertical, Loader2, RotateCcw, Sparkles, Tag } from "lucide-react"
import { useCallback, useEffect, useId, useRef, useState } from "react"
import { toast } from "sonner"

import { Problem, QuietLoading, relativeTime } from "@/components/common/bits"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ApiError, type VersionChange, type VersionFull, type VersionInfo } from "@/lib/api"
import { cn } from "@/lib/utils"

import type { HistoryHost } from "./types"

interface Props {
  host: HistoryHost
  /** the version on the stage right now, if someone is looking at one */
  viewing: number | null
  onView: (version: VersionFull | null) => void
  /** a reason the lesson can't be changed right now (an AI edit is running) */
  locked?: string
}

const why = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

export function History({ host, viewing, onView, locked }: Props) {
  // One list, newest first. The newest page reloads whenever the lesson changes and goes on
  // top of what's shown; "Show older" adds the page after the bottom.
  const [list, setList] = useState<{ versions: VersionInfo[]; more: boolean } | null>(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<{ id: number; what: "view" | "restore" } | null>(null)
  const [name, setName] = useState("")
  const [naming, setNaming] = useState(false)
  const nameId = useId()
  const asked = useRef(0)

  const load = useCallback(() => {
    const mine = ++asked.current
    host.list().then(
      (page) => {
        if (mine !== asked.current) return // a newer request is on its way
        setList((prev) => onTop(prev, page))
        setError(null)
      },
      (e) => mine === asked.current && setError(why(e, "The history didn't load.")),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // on opening, and again whenever the lesson changes (the list stays on screen meanwhile)
  useEffect(load, [load, host.rev])

  const versions = list?.versions ?? null
  const more = !!list?.more

  const loadOlder = async () => {
    if (!versions?.length || loadingOlder) return
    setLoadingOlder(true)
    try {
      const bottom = versions[versions.length - 1].id
      const page = await host.list(bottom)
      setList((l) => (l ? { versions: [...l.versions, ...page.versions.filter((v) => v.id < bottom)], more: page.more } : page))
    } catch (e) {
      toast.error(why(e, "The older versions didn't load."))
    } finally {
      setLoadingOlder(false)
    }
  }

  const view = async (v: VersionInfo) => {
    if (viewing === v.id) return onView(null)
    setBusy({ id: v.id, what: "view" })
    try {
      onView(await host.load(v.id))
    } catch (e) {
      toast.error(why(e, "That version didn't load."))
    } finally {
      setBusy(null)
    }
  }

  const restore = async (v: VersionInfo) => {
    setBusy({ id: v.id, what: "restore" })
    try {
      await host.restore(v.id)
      onView(null)
      toast.success(`The lesson is back at version ${v.number}.`, { description: "The versions after it are still here, so you can undo this." })
      load()
    } catch (e) {
      toast.error(why(e, "Couldn't go back to that version."))
    } finally {
      setBusy(null)
    }
  }

  const saveName = async () => {
    if (!name.trim() || naming) return
    setNaming(true)
    try {
      await host.name(name.trim())
      toast.success(`Saved as “${name.trim()}”.`)
      setName("")
      load()
    } catch (e) {
      toast.error(why(e, "Couldn't save that version."))
    } finally {
      setNaming(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          saveName()
        }}
      >
        <label htmlFor={nameId} className="text-xs text-muted-foreground">
          Every change is kept here on its own. Name the lesson as it is now to find it again easily.
        </label>
        <div className="flex gap-2">
          <Input id={nameId} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Before the review" disabled={naming} />
          <Button type="submit" variant="secondary" disabled={!name.trim() || naming} className="shrink-0">
            {naming ? <Loader2 className="animate-spin" /> : <Tag />} Save version
          </Button>
        </div>
      </form>

      {error && !versions ? (
        <Problem title="The history didn't load" action={<Button size="sm" variant="outline" onClick={load}>Try again</Button>}>
          {error}
        </Problem>
      ) : !versions ? (
        <QuietLoading label="Loading the history" className="py-8" />
      ) : versions.length === 0 ? (
        <p className="rounded-xl border border-border bg-panel-raised/50 p-4 text-sm text-muted-foreground">
          No versions yet. The first change you make starts the history, and the lesson as it is now will be its first entry.
        </p>
      ) : (
        <ol className="relative flex flex-col" aria-label="Versions, newest first">
          {versions.map((v, i) => (
            <li key={v.id} className="relative flex gap-3 pb-4 last:pb-0">
              {/* the line down the side that makes it read as one history */}
              {i < versions.length - 1 ? <span className="absolute top-5 bottom-0 left-[9px] w-px bg-border" aria-hidden /> : null}
              <span
                className={cn(
                  "relative z-10 mt-0.5 flex size-[19px] shrink-0 items-center justify-center rounded-full border bg-panel",
                  v.current ? "border-ember text-ember" : "border-border text-muted-foreground",
                )}
                aria-hidden
              >
                {v.kind === "write" || v.kind === "ai" ? <Sparkles className="size-2.5" /> : v.name ? <Tag className="size-2.5" /> : <GitCommitVertical className="size-3" />}
              </span>
              <div
                className={cn(
                  "min-w-0 flex-1 rounded-xl border p-3 transition-colors",
                  viewing === v.id ? "border-ember/60 bg-ember-soft/40" : "border-border",
                )}
              >
                <div className="flex items-baseline gap-2 text-[11px] text-muted-foreground">
                  <span className="font-mono">v{v.number}</span>
                  {v.current ? <span className="rounded-full bg-ember-soft px-1.5 py-px font-medium text-ember">Now</span> : null}
                  <time dateTime={v.updated_at} title={new Date(v.updated_at).toLocaleString()} className="ml-auto shrink-0 tabular-nums">
                    {relativeTime(v.updated_at)}
                  </time>
                </div>
                <p className="mt-1 text-sm leading-snug font-medium text-pretty break-words">{v.name || title(v)}</p>
                {v.name ? <p className="mt-0.5 text-xs text-muted-foreground">{title(v)}</p> : null}
                {v.authors.length ? <p className="mt-0.5 text-xs text-muted-foreground">{byline(v)}</p> : null}
                <Changes changes={v.changes} />
                {!v.current ? (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    <Button size="xs" variant={viewing === v.id ? "secondary" : "outline"} onClick={() => view(v)} disabled={!!busy} aria-pressed={viewing === v.id}>
                      {busy?.id === v.id && busy.what === "view" ? <Loader2 className="animate-spin" /> : <Eye />}
                      {viewing === v.id ? "Stop looking" : "Look"}
                    </Button>
                    <Button size="xs" variant="outline" onClick={() => restore(v)} disabled={!!busy || !!locked} title={locked}>
                      {busy?.id === v.id && busy.what === "restore" ? <Loader2 className="animate-spin" /> : <RotateCcw />}
                      Go back to this
                    </Button>
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
      {versions?.length && more ? (
        <Button size="sm" variant="outline" className="self-center" onClick={loadOlder} disabled={loadingOlder}>
          {loadingOlder ? <Loader2 className="animate-spin" /> : null} Show older versions
        </Button>
      ) : null}
    </div>
  )
}

/** The newest page put on top of the list already shown. Versions are numbered in order, so
 * when the page reaches down into what's shown, everything below the page's last version is
 * still right; when it doesn't (many versions were made since), what's shown would leave a
 * gap, so the list starts over from the page. */
function onTop(prev: { versions: VersionInfo[]; more: boolean } | null, page: { versions: VersionInfo[]; more: boolean }) {
  if (!prev || !page.versions.length || !page.more) return page
  const last = page.versions[page.versions.length - 1].id
  if (!prev.versions.some((v) => v.id >= last)) return page
  const below = prev.versions.filter((v) => v.id < last)
  return below.length ? { versions: [...page.versions, ...below], more: prev.more } : page
}

/** What happened in this version, in the words the page uses elsewhere. */
function title(v: VersionInfo): string {
  switch (v.kind) {
    case "hand":
      return "Edited by hand"
    case "ai":
      return `Asked Claude: “${v.message}”`
    case "start":
      return "The lesson before its history began"
    default:
      return v.message || "A version"
  }
}

function byline(v: VersionInfo): string {
  const names = v.authors.length > 2 ? `${v.authors.slice(0, -1).join(", ")} and ${v.authors[v.authors.length - 1]}` : v.authors.join(" and ")
  return v.kind === "ai" || v.kind === "write" ? `Asked by ${names}` : `By ${names}`
}

const SHOWN = 4

function Changes({ changes }: { changes: VersionChange[] }) {
  if (!changes.length) return null
  return (
    <ul className="mt-2 flex flex-col gap-1" aria-label="What changed">
      {changes.slice(0, SHOWN).map((c, k) => (
        <li key={k} className="flex items-start gap-1.5 text-xs">
          <span className={cn("mt-px shrink-0 rounded px-1.5 py-px font-mono text-[10px] uppercase", KIND[c.kind])}>{LABEL[c.kind]}</span>
          <span className="min-w-0 text-muted-foreground">
            {c.kind === "reordered" ? (
              "Scenes are in a different order"
            ) : c.kind === "lesson" ? (
              `The lesson's ${c.fields.join(" and ")}`
            ) : (
              <>
                <span className="text-foreground">{c.heading || "A scene"}</span>
                {c.fields.length ? `: ${c.fields.join(", ")}` : ""}
              </>
            )}
          </span>
        </li>
      ))}
      {changes.length > SHOWN ? <li className="text-xs text-muted-foreground">and {changes.length - SHOWN} more</li> : null}
    </ul>
  )
}

const LABEL: Record<VersionChange["kind"], string> = { lesson: "changed", added: "added", changed: "changed", removed: "removed", reordered: "moved" }

const KIND: Record<VersionChange["kind"], string> = {
  lesson: "bg-ember-soft text-ember",
  changed: "bg-ember-soft text-ember",
  added: "bg-ok/15 text-ok",
  removed: "bg-destructive/15 text-destructive",
  reordered: "bg-muted text-muted-foreground",
}
