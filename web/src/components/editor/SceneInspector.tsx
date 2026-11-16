/** Edit one scene by hand: layout, text on screen, when each item appears, narration. */
import { ArrowDown, ArrowUp, Copy, ExternalLink, Loader2, Mic, Plus, Trash2, X } from "lucide-react"
import { useId } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { githubUrl, type Item, type Layout, type RepoRef, type Scene } from "@/lib/api"
import { LAYOUT_LABELS } from "@/lib/edit"
import { sentenceSpans, wordCount } from "@/lib/timing"
import { cn } from "@/lib/utils"

import type { VoiceState } from "./types"

interface Props {
  scene: Scene
  /** set when the lesson teaches a repository: code comes from the file, not from typing */
  repo?: RepoRef
  index: number
  count: number
  voice: VoiceState
  onChange: (patch: Partial<Scene>) => void
  onVoice?: () => void
  onMove: (by: -1 | 1) => void
  onDuplicate: () => void
  onDelete: () => void
}

export function SceneInspector({ scene, repo, index, count, voice, onChange, onVoice, onMove, onDuplicate, onDelete }: Props) {
  const ids = { layout: useId(), heading: useId(), sub: useId(), code: useId(), narration: useId(), path: useId() }
  const src = scene.source
  const setSource = (patch: Partial<Scene["source"]>) => onChange({ source: { ...src, ...patch } })
  const spans = sentenceSpans(scene.narration)
  const sentenceLabels = spans.map(([a, b], i) => `${i + 1}. ${scene.narration.slice(a, b).split(/\s+/).slice(0, 6).join(" ")}…`)
  const words = wordCount(scene.narration)
  const hasItems = scene.layout !== "title"

  const setItem = (i: number, patch: Partial<Item>) => onChange({ items: scene.items.map((it, k) => (k === i ? { ...it, ...patch } : it)) })

  return (
    <div className="flex flex-col gap-5 p-4">
      <div className="flex items-center justify-between">
        <p className="font-mono text-xs text-muted-foreground">
          Scene {String(index + 1).padStart(2, "0")} of {String(count).padStart(2, "0")}
        </p>
        <div className="flex gap-0.5">
          <Button variant="ghost" size="icon-sm" onClick={() => onMove(-1)} disabled={index === 0} aria-label="Move scene earlier">
            <ArrowUp />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => onMove(1)} disabled={index === count - 1} aria-label="Move scene later">
            <ArrowDown />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={onDuplicate} aria-label="Duplicate scene">
            <Copy />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={onDelete} disabled={count <= 1} aria-label="Delete scene" className="hover:text-destructive">
            <Trash2 />
          </Button>
        </div>
      </div>

      <Field label="Layout" htmlFor={ids.layout}>
        <Select value={scene.layout} onValueChange={(v) => onChange({ layout: v as Layout })}>
          <SelectTrigger id={ids.layout} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(LAYOUT_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Heading" htmlFor={ids.heading}>
        <Input id={ids.heading} value={scene.heading} maxLength={80} onChange={(e) => onChange({ heading: e.target.value })} />
      </Field>
      <Field label="Subheading" htmlFor={ids.sub} hint="Optional">
        <Input id={ids.sub} value={scene.subheading} maxLength={120} onChange={(e) => onChange({ subheading: e.target.value })} />
      </Field>

      {repo ? (
        <fieldset className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between">
            <label htmlFor={ids.path} className="text-xs font-medium text-muted-foreground">
              Source in the repo
            </label>
            {src.path ? (
              <a
                href={githubUrl(repo, src.path, src.start_line, src.end_line)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11px] text-ember hover:underline"
              >
                Open on GitHub <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : null}
          </div>
          <Input id={ids.path} value={src.path} placeholder="path/to/file.py" className="h-8 font-mono text-xs" onChange={(e) => setSource({ path: e.target.value.trim() })} />
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>Lines</span>
            <Input type="number" min={0} value={src.start_line || ""} aria-label="First line" className="h-7 w-20 text-xs" onChange={(e) => setSource({ start_line: Number(e.target.value) || 0 })} />
            <span>to</span>
            <Input type="number" min={0} value={src.end_line || ""} aria-label="Last line" className="h-7 w-20 text-xs" onChange={(e) => setSource({ end_line: Number(e.target.value) || 0 })} />
          </div>
          {scene.layout === "code" ? (
            <p className="text-[11px] text-muted-foreground">The code shown is read from this file when you save, so it's always exact (14 lines at most).</p>
          ) : null}
        </fieldset>
      ) : scene.layout === "code" ? (
        <Field label="Code" htmlFor={ids.code} hint="Up to 14 lines">
          <Textarea id={ids.code} value={scene.code} rows={6} className="font-mono text-xs" onChange={(e) => onChange({ code: e.target.value })} />
        </Field>
      ) : null}

      {hasItems ? (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-xs font-medium text-muted-foreground">On screen</legend>
          {scene.items.map((item, i) => (
            <div key={i} className="rounded-xl border border-border bg-panel-raised/60 p-2.5">
              <div className="flex gap-1.5">
                <Input value={item.text} maxLength={90} aria-label={`Item ${i + 1}`} onChange={(e) => setItem(i, { text: e.target.value })} className="h-8" />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove item ${i + 1}`}
                  onClick={() => onChange({ items: scene.items.filter((_, k) => k !== i) })}
                >
                  <X />
                </Button>
              </div>
              <Input
                value={item.detail}
                maxLength={160}
                placeholder="Detail (optional)"
                aria-label={`Item ${i + 1} detail`}
                onChange={(e) => setItem(i, { detail: e.target.value })}
                className="mt-1.5 h-8 text-xs"
              />
              {scene.layout === "code" ? (
                <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="shrink-0">Highlights line</span>
                  <Input
                    type="number"
                    min={0}
                    value={item.line || ""}
                    placeholder="none"
                    aria-label={`Line item ${i + 1} highlights`}
                    className="h-7 w-20 text-xs"
                    onChange={(e) => setItem(i, { line: Number(e.target.value) || 0 })}
                  />
                </div>
              ) : null}
              <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="shrink-0">Appears on</span>
                <Select value={String(Math.min(item.at, spans.length - 1))} onValueChange={(v) => setItem(i, { at: Number(v) })}>
                  <SelectTrigger size="sm" className="h-7 min-w-0 flex-1 text-[11px]" aria-label={`When item ${i + 1} appears`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {sentenceLabels.map((label, k) => (
                      <SelectItem key={k} value={String(k)} className="text-xs">
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ))}
          {scene.items.length < 5 ? (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => onChange({ items: [...scene.items, { text: "New point", detail: "", at: Math.max(0, spans.length - 1), line: 0 }] })}
            >
              <Plus /> Add item
            </Button>
          ) : null}
        </fieldset>
      ) : null}

      <Field label="Narration" htmlFor={ids.narration} hint={`${words} words · about ${Math.round(words / 2.5)} s`}>
        <Textarea
          id={ids.narration}
          value={scene.narration}
          rows={6}
          maxLength={900}
          className="text-sm leading-relaxed"
          onChange={(e) => onChange({ narration: e.target.value })}
        />
      </Field>
      <VoiceRow voice={voice} onVoice={onVoice} />
    </div>
  )
}

export function VoiceRow({ voice, onVoice }: { voice: VoiceState; onVoice?: () => void }) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border px-3 py-2.5 text-xs",
        voice.kind === "failed" ? "border-destructive/30 bg-destructive/8" : "border-border bg-panel-raised/50",
      )}
      role="status"
      aria-live="polite"
    >
      <Mic className={cn("size-4 shrink-0", voice.kind === "voiced" ? "text-ok" : "text-muted-foreground")} aria-hidden />
      <span className="min-w-0 flex-1 text-muted-foreground">
        {voice.kind === "voiced" && "Voiced. It plays with this narration."}
        {voice.kind === "stale" && "Not voiced yet. It plays silently, with captions."}
        {voice.kind === "voicing" && "Voicing this scene…"}
        {voice.kind === "failed" && <span className="text-foreground">{voice.message}</span>}
      </span>
      {onVoice && voice.kind !== "voiced" ? (
        <Button size="xs" variant={voice.kind === "failed" ? "outline" : "secondary"} onClick={onVoice} disabled={voice.kind === "voicing"}>
          {voice.kind === "voicing" ? <Loader2 className="animate-spin" /> : null}
          {voice.kind === "failed" ? "Try again" : "Voice it"}
        </Button>
      ) : null}
    </div>
  )
}

function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
          {label}
        </label>
        {hint ? <span className="text-[11px] text-muted-foreground/80 tabular-nums">{hint}</span> : null}
      </div>
      {children}
    </div>
  )
}
