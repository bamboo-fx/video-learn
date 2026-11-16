import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Loader2, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Problem, QuietLoading, Shell } from "@/components/common/bits"
import { Editor } from "@/components/editor/Editor"
import type { EditorHost, VoiceState } from "@/components/editor/types"
import { Button } from "@/components/ui/button"
import { api, ApiError, type EditResult, type Project, type Storyboard, type Voice } from "@/lib/api"
import { navigate } from "@/lib/router"

export const configQuery = { queryKey: ["config"], queryFn: api.config, staleTime: 5 * 60_000, gcTime: 60 * 60_000 }

export function Lesson({ id }: { id: string }) {
  const qc = useQueryClient()
  const key = ["project", id]
  const writingHere = typeof sessionStorage !== "undefined" && sessionStorage.getItem(`writing:${id}`) === "1"

  const project = useQuery({
    queryKey: key,
    queryFn: () => api.get(id),
    refetchInterval: (q) => {
      const p = q.state.data as Project | undefined
      return p && (p.status === "writing" || (p.status === "new" && writingHere)) ? 1500 : false
    },
  })
  const config = useQuery(configQuery)

  const p = project.data
  if (project.isPending) return <QuietLoading label="Opening the lesson" className="min-h-dvh" />
  if (project.isError) {
    const notFound = project.error instanceof ApiError && project.error.status === 404
    return (
      <Shell>
        <div className="py-16">
          <Problem
            title={notFound ? "That lesson doesn't exist" : "The lesson didn't load"}
            action={
              notFound ? (
                <Button size="sm" onClick={() => navigate("/")}>Make a lesson</Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => project.refetch()}>Try again</Button>
              )
            }
          >
            {project.error instanceof ApiError ? project.error.message : "Something went wrong."}
          </Problem>
        </div>
      </Shell>
    )
  }
  if (!p) return null

  if (p.status === "writing" || (p.status === "new" && writingHere)) return <Writing project={p} />
  if (p.status === "failed" || p.status === "new" || !p.storyboard) {
    return <NotWritten project={p} aiReady={config.data?.ai ?? true} onWritten={(np) => qc.setQueryData(key, np)} />
  }
  return <Workspace project={p} aiReady={config.data?.ai ?? true} voiceReady={config.data?.voice ?? true} />
}

// ---------------------------------------------------------------- while Claude writes

const STEPS = ["Reading your topic and notes", "Planning the scenes", "Writing the narration", "Checking the lesson"]

function Writing({ project }: { project: Project }) {
  const [step, setStep] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setStep((s) => Math.min(STEPS.length - 1, s + 1)), 7000)
    return () => clearInterval(t)
  }, [])
  return (
    <Shell>
      <div className="mx-auto max-w-md py-24" role="status" aria-label="Writing the lesson">
        <p className="mb-2 text-xs text-muted-foreground">Claude is writing</p>
        <h1 className="font-serif text-4xl leading-tight text-balance">{project.topic}</h1>
        <ol className="mt-10 flex flex-col gap-3 text-sm">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-3">
              {i < step ? (
                <Check className="size-4 text-ok" aria-hidden />
              ) : i === step ? (
                <Loader2 className="size-4 animate-spin text-ember motion-reduce:animate-none" aria-hidden />
              ) : (
                <span className="size-4 rounded-full border border-border" aria-hidden />
              )}
              <span className={i <= step ? "text-foreground" : "text-muted-foreground"}>{s}</span>
            </li>
          ))}
        </ol>
        <p className="mt-10 text-xs text-muted-foreground">This usually takes under a minute. You can leave this page; the lesson keeps writing.</p>
      </div>
    </Shell>
  )
}

