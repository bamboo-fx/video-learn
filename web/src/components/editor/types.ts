import type { EditResult, Person, RepoRef, Storyboard, VersionFull, VersionInfo, Voice } from "@/lib/api"

/** Where a scene's narration stands with ElevenLabs. */
export type VoiceState =
  | { kind: "voiced" }
  | { kind: "stale" } // never voiced, or the narration changed since
  | { kind: "voicing" }
  | { kind: "failed"; message: string }

/** The lesson's history: every version of the storyboard, and going back to one. */
export interface HistoryHost {
  /** changes whenever the lesson does, so an open list knows to reload */
  rev: number
  list: () => Promise<VersionInfo[]>
  load: (versionId: number) => Promise<VersionFull>
  /** make the lesson what it was at this version (adds a version; nothing is lost) */
  restore: (versionId: number) => Promise<void>
  /** keep the lesson as it is now under a name */
  name: (name: string) => Promise<void>
}

/** Who can edit the lesson, and inviting more people. */
export interface SharingHost {
  people: Person[]
  isOwner: boolean
  myName: string
  setMyName: (name: string) => Promise<void>
  /** the link that makes whoever opens it an editor; "" when it's off or you aren't the owner */
  inviteUrl: string
  invite: (reset?: boolean) => Promise<void>
  stopInviting: () => Promise<void>
  /** the owner removes an editor, or an editor leaves */
  remove: (personId: number) => Promise<void>
}

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
  /** undefined where there's no history (the example isn't saved anywhere) */
  history?: HistoryHost
  /** undefined where a lesson can't be edited with others, or you can't edit this one */
  sharing?: SharingHost
  /** the repository the lesson teaches, for source links */
  repo?: RepoRef
  /** sources can't be changed here (the example has no server to re-read the code) */
  sourcesLocked?: boolean
  /** a reason hand editing is paused right now (an AI edit is running), or undefined */
  locked?: string
}
