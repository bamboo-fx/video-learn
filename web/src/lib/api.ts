import type { Storyboard } from "./storyboard.gen"

export type { Storyboard }
export type Scene = Storyboard["scenes"][number]
export type Item = Scene["items"][number]
export type Layout = Scene["layout"]

/** Narration ElevenLabs has voiced, with when each word is said. */
export interface Voice {
  hash: string
  /** the narration this audio says; stale once the scene's narration changes */
  text: string
  url: string
  duration: number
  words: Word[]
}

export interface Word {
  text: string
  /** character offset in the scene's narration */
  start_char: number
  end_char: number
  start: number
  end: number
}

/** Ways of explaining, each for a kind of learning goal. The server sets the audience and
 * length for each (backend/app/llm.py MODES). */
export const LESSON_MODES = [
  { value: "walkthrough", label: "Walkthrough", hint: "The whole picture, in the order things happen. About 3 minutes." },
  { value: "bottom_up", label: "Bottom-up", hint: "From the smallest concrete piece up, one idea per step. About 4 minutes." },
] as const

export type LessonMode = (typeof LESSON_MODES)[number]["value"]

export interface Project {
  id: string
  topic: string
  notes: string
  /** how the lesson explains things (one per kind of learning goal) */
  mode: LessonMode
  title: string
  status: "new" | "writing" | "ready" | "failed"
  error: string
  storyboard: Storyboard | null
  /** "owner/repo" when the lesson teaches a codebase, at commit repo_sha */
  repo: string
  /** a branch or tag from the pasted link, or "" for the default branch */
  repo_ref: string
  repo_sha: string
  /** what Claude is doing while it writes, newest last */
  progress: string[]
  voices: Record<string, Voice>
  is_owner: boolean
  /** the owner, or someone the owner invited to edit */
  can_edit: boolean
  /** goes up each time the storyboard changes, whoever changed it */
  rev: number
  /** who can edit, owner first; empty unless you can edit too */
  people: Person[]
  /** what the others see next to your changes */
  my_name: string
  /** the token of the link that invites editors; "" when off, and only the owner gets it */
  invite_token: string
  /** "web" (written on our server), "local" (the /lesson skill) or "connector" (claude.ai) */
  origin: "web" | "local" | "connector"
  created_at: string
  updated_at: string
}

/** Someone who can edit a lesson. `id` is 0 for the owner. */
export interface Person {
  id: number
  name: string
  role: "owner" | "editor"
  you: boolean
}

/** Where a save and someone else's changed the same thing. The save won; `note` says what. */
export interface Conflict {
  scene_id: string
  heading: string
  note: string
}

export interface VersionChange {
  kind: "lesson" | "added" | "changed" | "removed" | "reordered"
  scene_id: string
  heading: string
  /** which parts changed: "narration", "heading", ... */
  fields: string[]
}

/** One entry in a lesson's history. */
export interface VersionInfo {
  id: number
  /** 1, 2, 3... within the lesson */
  number: number
  kind: "start" | "write" | "import" | "hand" | "ai" | "restore"
  /** set when someone saved this version on purpose */
  name: string
  message: string
  authors: string[]
  /** what changed since the version before */
  changes: VersionChange[]
  /** the lesson is this version right now */
  current: boolean
  created_at: string
  updated_at: string
}

/** A page of the history, newest first. */
export interface VersionPage {
  versions: VersionInfo[]
  /** there are older versions than these */
  more: boolean
}

export interface VersionFull extends VersionInfo {
  storyboard: Storyboard
  repo_sha: string
}

export interface ProjectSummary {
  id: string
  /** someone else's lesson you were invited to edit */
  shared: boolean
  title: string
  topic: string
  repo: string
  status: Project["status"]
  scenes: number
  updated_at: string
}

export interface EditChange {
  kind: "updated" | "inserted" | "deleted" | "moved"
  scene_id: string
  note: string
}

export interface EditResult {
  project: Project
  summary: string
  changes: EditChange[]
}

// ---------------------------------------------------------------- who is asking

const OWNER_KEY = "video-learn.owner"

/** A random id kept in this browser. Lessons made with it are yours. */
export function ownerId(): string {
  let id = localStorage.getItem(OWNER_KEY)
  if (!id) {
    const bytes = crypto.getRandomValues(new Uint8Array(18))
    id = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
    localStorage.setItem(OWNER_KEY, id)
  }
  return id
}

const NAME_KEY = "video-learn.name"

/** What this person asked to be called, remembered so they're asked once, not per lesson. */
export function savedName(): string {
  try {
    return localStorage.getItem(NAME_KEY) ?? ""
  } catch {
    return ""
  }
}

