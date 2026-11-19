import {
  Captions,
  CaptionsOff,
  Check,
  CloudOff,
  FastForward,
  History as HistoryIcon,
  Link2,
  Loader2,
  Mic,
  Pause,
  Play,
  Plus,
  Rewind,
  SkipBack,
  SkipForward,
  Users,
  X,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { Logo } from "@/components/common/bits"
import { Stage } from "@/components/stage/Stage"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { TextShimmer } from "@/components/ui/text-shimmer"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ApiError, githubUrl, type VersionFull } from "@/lib/api"
import { deleteScene, duplicateScene, insertScene, MAX_SCENES, moveScene, updateScene } from "@/lib/edit"
import { buildTimeline, captionAt, clock, sceneAt } from "@/lib/timing"
import { RATES, usePlayback } from "@/lib/usePlayback"
import { cn } from "@/lib/utils"

import { AskAI } from "./AskAI"
import { History } from "./History"
import { SceneInspector, VoiceRow } from "./SceneInspector"
import { Script } from "./Script"
import { ShareDialog } from "./ShareDialog"
import { Timeline } from "./Timeline"
import type { EditorHost, VoiceState } from "./types"

export function Editor({ host, banner }: { host: EditorHost; banner?: React.ReactNode }) {
  const { voices } = host
  // Looking at an older version puts its storyboard on the stage in place of the lesson's.
  // It plays like any lesson; nothing can be changed until you stop looking.
  const [viewing, setViewing] = useState<VersionFull | null>(null)
  const board = viewing?.storyboard ?? host.board
  // while an AI edit runs, hand edits pause, so its reply can't overwrite what you typed
  const editable = host.editable && !host.locked && !viewing
  const voiceState = viewing
    ? (id: string): VoiceState => {
        const scene = board.scenes.find((s) => s.id === id)
        return scene && voices[id]?.text === scene.narration ? { kind: "voiced" } : { kind: "stale" }
      }
    : host.voiceState
  // an older version's code may come from an older commit
  const repo = viewing?.repo_sha && host.repo ? { name: host.repo.name, sha: viewing.repo_sha } : host.repo
  const [sharing, setSharing] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const timeline = useMemo(() => buildTimeline(board, voices), [board, voices])
  const pb = usePlayback(timeline)
  const [selectedId, setSelectedId] = useState<string | null>(board.scenes[0]?.id ?? null)
  const [cc, setCc] = useState(true)
  const [tab, setTab] = useState(host.editable ? "scene" : "script")
  // someone who just became an editor (an invite or claim link answered) lands on the editing tab
  const [wasEditable, setWasEditable] = useState(host.editable)
  if (host.editable !== wasEditable) {
    setWasEditable(host.editable)
    if (host.editable && tab === "script") setTab("scene")
  }

  const current = sceneAt(timeline, pb.time)
  const activeId = pb.playing ? (current?.id ?? null) : selectedId
  const activeIndex = Math.max(0, board.scenes.findIndex((s) => s.id === activeId))
  const activeScene = board.scenes[activeIndex] ?? null
  const shownTiming = pb.playing ? current : timeline.scenes[activeIndex]
  const local = shownTiming ? pb.time - shownTiming.start : 0
  const inScene = shownTiming && pb.time >= shownTiming.start && pb.time < shownTiming.start + shownTiming.duration
  // Paused, show the whole scene (a half-empty slide reads as broken); playing, reveal on cue.
  const preview = !pb.playing
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

  /** Jump by seconds. Playback carries on from the new spot if it was playing. */
  const skip = (by: number) => seek(pb.time + by)

  const stepRate = (by: -1 | 1) => {
    const i = RATES.indexOf(pb.rate as (typeof RATES)[number])
    pb.setRate(RATES[Math.max(0, Math.min(RATES.length - 1, (i < 0 ? RATES.indexOf(1) : i) + by))])
  }

  // The keys video players have taught everyone, unless you're typing: Space or K plays and
  // pauses, the arrows skip 5 seconds, J and L skip 10, and < and > change the speed.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // a control that already used the key (a menu button opening its menu) keeps it
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target as HTMLElement
      if (el.closest("input, textarea, select, [contenteditable], [role=combobox], [role=slider]")) return
      // arrows and letters already mean something in tabs, menus and dialogs, and Space on a
      // button that opens a menu opens the menu
      const inWidget = !!el.closest("[role=tablist], [role=menu], [role=listbox], [role=radiogroup], [role=dialog], [aria-haspopup]")
      if (e.code === "Space") {
        if (inWidget) return
        e.preventDefault()
        pb.toggle()
        return
      }
      if (inWidget) return
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
      const act: Record<string, () => void> = {
        k: pb.toggle,
        ArrowLeft: () => skip(-SKIP_SHORT),
        ArrowRight: () => skip(SKIP_SHORT),
        j: () => skip(-SKIP),
        l: () => skip(SKIP),
        "<": () => stepRate(-1),
        ">": () => stepRate(1),
      }
      if (!Object.hasOwn(act, key)) return
      e.preventDefault()
      act[key]()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pb, timeline])

  const patchScene = (id: string, patch: Parameters<typeof updateScene>[2]) => host.setBoard(updateScene(board, id, patch))
  const stale = board.scenes.filter((s) => voiceState(s.id).kind === "stale").length
  const editors = host.sharing?.people.length ?? 0

  const goBackToViewed = async () => {
    if (!viewing || !host.history || restoring) return
    setRestoring(true)
    try {
      await host.history.restore(viewing.id)
      toast.success(`The lesson is back at version ${viewing.number}.`, { description: "The versions after it are still in History, so you can undo this." })
      setViewing(null)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Couldn't go back to that version.")
    } finally {
      setRestoring(false)
    }
  }

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
            {repo ? (
              <a href={githubUrl(repo)} target="_blank" rel="noreferrer" className="font-mono hover:text-foreground hover:underline">
                {repo.name}@{repo.sha.slice(0, 7)}
              </a>
            ) : null}
            {repo ? " · " : ""}
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
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button size="sm" variant="outline" onClick={() => setSharing(true)} aria-label={editors > 1 ? `Share. ${editors} people can edit` : "Share"}>
                  {editors > 1 ? <Users /> : <Link2 />}
                  <span className="hidden sm:inline">Share</span>
                  {editors > 1 ? <span className="font-mono tabular-nums">{editors}</span> : null}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{host.sharing ? "Links to watch, or to edit together" : "A link anyone can watch"}</TooltipContent>
            </Tooltip>
            <ShareDialog open={sharing} onOpenChange={setSharing} shareUrl={host.shareUrl} sharing={host.sharing} />
          </>
        ) : null}
      </header>
      {banner}
      {viewing ? (
        <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-ember/40 bg-ember-soft/60 px-4 py-2 text-xs">
          <HistoryIcon className="size-3.5 shrink-0 text-ember" aria-hidden />
          <span className="min-w-0 flex-1 basis-56 text-muted-foreground">
            <span className="font-medium text-foreground">
              You're looking at version {viewing.number}
              {viewing.name ? `, “${viewing.name}”` : ""}
            </span>{" "}
            from {new Date(viewing.updated_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}. The lesson itself hasn't changed.
          </span>
          <span className="flex gap-1.5">
            <Button size="xs" onClick={goBackToViewed} disabled={restoring || !!host.locked}>
              {restoring ? <Loader2 className="animate-spin" /> : null} Go back to this version
            </Button>
            <Button size="xs" variant="outline" onClick={() => setViewing(null)}>
              <X /> Stop looking
            </Button>
          </span>
        </div>
      ) : null}
      {host.locked ? (
        <div role="status" className="flex items-center gap-2 border-b border-border bg-ember-soft/40 px-4 py-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 shrink-0 animate-spin text-ember motion-reduce:animate-none" aria-hidden /> <TextShimmer duration={2.4}>{host.locked}</TextShimmer>
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
                    voice={voiceState(scene.id)}
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
            {/* on a phone the scene strip below does previous and next, so the row has room to skip */}
            <TransportButton label="Previous scene" onClick={() => step(-1)} className="max-sm:hidden">
              <SkipBack />
            </TransportButton>
            <TransportButton label={`Back ${SKIP} seconds`} keys="J" onClick={() => skip(-SKIP)}>
              <Rewind />
            </TransportButton>
            <Button size="icon-lg" className="rounded-full" onClick={pb.toggle} aria-label={pb.playing ? "Pause" : "Play"}>
              {pb.playing ? <Pause className="fill-current" /> : <Play className="ml-0.5 fill-current" />}
            </Button>
            <TransportButton label={`Forward ${SKIP} seconds`} keys="L" onClick={() => skip(SKIP)}>
              <FastForward />
            </TransportButton>
            <TransportButton label="Next scene" onClick={() => step(1)} className="max-sm:hidden">
              <SkipForward />
            </TransportButton>
            <span className="ml-1 font-mono text-xs whitespace-nowrap text-muted-foreground tabular-nums" aria-live="off">
              <span className="text-foreground">{clock(pb.time)}</span>
              <span className="max-sm:hidden"> / {clock(timeline.total)}</span>
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
              <SpeedMenu rate={pb.rate} onRate={pb.setRate} />
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
                    voice={voiceState(scene.id)}
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
            <TabsList className={cn("m-3 mb-0 grid w-auto", host.history ? "grid-cols-4" : "grid-cols-3")}>
              <TabsTrigger value="scene">{editable ? "Edit scene" : "Scene"}</TabsTrigger>
              <TabsTrigger value="script">Script</TabsTrigger>
              <TabsTrigger value="ai">Ask AI</TabsTrigger>
              {host.history ? <TabsTrigger value="history">History</TabsTrigger> : null}
            </TabsList>
            <ScrollArea className="min-h-0 flex-1">
              <TabsContent value="scene">
                {activeScene && editable ? (
                  <SceneInspector
                    scene={activeScene}
                    repo={repo}
                    sourcesLocked={host.sourcesLocked}
                    index={activeIndex}
                    count={board.scenes.length}
                    voice={voiceState(activeScene.id)}
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
                    <VoiceRow voice={voiceState(activeScene.id)} />
                    <p className="text-xs text-muted-foreground">
                      {viewing
                        ? `This is the scene as it was in version ${viewing.number}. Stop looking to edit the lesson as it is now.`
                        : host.locked
                          ? host.locked
                          : "You're watching. Only the person who made this lesson, and people they invite, can change it."}
                    </p>
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
                  aiEdit={host.editable && !viewing ? host.aiEdit : null}
                  unavailable={
                    viewing
                      ? "You're looking at an older version. Stop looking to ask for changes to the lesson as it is now."
                      : host.editable
                        ? host.aiUnavailable
                        : "Only the person who made this lesson, and people they invite, can ask for changes."
                  }
                  onJump={select}
                  sceneName={sceneName}
                />
              </TabsContent>
              {host.history ? (
                <TabsContent value="history">
                  <History host={host.history} viewing={viewing?.id ?? null} onView={setViewing} locked={host.locked} />
                </TabsContent>
              ) : null}
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
        voiceState={voiceState}
        onSeek={seek}
        onSelect={select}
      />
    </div>
  )
}

/** Seconds the skip buttons (and J and L) jump; the arrow keys make the smaller jump. */
const SKIP = 10
const SKIP_SHORT = 5

function TransportButton({ label, keys, onClick, className, children }: {
  label: string
  /** the keyboard shortcut, shown in the tooltip */
  keys?: string
  onClick: () => void
  className?: string
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" onClick={onClick} aria-label={label} className={className}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {label}
        {keys ? <kbd className="ml-1.5 font-mono opacity-70">{keys}</kbd> : null}
      </TooltipContent>
    </Tooltip>
  )
}

const rateLabel = (rate: number) => `${rate}×`

function SpeedMenu({ rate, onRate }: { rate: number; onRate: (rate: number) => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Playback speed, ${rate === 1 ? "normal" : `${rate} times`}`}
          className={cn("min-w-10 px-1.5 font-mono text-xs tabular-nums", rate !== 1 && "text-ember hover:text-ember")}
        >
          {rateLabel(rate)}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" side="top" className="w-36">
        <DropdownMenuLabel>Speed</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={String(rate)} onValueChange={(v) => onRate(Number(v))}>
          {RATES.map((r) => (
            <DropdownMenuRadioItem key={r} value={String(r)} className="font-mono text-xs tabular-nums">
              {rateLabel(r)}
              {r === 1 ? <span className="font-sans text-muted-foreground">Normal</span> : null}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
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
