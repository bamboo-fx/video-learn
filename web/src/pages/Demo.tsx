/** An example lesson that needs no server: the storyboard ships with the app. Edits stay
 * in this tab. It's what a tester opens first, and it works even if the APIs are down. */
import { ArrowRight } from "lucide-react"
import { useState } from "react"

import { Editor } from "@/components/editor/Editor"
import type { EditorHost } from "@/components/editor/types"
import { Button } from "@/components/ui/button"
import type { Storyboard, Voice } from "@/lib/api"
import { navigate } from "@/lib/router"
import demo from "../../../shared/demo-lesson.json"
import demoVoices from "../../../shared/demo-voices.json"

export function Demo() {
  const [board, setBoard] = useState<Storyboard>(demo.storyboard as Storyboard)
  const voices = demoVoices as Record<string, Voice>

  const host: EditorHost = {
    board,
    voices,
    editable: true,
    setBoard,
    voiceState: (id) => {
      const scene = board.scenes.find((s) => s.id === id)
      return scene && voices[id]?.text === scene.narration ? { kind: "voiced" } : { kind: "stale" }
    },
    repo: { name: demo.repo, sha: demo.sha },
    aiEdit: null,
    aiUnavailable: "AI edits are off in the example. Make your own lesson to ask for changes.",
  }

  return (
    <Editor
      host={host}
      banner={
        <div className="flex items-center gap-3 border-b border-border bg-ember-soft/50 px-4 py-2 text-xs">
          <span className="min-w-0 flex-1 text-muted-foreground">
            <span className="font-medium text-foreground">An example lesson</span> about this app's own code. Changes here aren't saved.
          </span>
          <Button size="xs" onClick={() => navigate("/")}>
            Make your own <ArrowRight />
          </Button>
        </div>
      }
    />
  )
}