function NotWritten({ project, aiReady, onWritten }: { project: Project; aiReady: boolean; onWritten: (p: Project) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const retry = async () => {
    setBusy(true)
    setError(null)
    sessionStorage.setItem(`autovoice:${project.id}`, "1")
    try {
      onWritten(await api.write(project.id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "It didn't work this time.")
    } finally {
      setBusy(false)
    }
  }
  return (
    <Shell>
      <div className="mx-auto max-w-lg py-20">
        <h1 className="font-serif text-4xl leading-tight">{project.topic}</h1>
        <div className="mt-8">
          <Problem
            title={project.status === "failed" ? "The lesson didn't get written" : "This lesson hasn't been written yet"}
            action={
              project.is_owner ? (
                <Button size="sm" onClick={retry} disabled={busy || !aiReady}>
                  {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />} {project.status === "failed" ? "Try again" : "Write it"}
                </Button>
              ) : null
            }
          >
            {error ?? (project.error || (!aiReady ? "AI writing isn't set up on this server yet, so lessons can't be written right now." : "Claude hasn't written it yet."))}
          </Problem>
        </div>
      </div>
    </Shell>
  )
}

// ---------------------------------------------------------------- the editor, on the real API

function Workspace({ project, aiReady, voiceReady }: { project: Project; aiReady: boolean; voiceReady: boolean }) {
  const qc = useQueryClient()
  const key = ["project", project.id]
  const [board, setBoardState] = useState<Storyboard>(project.storyboard!)
  const [saveState, setSaveState] = useState<EditorHost["saveState"]>("saved")
  const [saveError, setSaveError] = useState<string>()
  const [voicing, setVoicing] = useState<Record<string, boolean>>({})
  const [failed, setFailed] = useState<Record<string, string>>({})
  const voices = project.voices

  const dirty = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inflight = useRef<Promise<void> | null>(null)
  const latest = useRef(board)
  latest.current = board

  // when the server's copy changes under us (an AI edit), take it if we have no edits pending
  const serverBoard = project.storyboard
  useEffect(() => {
    if (!dirty.current && serverBoard) setBoardState(serverBoard)
  }, [serverBoard])

  const save = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    // one save at a time: an older response must never land after a newer request starts
    while (inflight.current) {
      try {
        await inflight.current
      } catch {
        // the earlier save failed; this one retries with the latest board
      }
    }
    if (!dirty.current) return
    dirty.current = false
    setSaveState("saving")
    const run = (async () => {
      try {
        const saved = await api.save(project.id, latest.current)
        qc.setQueryData(key, saved)
        setSaveState(dirty.current ? "unsaved" : "saved")
        setSaveError(undefined)
      } catch (e) {
        dirty.current = true
        setSaveState("error")
        setSaveError(e instanceof ApiError ? e.message : "Couldn't save.")
        throw e
      }
    })()
    inflight.current = run
    try {
      await run
    } finally {
      if (inflight.current === run) inflight.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  const setBoard = (next: Storyboard) => {
    setBoardState(next)
    dirty.current = true
    setSaveState("unsaved")
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => save().catch(() => {}), 800)
  }

  // save before leaving
  useEffect(() => {
    const onLeave = (e: BeforeUnloadEvent) => {
      if (dirty.current) {
        save().catch(() => {})
        e.preventDefault()
      }
    }
    window.addEventListener("beforeunload", onLeave)
    return () => window.removeEventListener("beforeunload", onLeave)
  }, [save])

  const voiceState = (sceneId: string): VoiceState => {
    if (voicing[sceneId]) return { kind: "voicing" }
    if (failed[sceneId]) return { kind: "failed", message: failed[sceneId] }
    const scene = board.scenes.find((s) => s.id === sceneId)
    const v = voices[sceneId]
    return v && scene && v.text === scene.narration ? { kind: "voiced" } : { kind: "stale" }
  }

  const voiceScene = useCallback(
    async (sceneId: string) => {
      setVoicing((m) => ({ ...m, [sceneId]: true }))
      setFailed(({ [sceneId]: _, ...rest }) => rest)
      try {
        await save()
        const voice: Voice = await api.voice(project.id, sceneId)
        qc.setQueryData<Project>(key, (old) => (old ? { ...old, voices: { ...old.voices, [sceneId]: voice } } : old))
      } catch (e) {
        setFailed((m) => ({ ...m, [sceneId]: e instanceof ApiError ? e.message : "The voice didn't come through. Try again." }))
      } finally {
        setVoicing(({ [sceneId]: _, ...rest }) => rest)
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [project.id, save],
  )

  const voiceMany = useCallback(
    async (ids: string[]) => {
      const queue = [...ids]
      const worker = async () => {
        while (queue.length) await voiceScene(queue.shift()!)
      }
      await Promise.all([worker(), worker()])
    },
    [voiceScene],
  )

  const staleIds = () =>
    latest.current.scenes.filter((s) => !(voices[s.id] && voices[s.id].text === s.narration)).map((s) => s.id)

  // first open after writing: voice the whole lesson once
  const autoVoiced = useRef(false)
  useEffect(() => {
    if (autoVoiced.current || !project.is_owner || !voiceReady) return
    if (sessionStorage.getItem(`autovoice:${project.id}`) !== "1") return
    autoVoiced.current = true
    sessionStorage.removeItem(`autovoice:${project.id}`)
    sessionStorage.removeItem(`writing:${project.id}`)
    voiceMany(staleIds())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const aiEdit = async (instruction: string, sceneId: string | null): Promise<EditResult> => {
    await save()
    const result = await api.edit(project.id, instruction, sceneId)
    qc.setQueryData(key, result.project)
    setBoardState(result.project.storyboard!)
    const changed = result.changes.filter((c) => c.kind === "updated" || c.kind === "inserted").map((c) => c.scene_id)
    if (voiceReady && changed.length) {
      const sb = result.project.storyboard!
      const needs = changed.filter((id) => {
        const s = sb.scenes.find((x) => x.id === id)
        const v = result.project.voices[id]
        return s && !(v && v.text === s.narration)
      })
      if (needs.length) voiceMany(needs)
    }
    return result
  }

  const host: EditorHost = {
    board,
    voices,
    editable: project.is_owner,
    setBoard,
    saveState,
    saveError,
    voiceState,
    voiceScene: voiceReady ? voiceScene : undefined,
    voiceAll: voiceReady
      ? () => {
          save()
            .then(() => voiceMany(staleIds()))
            .catch(() => toast.error("Save failed, so nothing was voiced."))
        }
      : undefined,
    aiEdit: aiReady ? aiEdit : null,
    aiUnavailable: aiReady ? undefined : "AI edits aren't set up on this server yet. You can still edit every scene by hand.",
    shareUrl: `${window.location.origin}/l/${project.id}`,
  }

  return (
    <Editor
      host={host}
      banner={
        !voiceReady && project.is_owner ? (
          <div className="border-b border-border bg-panel-raised px-4 py-2 text-xs text-muted-foreground" role="status">
            Voices aren't set up on this server yet, so the lesson plays silently with captions.
          </div>
        ) : null
      }
    />
  )
}
