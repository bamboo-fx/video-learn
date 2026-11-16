import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, BookOpen, ChevronDown, Clock3, Loader2, NotebookPen, Sparkles } from "lucide-react"
import { useId, useState } from "react"

import { Problem, QuietLoading, Shell, relativeTime } from "@/components/common/bits"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api, ApiError, type Project } from "@/lib/api"
import { navigate } from "@/lib/router"
import { configQuery } from "./Lesson"
import { cn } from "@/lib/utils"

export const lessonsQuery = { queryKey: ["projects"], queryFn: api.list, gcTime: 30 * 60_000 }

const IDEAS = ["How does backpropagation work?", "What is a Fourier transform, intuitively?", "Why do vaccines need boosters?", "Big-O notation, with examples"]

export function Home() {
  const qc = useQueryClient()
  const [topic, setTopic] = useState("")
  const [notes, setNotes] = useState("")
  const [showNotes, setShowNotes] = useState(false)
  const [level, setLevel] = useState("intro")
  const [minutes, setMinutes] = useState("3")
  const topicId = useId()
  const notesId = useId()

  const lessons = useQuery(lessonsQuery)
  const config = useQuery(configQuery)
  const aiOff = config.data?.ai === false

  const create = useMutation({
    mutationFn: () => api.create({ topic: topic.trim(), notes: notes.trim(), level, minutes: Number(minutes) }),
    onSuccess: (project: Project) => {
      sessionStorage.setItem(`writing:${project.id}`, "1")
      sessionStorage.setItem(`autovoice:${project.id}`, "1")
      qc.setQueryData(["project", project.id], { ...project, status: "writing" })
      // Claude writes it in the background while the editor opens and waits.
      api.write(project.id).then(
        (p) => qc.setQueryData(["project", p.id], p),
        () => {
          // the lesson page stops waiting and shows why (the server saved the reason)
          sessionStorage.removeItem(`writing:${project.id}`)
          qc.invalidateQueries({ queryKey: ["project", project.id] })
        },
      )
      qc.invalidateQueries({ queryKey: ["projects"] })
      navigate(`/l/${project.id}`)
    },
  })

  const canSubmit = topic.trim().length >= 3 && !create.isPending && !aiOff

  return (
    <Shell wide>
      <section className="mx-auto max-w-3xl pt-10 pb-12 text-center sm:pt-16">
        <p className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1 text-xs text-muted-foreground">
          <Sparkles className="size-3.5 text-ember" aria-hidden /> Written by Claude, voiced by ElevenLabs, edited by you
        </p>
        <h1 className="font-serif text-[44px] leading-[1.02] tracking-tight text-balance sm:text-[64px]">
          Learn anything as a short lesson you can <em className="text-ember">watch and edit</em>.
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-base text-pretty text-muted-foreground sm:text-lg">
          Type a topic, paste your notes if you have them, and get a narrated, captioned lesson in about a minute. Then fix
          any scene by hand, or ask for a change.
        </p>
      </section>

      <form
        className="mx-auto max-w-3xl rounded-[22px] border border-border bg-card p-3 shadow-[0_30px_80px_-40px_oklch(0_0_0/0.8)] sm:p-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) create.mutate()
        }}
      >
        <label htmlFor={topicId} className="sr-only">
          What do you want to learn?
        </label>
        <Textarea
          id={topicId}
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              if (canSubmit) create.mutate()
            }
          }}
          placeholder="What do you want to learn?"
          maxLength={200}
          rows={2}
          className="min-h-[76px] resize-none border-0 bg-transparent px-3 py-3 text-lg shadow-none focus-visible:ring-0 dark:bg-transparent sm:text-xl"
        />

        {showNotes ? (
          <div className="px-3 pb-2">
            <label htmlFor={notesId} className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <NotebookPen className="size-3.5" aria-hidden /> Your notes. The lesson sticks to what they say.
            </label>
            <Textarea
              id={notesId}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Paste lecture notes, a textbook section, or slide text…"
              maxLength={12000}
              rows={6}
              className="text-sm"
            />
            <p className="mt-1 text-right text-[11px] text-muted-foreground tabular-nums">{notes.length.toLocaleString()} / 12,000</p>
          </div>
        ) : null}

        <div className="flex flex-col gap-3 border-t border-border px-1 pt-3 md:flex-row md:items-center">
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowNotes((v) => !v)} aria-expanded={showNotes} className="justify-start">
            <NotebookPen aria-hidden /> {showNotes ? "Hide notes" : "Add your notes"}
            <ChevronDown className={cn("transition-transform", showNotes && "rotate-180")} aria-hidden />
          </Button>
          <div className="flex flex-wrap items-center gap-2 md:ml-auto">
            <ToggleGroup
              type="single"
              value={level}
              onValueChange={(v) => v && setLevel(v)}
              variant="outline"
              size="sm"
              spacing={0}
              aria-label="Level"
            >
              <ToggleGroupItem value="intro">Intro</ToggleGroupItem>
              <ToggleGroupItem value="intermediate">Middle</ToggleGroupItem>
              <ToggleGroupItem value="advanced">Advanced</ToggleGroupItem>
            </ToggleGroup>
            <ToggleGroup
              type="single"
              value={minutes}
              onValueChange={(v) => v && setMinutes(v)}
              variant="outline"
              size="sm"
              spacing={0}
              aria-label="Length in minutes"
            >
              {["2", "3", "5"].map((m) => (
                <ToggleGroupItem key={m} value={m} aria-label={`${m} minutes`}>
                  {m} min
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <Button type="submit" disabled={!canSubmit} className="h-9 w-full px-4 sm:ml-auto sm:w-auto md:ml-1">
              {create.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Make the lesson <ArrowRight aria-hidden />
            </Button>
          </div>
        </div>
      </form>

      <div className="mx-auto mt-4 max-w-3xl">
        {aiOff ? (
          <div role="status" className="mb-3 rounded-xl border border-border bg-card/60 px-4 py-3 text-center text-sm text-muted-foreground">
            AI writing isn't set up on this server yet, so new lessons can't be made right now.{" "}
            <button type="button" className="font-medium text-ember underline-offset-4 hover:underline" onClick={() => navigate("/demo")}>
              Watch the example
            </button>{" "}
            instead.
          </div>
        ) : null}
        {create.isError ? (
          <Problem title="The lesson couldn't be started">
            {create.error instanceof ApiError ? create.error.message : "Something went wrong. Try again."}
          </Problem>
        ) : (
          <div className="flex flex-wrap justify-center gap-2">
            {IDEAS.map((idea) => (
              <button
                key={idea}
                type="button"
                onClick={() => setTopic(idea)}
                className="rounded-full border border-border bg-card/40 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-ember/40 hover:text-foreground"
              >
                {idea}
              </button>
            ))}
          </div>
        )}
      </div>

      <section className="mx-auto mt-20 max-w-5xl" aria-labelledby="your-lessons">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 id="your-lessons" className="font-serif text-3xl">
            Your lessons
          </h2>
          <span className="text-xs text-muted-foreground">Kept in this browser</span>
        </div>
        {lessons.isPending ? (
          <QuietLoading label="Loading your lessons" />
        ) : lessons.isError ? (
          <Problem title="Your lessons didn't load" action={<Button size="sm" variant="outline" onClick={() => lessons.refetch()}>Try again</Button>}>
            {lessons.error instanceof ApiError ? lessons.error.message : "Something went wrong."}
          </Problem>
        ) : lessons.data.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border px-6 py-12 text-center text-sm text-muted-foreground">
            <BookOpen className="mx-auto mb-3 size-5" aria-hidden />
            Nothing yet. Your first lesson will show up here.
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {lessons.data.map((p) => (
              <li key={p.id}>
                <a
                  href={`/l/${p.id}`}
                  onClick={(e) => {
                    e.preventDefault()
                    navigate(`/l/${p.id}`)
                  }}
                  className="group flex h-full flex-col rounded-2xl border border-border bg-card p-4 transition-colors hover:border-ember/40 hover:bg-panel-raised"
                >
                  <div className="mb-6 flex items-center justify-between text-xs text-muted-foreground">
                    <StatusPill status={p.status} />
                    <span className="inline-flex items-center gap-1">
                      <Clock3 className="size-3" aria-hidden /> {relativeTime(p.updated_at)}
                    </span>
                  </div>
                  <p className="font-serif text-2xl leading-tight text-balance">{p.title}</p>
                  <p className="mt-auto pt-4 text-xs text-muted-foreground">{p.scenes ? `${p.scenes} scenes` : p.topic}</p>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Shell>
  )
}

export function StatusPill({ status }: { status: Project["status"] }) {
  const map = {
    new: ["Not written", "bg-muted text-muted-foreground"],
    writing: ["Writing…", "bg-ember-soft text-ember"],
    ready: ["Ready", "bg-ok/15 text-ok"],
    failed: ["Didn't finish", "bg-destructive/15 text-destructive"],
  } as const
  const [label, cls] = map[status] ?? map.new
  return <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", cls)}>{label}</span>
}
