/**
 * What Claude is doing while it writes a repository lesson, shown like a coding agent's trace:
 * one row per tool call (look in a folder, read a file, search), newest at the bottom.
 * Layout after Vercel AI Elements' Chain of Thought (icon rail joined by a line, label, detail).
 *
 * The server sends plain lines ("Reading app/main.py"); the kind is read from the first words,
 * so the backend stays as it is. Unknown lines still show, with a dot.
 */
import { Check, Dot, Download, FileText, FolderOpen, Search, ShieldCheck, type LucideIcon } from "lucide-react"
import { useEffect, useState } from "react"

import { TextShimmer } from "@/components/ui/text-shimmer"
import { cn } from "@/lib/utils"

type Step = { icon: LucideIcon; verb: string; target?: string; kind: "file" | "folder" | "search" | "other" }

const RULES: [RegExp, (m: RegExpMatchArray) => Step][] = [
  [/^Downloading (.+)$/, (m) => ({ icon: Download, verb: "Downloading", target: m[1], kind: "other" })],
  [/^Read (\d+) files from (.+)$/, (m) => ({ icon: Check, verb: `Got ${m[1]} files from`, target: m[2], kind: "other" })],
  [/^Looking in (.+)$/, (m) => ({ icon: FolderOpen, verb: "Listed", target: m[1], kind: "folder" })],
  [/^Reading (.+)$/, (m) => ({ icon: FileText, verb: "Read", target: m[1], kind: "file" })],
  [/^Searching for (.+)$/, (m) => ({ icon: Search, verb: "Searched", target: m[1].replace(/^'(.*)'$/, "$1"), kind: "search" })],
  [/^Checking/, () => ({ icon: ShieldCheck, verb: "Checking every citation against the code", kind: "other" })],
]

function parseStep(line: string): Step {
  for (const [re, make] of RULES) {
    const m = line.match(re)
    if (m) return make(m)
  }
  return { icon: Dot, verb: line, kind: "other" }
}

function useElapsed() {
  const [s, setS] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setS((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

export function AgentTrace({ lines, className }: { lines: string[]; className?: string }) {
  const steps = lines.map(parseStep)
  const elapsed = useElapsed()
  // Running totals for the whole write: the server keeps a long but finite list of lines, so
  // remember what this page has seen and the counts never go down.
  const [seen, setSeen] = useState({ files: new Set<string>(), searches: new Set<string>(), key: "" })
  const key = lines.join("\n")
  if (seen.key !== key) {
    const files = new Set(seen.files)
    const searches = new Set(seen.searches)
    for (const s of steps) {
      if (s.kind === "file" && s.target) files.add(s.target)
      if (s.kind === "search" && s.target) searches.add(s.target)
    }
    setSeen({ files, searches, key })
  }
  const files = seen.files.size
  const searches = seen.searches.size
  const summary = [files && `${files} ${files === 1 ? "file" : "files"}`, searches && `${searches} ${searches === 1 ? "search" : "searches"}`]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className={cn("rounded-[14px] border border-border bg-card", className)}>
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5 text-xs text-muted-foreground">
        <span className="relative flex size-2" aria-hidden>
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-ember opacity-60 motion-reduce:hidden" />
          <span className="relative inline-flex size-2 rounded-full bg-ember" />
        </span>
        <span className="text-foreground">Working</span>
        {summary ? <span>· {summary}</span> : null}
        <span className="ml-auto font-mono tabular-nums">{elapsed}</span>
      </div>

      {/* Newest at the bottom; older steps slide up and fade out under the top edge. */}
      <div
        className={cn(
          "flex max-h-[340px] flex-col justify-end overflow-hidden px-4 py-3",
          steps.length > 7 && "[mask-image:linear-gradient(to_bottom,transparent,black_72px)]",
        )}
      >
        <ol aria-live="polite" className="flex flex-col">
          {steps.length === 0 ? (
            <Row icon={Dot} active last>
              <TextShimmer>Starting…</TextShimmer>
            </Row>
          ) : (
            steps.map((s, i) => {
              const active = i === steps.length - 1
              return (
                <Row key={`${i}-${lines[i]}`} icon={s.icon} active={active} last={active}>
                  <Label step={s} active={active} />
                </Row>
              )
            })
          )}
        </ol>
      </div>
    </div>
  )
}

function Row({ icon: Icon, active, last, children }: { icon: LucideIcon; active: boolean; last: boolean; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 text-sm animate-in duration-300 fade-in-0 slide-in-from-bottom-1">
      <div className="relative flex flex-col items-center">
        <span
          className={cn(
            "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md",
            active ? "bg-ember-soft text-ember" : "text-muted-foreground",
          )}
        >
          <Icon className="size-3.5" aria-hidden />
        </span>
        {!last ? <span className="w-px flex-1 bg-border" aria-hidden /> : null}
      </div>
      <div className={cn("min-w-0 flex-1", last ? "pb-0.5" : "pb-2.5")}>{children}</div>
    </li>
  )
}

function Label({ step, active }: { step: Step; active: boolean }) {
  const verb = active ? <TextShimmer duration={1.8}>{step.verb}</TextShimmer> : <span>{step.verb}</span>
  return (
    <div className={cn("flex min-w-0 items-baseline gap-2 leading-6", active ? "text-foreground" : "text-muted-foreground")}>
      <span className="shrink-0">{verb}</span>
      {step.target ? (
        <span
          className={cn(
            "min-w-0 truncate font-mono text-[12px]",
            step.kind === "search" && "rounded bg-secondary px-1.5 py-px",
            active ? "text-foreground" : "text-muted-foreground/90",
          )}
        >
          {step.target}
        </span>
      ) : null}
    </div>
  )
}
