import {
  Captions,
  CaptionsOff,
  Check,
  CloudOff,
  Link2,
  Loader2,
  Mic,
  Pause,
  Play,
  Plus,
  SkipBack,
  SkipForward,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { Logo } from "@/components/common/bits"
import { Stage } from "@/components/stage/Stage"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { deleteScene, duplicateScene, insertScene, MAX_SCENES, moveScene, updateScene } from "@/lib/edit"
import { buildTimeline, captionAt, clock, sceneAt } from "@/lib/timing"
import { usePlayback } from "@/lib/usePlayback"
import { cn } from "@/lib/utils"

import { AskAI } from "./AskAI"
import { SceneInspector, VoiceRow } from "./SceneInspector"
import { Script } from "./Script"
import { Timeline } from "./Timeline"
import type { EditorHost, VoiceState } from "./types"

export function Editor({ host, banner }: { host: EditorHost; banner?: React.ReactNode }) {
  const { board, voices } = host
  // while an AI edit runs, hand edits pause, so its reply can't overwrite what you typed
  const editable = host.editable && !host.locked
  const timeline = useMemo(() => buildTimeline(board, voices), [board, voices])
  const pb = usePlayback(timeline)
  const [selectedId, setSelectedId] = useState<string | null>(board.scenes[0]?.id ?? null)
  const [cc, setCc] = useState(true)
  const [tab, setTab] = useState(host.editable ? "scene" : "script")

  const current = sceneAt(timeline, pb.time)
  const activeId = pb.playing ? (current?.id ?? null) : selectedId
  const activeIndex = Math.max(0, board.scenes.findIndex((s) => s.id === activeId))
  const activeScene = board.scenes[activeIndex] ?? null
  const shownTiming = pb.playing ? current : timeline.scenes[activeIndex]
  const local = shownTiming ? pb.time - shownTiming.start : 0
  const inScene = shownTiming && pb.time >= shownTiming.start && pb.time < shownTiming.start + shownTiming.duration
  // While editing and paused, show the whole scene; while playing (or watching), reveal on cue.
  const preview = editable && !pb.playing
  const shown = shownTiming?.reveals.map((r) => (preview ? true : inScene ? local >= r : false))
  const caption = cc && pb.playing && inScene ? (captionAt(shownTiming, local)?.text ?? null) : null

  // when playback stops, keep the scene it stopped on selected
  useEffect(() => {
    if (!pb.playing && current) setSelectedId(current.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pb.playing])

  // a scene that no longer exists can't stay selected
  useEffect(() => {
    if (selectedId && !board.scenes.some((s) => s.id === selectedId)) setSelectedId(board.scenes[0]?.id ?? null)
  }, [board, selectedId])

  const select = useCallback(
    (id: string) => {
      setSelectedId(id)
      const t = timeline.scenes.find((s) => s.id === id)
      if (t) pb.seek(t.start + 0.001)
    },
    [timeline, pb],
  )

  const seek = (t: number) => {
    pb.seek(t)
    const s = sceneAt(timeline, t)
    if (s) setSelectedId(s.id)
  }

  const step = (by: -1 | 1) => {
    const i = Math.max(0, Math.min(board.scenes.length - 1, activeIndex + by))
    select(board.scenes[i].id)
  }

  // Space plays and pauses, unless you're typing
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest("input, textarea, select, [contenteditable], [role=combobox], [role=slider]")) return
      if (e.code === "Space") {
        e.preventDefault()
        pb.toggle()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [pb])

  const patchScene = (id: string, patch: Parameters<typeof updateScene>[2]) => host.setBoard(updateScene(board, id, patch))
  const stale = board.scenes.filter((s) => host.voiceState(s.id).kind === "stale").length

  const sceneName = (id: string) => {
    const i = board.scenes.findIndex((s) => s.id === id)
    return i >= 0 ? `Scene ${i + 1}, ${board.scenes[i].heading}:` : "A scene"
  }

  return (
    <div className="flex min-h-dvh flex-col bg-background animate-in duration-200 fade-in lg:h-dvh lg:overflow-hidden">
      {/* top bar */}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-3 sm:px-4">
        <Logo className="[&>span:last-child]:hidden sm:[&>span:last-child]:inline" />
        <div className="mx-1 h-5 w-px bg-border" aria-hidden />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-medium">{board.title}</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {board.scenes.length} scenes · {clock(timeline.total)}
          </p>
        </div>
        {editable && host.saveState ? <SaveBadge state={host.saveState} error={host.saveError} /> : null}
        {editable && host.voiceAll && stale > 0 ? (
          <Button size="sm" variant="secondary" onClick={host.voiceAll} className="hidden sm:inline-flex">
            <Mic /> Voice {stale} {stale === 1 ? "scene" : "scenes"}
          </Button>
        ) : null}
        {host.shareUrl ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  navigator.clipboard.writeText(host.shareUrl!).then(
                    () => toast.success("Link copied. Anyone with it can watch."),
                    () => toast.error("Couldn't copy the link."),
                  )
                }}
              >
                <Link2 /> <span className="hidden sm:inline">Share</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Copy a link anyone can watch</TooltipContent>
          </Tooltip>
        ) : null}
      </header>
      {banner}
      {host.locked ? (
        <div role="status" className="flex items-center gap-2 border-b border-border bg-ember-soft/40 px-4 py-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin text-ember motion-reduce:animate-none" aria-hidden /> {host.locked}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* scene rail */}
        <nav aria-label="Scenes" className="hidden w-[232px] shrink-0 flex-col border-r border-border bg-panel lg:flex">
          <ScrollArea className="min-h-0 flex-1">
            <ol className="flex flex-col gap-2 p-3">
              {board.scenes.map((scene, i) => (
                <li key={scene.id}>
                  <SceneThumb
                    index={i}
                    title={board.title}
                    scene={scene}
                    active={scene.id === activeId}
                    voice={host.voiceState(scene.id)}
                    seconds={timeline.scenes[i]?.duration ?? 0}
                    onClick={() => select(scene.id)}
                  />
                </li>
              ))}
            </ol>
          </ScrollArea>
          {editable ? (
            <div className="border-t border-border p-3">
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={board.scenes.length >= MAX_SCENES}
                title={board.scenes.length >= MAX_SCENES ? `A lesson has at most ${MAX_SCENES} scenes` : undefined}
                onClick={() => {
                  const r = insertScene(board, activeId)
                  host.setBoard(r.board)
                  setSelectedId(r.id)
                }}
              >
                <Plus /> Add scene
              </Button>
            </div>
          ) : null}
        </nav>

        {/* stage */}
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 items-center justify-center bg-[radial-gradient(ellipse_at_center,oklch(0.2_0.008_275),transparent_70%)] p-3 sm:p-6">
            <div className="w-full max-w-[min(100%,calc((100dvh-56px-176px-140px)*16/9))] max-lg:max-w-full">
              <Stage
                scene={activeScene}
                shown={shown}
                index={activeIndex}
                count={board.scenes.length}
                lessonTitle={board.title}
                caption={caption}
                className="rounded-[14px] shadow-[0_40px_90px_-30px_oklch(0_0_0/0.9),0_0_0_1px_oklch(1_0_0/0.06)]"
              />
            </div>
          </div>

          {/* transport */}
          <div className="flex shrink-0 items-center gap-2 border-t border-border px-3 py-2.5 sm:px-5">
            <Button variant="ghost" size="icon-sm" onClick={() => step(-1)} aria-label="Previous scene">
              <SkipBack />
            </Button>
            <Button size="icon-lg" className="rounded-full" onClick={pb.toggle} aria-label={pb.playing ? "Pause" : "Play"}>
              {pb.playing ? <Pause className="fill-current" /> : <Play className="ml-0.5 fill-current" />}
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={() => step(1)} aria-label="Next scene">
              <SkipForward />
            </Button>
            <span className="ml-1 font-mono text-xs text-muted-foreground tabular-nums" aria-live="off">
              <span className="text-foreground">{clock(pb.time)}</span> / {clock(timeline.total)}
            </span>
            {/* phone scrubber, in place of the timeline */}
            <input
              type="range"
              min={0}
              max={Math.max(1, timeline.total)}
              step={0.1}
              value={pb.time}
              onChange={(e) => seek(Number(e.target.value))}
              aria-label="Playhead"
              className="mx-2 h-1 min-w-0 flex-1 cursor-pointer accent-[var(--ember)] lg:hidden"
            />
            <div className="ml-auto flex items-center gap-1">
              {pb.audioError ? (
                <span role="status" className="text-xs text-destructive">
                  {pb.audioError}
                </span>
              ) : null}
              <Button variant="ghost" size="icon-sm" onClick={() => setCc((v) => !v)} aria-pressed={cc} aria-label={cc ? "Hide captions" : "Show captions"}>
                {cc ? <Captions /> : <CaptionsOff />}
              </Button>
            </div>
          </div>

          {/* phone: scenes as a strip */}
          <div className="border-t border-border lg:hidden">
            <ol className="flex snap-x gap-2 overflow-x-auto p-3" aria-label="Scenes">
              {board.scenes.map((scene, i) => (
                <li key={scene.id} className="w-[148px] shrink-0 snap-start">
                  <SceneThumb
                    index={i}
                    title={board.title}
                    scene={scene}
                    active={scene.id === activeId}
                    voice={host.voiceState(scene.id)}
                    seconds={timeline.scenes[i]?.duration ?? 0}
                    onClick={() => select(scene.id)}
                    compact
                  />
                </li>
              ))}
            </ol>
          </div>
        </main>

        {/* inspector */}
        <aside aria-label="Edit" className="flex shrink-0 flex-col border-t border-border bg-panel lg:w-[372px] lg:border-t-0 lg:border-l">
          <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col gap-0">
            <TabsList className="m-3 mb-0 grid w-auto grid-cols-3">
              <TabsTrigger value="scene">{editable ? "Edit scene" : "Scene"}</TabsTrigger>
              <TabsTrigger value="script">Script</TabsTrigger>
              <TabsTrigger value="ai">Ask AI</TabsTrigger>
            </TabsList>
            <ScrollArea className="min-h-0 flex-1">
              <TabsContent value="scene">
                {activeScene && editable ? (
                  <SceneInspector
                    scene={activeScene}
                    index={activeIndex}
                    count={board.scenes.length}
                    voice={host.voiceState(activeScene.id)}
                    onChange={(patch) => patchScene(activeScene.id, patch)}
                    onVoice={host.voiceScene ? () => host.voiceScene!(activeScene.id) : undefined}
                    onMove={(by) => host.setBoard(moveScene(board, activeScene.id, by))}
                    onDuplicate={() => {
                      const r = duplicateScene(board, activeScene.id)
                      host.setBoard(r.board)
                      setSelectedId(r.id)
                    }}
                    onDelete={() => host.setBoard(deleteScene(board, activeScene.id))}
                  />
                ) : activeScene ? (
                  <div className="flex flex-col gap-3 p-4 text-sm">
                    <p className="font-serif text-2xl leading-tight">{activeScene.heading}</p>
                    <p className="leading-relaxed text-muted-foreground">{activeScene.narration}</p>
                    <VoiceRow voice={host.voiceState(activeScene.id)} />
                    <p className="text-xs text-muted-foreground">You're watching. Only the person who made this lesson can change it.</p>
                  </div>
                ) : null}
              </TabsContent>
              <TabsContent value="script">
                <Script
                  board={board}
                  timeline={timeline}
                  time={pb.time}
                  playing={pb.playing}
                  activeId={activeId}
                  editable={editable}
                  onJump={select}
                  onNarration={(id, text) => patchScene(id, { narration: text })}
                />
              </TabsContent>
              <TabsContent value="ai">
                <AskAI
                  scene={activeScene}
                  sceneIndex={activeIndex}
                  aiEdit={host.editable ? host.aiEdit : null}
                  unavailable={host.editable ? host.aiUnavailable : "Only the person who made this lesson can ask for changes."}
                  onJump={select}
                  sceneName={sceneName}
                />
              </TabsContent>
            </ScrollArea>
          </Tabs>
        </aside>
      </div>

      <Timeline
        className="hidden h-[156px] shrink-0 lg:block"
        timeline={timeline}
        board={board}
        time={pb.time}
        activeId={activeId}
        voiceState={host.voiceState}
        onSeek={seek}
        onSelect={select}
      />
    </div>
  )
}

