/** How to make lessons from inside Claude: the /lesson skill for Claude Code (your own code,
 * private repositories too) and the connector for the Claude app (public repositories). */
import { Check, Copy, ShieldCheck, Terminal, Unplug } from "lucide-react"
import { useState, type ReactNode } from "react"
import { toast } from "sonner"

import { Shell } from "@/components/common/bits"
import { Button } from "@/components/ui/button"

const INSTALL = `git clone --depth 1 https://github.com/bamboo-fx/video-learn.git /tmp/video-learn
mkdir -p ~/.claude/skills && cp -R /tmp/video-learn/skill/lesson ~/.claude/skills/lesson`

function CopyBlock({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false)
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-xl border border-border bg-background/70 p-4 pr-12 font-mono text-[12.5px] leading-relaxed">{text}</pre>
      <Button
        variant="ghost"
        size="icon-sm"
        className="absolute top-2 right-2"
        aria-label={`Copy ${label}`}
        onClick={() =>
          navigator.clipboard.writeText(text).then(
            () => {
              setDone(true)
              setTimeout(() => setDone(false), 1500)
            },
            () => toast.error("Your browser didn't allow copying. Select the text and copy it by hand."),
          )
        }
      >
        {done ? <Check className="text-ok" /> : <Copy />}
      </Button>
    </div>
  )
}

function Card({ icon, title, kicker, children }: { icon: ReactNode; title: string; kicker: string; children: ReactNode }) {
  return (
    <section className="rounded-[22px] border border-border bg-card p-5 sm:p-6">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-xl bg-ember-soft text-ember">{icon}</span>
        <div>
          <h2 className="font-serif text-2xl leading-tight">{title}</h2>
          <p className="text-xs text-muted-foreground">{kicker}</p>
        </div>
      </div>
      <div className="flex flex-col gap-4 text-sm leading-relaxed text-muted-foreground">{children}</div>
    </section>
  )
}

export function Connect() {
  const mcpUrl = `${window.location.origin}/mcp`
  return (
    <Shell>
      <div className="pt-8 pb-10 sm:pt-12">
        <h1 className="font-serif text-[40px] leading-[1.05] tracking-tight sm:text-[52px]">Use it from Claude</h1>
        <p className="mt-3 max-w-xl text-muted-foreground">
          Make a lesson without leaving your coding agent or your chat. Your own Claude reads the code, so it's free for us to
          run, and the finished lesson opens here to watch, voice and edit.
        </p>
      </div>

      <div className="flex flex-col gap-5">
        <Card icon={<Terminal className="size-4" />} title="Claude Code" kicker="Your own code, private repositories too">
          <p>Install the /lesson skill once:</p>
          <CopyBlock text={INSTALL} label="install commands" />
          <p>
            Then, in Claude Code inside any repository, type{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">/lesson how does login work?</code>, or{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">/lesson diff</code> to explain what changed on your
            branch.
          </p>
          <ul className="flex flex-col gap-1.5">
            <Safe>Only the lesson and the lines it shows are uploaded, never your repository.</Safe>
            <Safe>It never reads .env files, keys or credentials, and refuses lines that look like secrets.</Safe>
            <Safe>It shows you exactly what would be uploaded, and waits for your yes.</Safe>
            <Safe>
              The helper is one short Python file with no dependencies:{" "}
              <a className="text-ember underline-offset-4 hover:underline" href="https://github.com/bamboo-fx/video-learn/blob/main/skill/lesson/lesson.py" target="_blank" rel="noreferrer">
                read it before you install
              </a>
              .
            </Safe>
          </ul>
        </Card>

        <Card icon={<Unplug className="size-4" />} title="The Claude app" kicker="Public GitHub repositories">
          <p>
            Add Video Learn as a custom connector (in Claude: Settings, then Connectors, then Add custom connector), if your Claude
            plan has custom connectors. Paste this address:
          </p>
          <CopyBlock text={mcpUrl} label="connector address" />
          <p>
            Then ask Claude something like{" "}
            <span className="text-foreground">“Use Video Learn to make a lesson on github.com/pallets/flask: how does routing work?”</span>
          </p>
          <ul className="flex flex-col gap-1.5">
            <Safe>Public repositories only. It never asks for your GitHub account.</Safe>
            <Safe>Its tools only read the repository and save the finished lesson.</Safe>
            <Safe>
              Repository text is treated as data. A README can contain instructions aimed at whoever reads it; Claude is told not to
              follow them. If you have other connectors on, like email, keep an eye on what Claude asks to do.
            </Safe>
          </ul>
        </Card>
      </div>

      <p className="mt-8 text-xs text-muted-foreground">
        Either way you get a link. The first browser that opens it becomes the lesson's owner. It plays with captions straight away;
        click Voice for narration.
      </p>
    </Shell>
  )
}

function Safe({ children }: { children: ReactNode }) {
  return (
    <li className="flex gap-2">
      <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
      <span>{children}</span>
    </li>
  )
}