export function rememberName(name: string) {
  try {
    localStorage.setItem(NAME_KEY, name)
  } catch {
    // it still reaches the server for this lesson
  }
}

// ---------------------------------------------------------------- requests

export class ApiError extends Error {
  code: string
  status: number
  constructor(message: string, code: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers: { "X-Owner": ownerId(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", "network", 0)
  }
  if (res.status === 204) return undefined as T
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    // a proxy error page, or an empty body
  }
  if (!res.ok) {
    const err = (data as { error?: { message?: string; code?: string } } | null)?.error
    throw new ApiError(err?.message || `The server answered ${res.status}. Try again in a moment.`, err?.code || "http", res.status)
  }
  return data as T
}

export const api = {
  config: () => request<{ ai: boolean; voice: boolean }>("GET", "/api/config"),
  list: () => request<{ projects: ProjectSummary[] }>("GET", "/api/projects").then((r) => r.projects),
  get: (id: string) => request<Project>("GET", `/api/projects/${id}`),
  create: (input: { topic: string; repo: string; notes: string; mode: LessonMode }) =>
    request<Project>("POST", "/api/projects", input),
  write: (id: string) => request<Project>("POST", `/api/projects/${id}/write`),
  /** `base` is the storyboard these edits started from: if someone else saved since, the
   * server merges the two instead of letting this save erase theirs. */
  save: (id: string, storyboard: Storyboard, base?: Storyboard) =>
    request<Project & { conflicts: Conflict[] }>("PUT", `/api/projects/${id}/storyboard`, { storyboard, base }),
  voice: (id: string, sceneId: string) => request<Voice>("POST", `/api/projects/${id}/scenes/${sceneId}/voice`),
  edit: (id: string, instruction: string, sceneId: string | null) =>
    request<EditResult>("POST", `/api/projects/${id}/edit`, { instruction, scene_id: sceneId }),
  remove: (id: string) => request<void>("DELETE", `/api/projects/${id}`),
  claim: (id: string, token: string) => request<Project>("POST", `/api/projects/${id}/claim`, { token }),

  // history
  /** a page of the history, newest first; `before` = the oldest version id already shown */
  versions: (id: string, before?: number) =>
    request<VersionPage>("GET", `/api/projects/${id}/versions${before === undefined ? "" : `?before=${before}`}`),
  version: (id: string, versionId: number) => request<VersionFull>("GET", `/api/projects/${id}/versions/${versionId}`),
  nameVersion: (id: string, name: string) => request<VersionInfo>("POST", `/api/projects/${id}/versions`, { name }),
  restore: (id: string, versionId: number) => request<Project>("POST", `/api/projects/${id}/versions/${versionId}/restore`),

  // editing together
  rev: (id: string) => request<{ rev: number; status: Project["status"]; editors: number }>("GET", `/api/projects/${id}/rev`),
  invite: (id: string, reset = false) => request<Project>("POST", `/api/projects/${id}/invite`, { reset }),
  stopInviting: (id: string) => request<Project>("DELETE", `/api/projects/${id}/invite`),
  join: (id: string, token: string, name: string) => request<Project>("POST", `/api/projects/${id}/join`, { token, name }),
  removeMember: (id: string, memberId: number) => request<Project>("DELETE", `/api/projects/${id}/members/${memberId}`),
  setName: (id: string, name: string) => request<Project>("PUT", `/api/projects/${id}/me`, { name }),
}

// ---------------------------------------------------------------- repositories

export interface RepoRef {
  name: string // owner/repo
  sha: string
}

// The same forms the server's github.parse_repo accepts: the repository root, or a tree or
// blob link, with an optional .git and ?query or #fragment.
const REPO_URL =
  /^\s*(?:https?:\/\/)?(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?(?:\/(?:tree|blob)\/[^/\s?#]+[^\s?#]*)?\/?(?:[?#].*)?\s*$/
const REPO_SHORT = /^\s*([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\s*$/

/** "github.com/o/r/tree/main" or "o/r" -> "o/r"; null if it isn't a GitHub repository. */
export function parseRepo(text: string): string | null {
  const m = text.match(REPO_URL) ?? text.match(REPO_SHORT)
  return m ? `${m[1]}/${m[2]}` : null
}

export function githubUrl(repo: RepoRef, path = "", start = 0, end = 0): string {
  if (!path) return `https://github.com/${repo.name}/tree/${repo.sha}`
  const lines = start ? `#L${start}${end && end !== start ? `-L${end}` : ""}` : ""
  // each path segment encoded, so a file like src/C#Parser.cs isn't cut at the #
  return `https://github.com/${repo.name}/blob/${repo.sha}/${path.split("/").map(encodeURIComponent).join("/")}${lines}`
}
