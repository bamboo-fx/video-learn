import type { EditResult, RepoRef, Storyboard, Voice } from "@/lib/api"

/** Where a scene's narration stands with ElevenLabs. */
export type VoiceState =
  | { kind: "voiced" }
  | { kind: "stale" } // never voiced, or the narration changed since
  | { kind: "voicing" }
  | { kind: "failed"; message: string }

/** Everything the editor needs from whoever owns the data (the API, or the demo). */
export interface EditorHost {
  board: Storyboard
  voices: Record<string, Voice>
  editable: boolean
  setBoard: (next: Storyboard) => void
  /** undefined = this lesson isn't saved anywhere (the example) */
  saveState?: "saved" | "saving" | "unsaved" | "error"
  saveError?: string
  voiceState: (sceneId: string) => VoiceState
  voiceScene?: (sceneId: string) => void
  voiceAll?: () => void
  /** null when AI editing isn't available here, with the reason */
  aiEdit: ((instruction: string, sceneId: string | null) => Promise<EditResult>) | null
  aiUnavailable?: string
  shareUrl?: string
  /** the repository the lesson teaches, for source links */
  repo?: RepoRef
}
