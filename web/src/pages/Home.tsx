import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Check, FolderGit2, Loader2 } from "lucide-react"
import { motion } from "motion/react"
import { useId, useState } from "react"

import { Problem, QuietLoading, Shell, relativeTime } from "@/components/common/bits"
import { DemoPreview } from "@/components/common/DemoPreview"
import { AnimatedGroup } from "@/components/ui/animated-group"
import { BorderBeam } from "@/components/ui/border-beam"
import { TextShimmer } from "@/components/ui/text-shimmer"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api, ApiError, parseRepo, type Project } from "@/lib/api"
import { navigate } from "@/lib/router"
import { configQuery } from "./Lesson"
import { cn } from "@/lib/utils"

export const lessonsQuery = { queryKey: ["projects"], queryFn: api.list, gcTime: 30 * 60_000 }

const IDEAS = [
  { repo: "fastapi/fastapi", topic: "What happens when a request comes in?" },
  { repo: "pallets/flask", topic: "How does routing work?" },
  { repo: "karpathy/micrograd", topic: "How does backpropagation work in this code?" },
  { repo: "bamboo-fx/video-learn", topic: "How does a lesson get written?" },
]

export function Home() {
  const qc = useQueryClient()
  const [repo, setRepo] = useState("")
  const [topic, setTopic] = useState("")
  const [level, setLevel] = useState("intro")
  const [minutes, setMinutes] = useState("3")
  const [touched, setTouched] = useState(false)
  const repoId = useId()
  const topicId = useId()
  const repoErrorId = useId()

  const lessons = useQuery(lessonsQuery)
  const config = useQuery(configQuery)
  const aiOff = config.data?.ai === false
  // only allow a lesson once the server has said it can write one
  const aiReady = config.data?.ai === true
  const parsed = parseRepo(repo)
  const repoError = touched && repo.trim() && !parsed ? "That isn't a GitHub repository link. It should look like github.com/owner/repo." : null

  const create = useMutation({
    // send the link as pasted: the server reads the branch from it too (github.com/o/r/tree/dev)
    mutationFn: () => api.create({ topic: topic.trim(), repo: repo.trim(), notes: "", level, minutes: Number(minutes) }),
    onSuccess: (project: Project) => {
      sessionStorage.setItem(`writing:${project.id}`, "1")
      sessionStorage.setItem(`autovoice:${project.id}`, "1")
      qc.setQueryData(["project", project.id], { ...project, status: "writing" })
      // Claude reads the code and writes in the background while the editor opens and waits.
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

  const canSubmit = !!parsed && topic.trim().length >= 3 && !create.isPending && aiReady
  const submit = () => {
    setTouched(true)
    if (canSubmit) create.mutate()
  }

  return (
    <Shell wide>
      <section className="grid items-start gap-12 pt-8 pb-6 sm:pt-14 lg:grid-cols-[minmax(0,1.12fr)_minmax(0,1fr)] lg:gap-12 lg:pt-20">
        <AnimatedGroup className="flex min-w-0 flex-col">
          <h1 className="font-serif text-[42px] leading-[1.02] tracking-tight text-balance sm:text-[60px]">
            Turn any codebase into a lesson.
          </h1>
          <p className="mt-5 max-w-lg text-base text-pretty text-muted-foreground sm:text-[17px]">
            Paste a repo, ask a question, get a narrated walkthrough of the real code.
          </p>

          <form
            className="relative mt-9 rounded-[18px] border border-border bg-card p-2.5 sm:p-3"
            onSubmit={(e) => {
              e.preventDefault()
              submit()
            }}
            noValidate
          >
            {canSubmit || create.isPending ? <BorderBeam duration={create.isPending ? 3 : 9} /> : null}
            <div className="flex items-center gap-2 rounded-[12px] border border-border bg-background/60 px-3 focus-within:border-ember/50">
              <FolderGit2 className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <label htmlFor={repoId} className="sr-only">
                GitHub repository
              </label>
              <input
                id={repoId}
                value={repo}
                onChange={(e) => setRepo(e.target.value)}
                onBlur={() => setTouched(true)}
                placeholder="github.com/owner/repo"
                inputMode="url"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                aria-invalid={!!repoError}
                aria-describedby={repoError ? repoErrorId : undefined}
                className="h-11 min-w-0 flex-1 bg-transparent font-mono text-sm outline-none placeholder:text-muted-foreground/70"
              />
              {parsed ? (
                <Check className="size-4 shrink-0 text-ok" aria-label={`Repository ${parsed}`} />
              ) : null}
            </div>
            {repoError ? (
              <p id={repoErrorId} className="px-2 pt-1.5 text-xs text-destructive">
                {repoError}
              </p>
            ) : null}

            <label htmlFor={topicId} className="sr-only">
              What do you want to understand?
            </label>
            <Textarea
              id={topicId}
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
              placeholder="How does login work?"
              maxLength={200}
              rows={2}
              className="mt-1 min-h-[68px] resize-none border-0 bg-transparent px-3 py-3 text-base shadow-none focus-visible:ring-0 dark:bg-transparent sm:text-lg"
            />

            <div className="flex flex-col gap-2.5 border-t border-border px-1 pt-2.5 sm:flex-row sm:items-center">
              <div className="flex flex-wrap items-center gap-2">
                <ToggleGroup type="single" value={level} onValueChange={(v) => v && setLevel(v)} variant="outline" size="sm" spacing={0} aria-label="Level">
                  <ToggleGroupItem value="intro">New to it</ToggleGroupItem>
                  <ToggleGroupItem value="intermediate">Some</ToggleGroupItem>
                  <ToggleGroupItem value="advanced">Expert</ToggleGroupItem>
                </ToggleGroup>
                <ToggleGroup type="single" value={minutes} onValueChange={(v) => v && setMinutes(v)} variant="outline" size="sm" spacing={0} aria-label="Length in minutes">
                  {["2", "3", "5"].map((m) => (
                    <ToggleGroupItem key={m} value={m} aria-label={`${m} minutes`}>
                      {m} min
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </div>
              <Button type="submit" disabled={!canSubmit} className="h-9 w-full px-4 sm:ml-auto sm:w-auto">
                {create.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
                Make lesson <ArrowRight aria-hidden />
              </Button>
            </div>
          </form>

          <div className="mt-3 flex flex-col gap-3">
            {config.isError ? (
              <p role="status" className="px-1 text-sm text-muted-foreground">
                Couldn't reach the server.{" "}
                <button type="button" className="font-medium text-ember underline-offset-4 hover:underline" onClick={() => config.refetch()}>
                  Try again
                </button>
              </p>
            ) : null}
            {aiOff ? (
              <p role="status" className="px-1 text-sm text-muted-foreground">
                AI writing isn't set up here.{" "}
                <button type="button" className="font-medium text-ember underline-offset-4 hover:underline" onClick={() => navigate("/demo")}>
                  Watch the example
                </button>
              </p>
            ) : null}
            {create.isError ? (
              <Problem title="The lesson couldn't be started">
                {create.error instanceof ApiError ? create.error.message : "Something went wrong. Try again."}
              </Problem>
            ) : (
              <div className="px-1">
                <p className="mb-1.5 text-xs text-muted-foreground">Or try one:</p>
                <ul className="flex flex-col">
                  {IDEAS.map((idea) => (
                    <li key={idea.repo}>
                      <button
                        type="button"
                        onClick={() => {
                          setRepo(`github.com/${idea.repo}`)
                          setTopic(idea.topic)
                        }}
                        className="group flex w-full flex-col rounded-md py-1.5 text-left text-sm transition-colors sm:flex-row sm:items-baseline sm:gap-3 sm:py-1"
                      >
                        <span className="shrink-0 truncate font-mono text-xs text-muted-foreground group-hover:text-ember sm:w-[170px]">{idea.repo}</span>
                        <span className="min-w-0 truncate text-foreground/80 group-hover:text-foreground">{idea.topic}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </AnimatedGroup>

        <motion.div
          className="min-w-0 lg:sticky lg:top-8"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.25, ease: [0.22, 1, 0.36, 1] }}
        >
          <DemoPreview />
        </motion.div>
      </section>

      <section className="mt-12 border-t border-border pt-10 sm:mt-20" aria-labelledby="your-lessons">
        <div className="mb-5 flex items-baseline justify-between gap-4">
          <h2 id="your-lessons" className="font-serif text-3xl">
            Your lessons
          </h2>
        </div>
        {lessons.isPending ? (
          <QuietLoading label="Loading your lessons" />
        ) : lessons.isError ? (
          <Problem title="Your lessons didn't load" action={<Button size="sm" variant="outline" onClick={() => lessons.refetch()}>Try again</Button>}>
            {lessons.error instanceof ApiError ? lessons.error.message : "Something went wrong."}
          </Problem>
        ) : lessons.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">None yet.</p>
        ) : (
          <AnimatedGroup as="ul" className="divide-y divide-border border-y border-border">
            {lessons.data.map((p) => (
              <a
                key={p.id}
                href={`/l/${p.id}`}
                onClick={(e) => {
                  e.preventDefault()
                  navigate(`/l/${p.id}`)
                }}
                className="group -mx-3 flex flex-col gap-1 rounded-lg px-3 py-4 transition-colors hover:bg-card sm:flex-row sm:items-center sm:gap-6"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-serif text-xl leading-tight group-hover:text-foreground">{p.title}</span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {p.repo ? <span className="font-mono">{p.repo}</span> : p.topic}
                    {p.scenes ? ` · ${p.scenes} scenes` : ""}
                    {p.shared ? " · shared with you" : ""}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-4 text-xs text-muted-foreground">
                  <StatusPill status={p.status} />
                  <span className="w-16 text-right tabular-nums">{relativeTime(p.updated_at)}</span>
                  <ArrowRight className="hidden size-4 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100 sm:block" aria-hidden />
                </span>
              </a>
            ))}
          </AnimatedGroup>
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
  if (status === "writing") return <TextShimmer className="text-[11px] font-medium">Writing…</TextShimmer>
  return <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", cls)}>{label}</span>
}
