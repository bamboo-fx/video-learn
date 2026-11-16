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

export interface Project {
  id: string
  topic: string
  notes: string
  level: "intro" | "intermediate" | "advanced"
  minutes: number
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
  /** "web" (written on our server), "local" (the /lesson skill) or "connector" (claude.ai) */
  origin: "web" | "local" | "connector"
  created_at: string
  updated_at: string
}

export interface ProjectSummary {
  id: string
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
  create: (input: { topic: string; repo: string; notes: string; level: string; minutes: number }) =>
    request<Project>("POST", "/api/projects", input),
  write: (id: string) => request<Project>("POST", `/api/projects/${id}/write`),
  save: (id: string, storyboard: Storyboard) => request<Project>("PUT", `/api/projects/${id}/storyboard`, { storyboard }),
  voice: (id: string, sceneId: string) => request<Voice>("POST", `/api/projects/${id}/scenes/${sceneId}/voice`),
  edit: (id: string, instruction: string, sceneId: string | null) =>
    request<EditResult>("POST", `/api/projects/${id}/edit`, { instruction, scene_id: sceneId }),
  remove: (id: string) => request<void>("DELETE", `/api/projects/${id}`),
  claim: (id: string, token: string) => request<Project>("POST", `/api/projects/${id}/claim`, { token }),
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