function SceneThumb({ index, title, scene, active, voice, seconds, onClick, compact }: {
  index: number
  title: string
  scene: EditorHost["board"]["scenes"][number]
  active: boolean
  voice: VoiceState
  seconds: number
  onClick: () => void
  compact?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active || undefined}
      aria-label={`Scene ${index + 1}: ${scene.heading}`}
      className={cn(
        "group w-full rounded-[12px] border p-1.5 text-left transition-colors",
        active ? "border-ember bg-ember-soft" : "border-transparent hover:border-border hover:bg-panel-raised",
      )}
    >
      <Stage scene={scene} lessonTitle={title} thumb className="rounded-[7px] ring-1 ring-black/20" />
      <div className="flex items-center gap-1.5 px-0.5 pt-1.5 text-[11px]">
        <span className="font-mono text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
        {!compact ? <span className="min-w-0 flex-1 truncate">{scene.heading}</span> : <span className="flex-1" />}
        <VoiceDot voice={voice} />
        <span className="font-mono text-muted-foreground tabular-nums">{clock(seconds)}</span>
      </div>
    </button>
  )
}

function VoiceDot({ voice }: { voice: VoiceState }) {
  const label = { voiced: "Voiced", stale: "Not voiced yet", voicing: "Voicing", failed: "Voice failed" }[voice.kind]
  if (voice.kind === "voicing") return <Loader2 className="size-3 animate-spin text-ember" aria-label={label} />
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        "size-1.5 rounded-full",
        voice.kind === "voiced" ? "bg-ok" : voice.kind === "failed" ? "bg-destructive" : "bg-muted-foreground/50",
      )}
    />
  )
}

function SaveBadge({ state, error }: { state: NonNullable<EditorHost["saveState"]>; error?: string }) {
  const map = {
    saved: [<Check key="i" />, "Saved", "text-muted-foreground"],
    saving: [<Loader2 key="i" className="animate-spin" />, "Saving…", "text-muted-foreground"],
    unsaved: [<Loader2 key="i" className="animate-spin" />, "Saving…", "text-muted-foreground"],
    error: [<CloudOff key="i" />, "Not saved", "text-destructive"],
  } as const
  const [icon, label, cls] = map[state]
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs [&_svg]:size-3.5", cls)} role="status" title={error}>
      {icon} <span className={state === "error" ? "" : "sr-only sm:not-sr-only"}>{label}</span>
    </span>
  )
}
