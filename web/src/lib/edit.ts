/** Hand edits to a storyboard. Each returns a new storyboard; nothing is mutated. */
import type { Layout, Scene, Storyboard } from "./api"

export const LAYOUT_LABELS: Record<Layout, string> = {
  title: "Title card",
  points: "Key points",
  steps: "Steps",
  compare: "Compare two",
  definition: "Definition",
  example: "Worked example",
  code: "Code",
  summary: "Summary",
}

export function nextId(board: Storyboard): string {
  const nums = board.scenes.map((s) => Number(s.id.replace(/^s/, ""))).filter(Number.isFinite)
  return `s${Math.max(0, ...nums) + 1}`
}

export function updateScene(board: Storyboard, id: string, patch: Partial<Scene>): Storyboard {
  return { ...board, scenes: board.scenes.map((s) => (s.id === id ? { ...s, ...patch } : s)) }
}

export function insertScene(board: Storyboard, afterId: string | null): { board: Storyboard; id: string } {
  const id = nextId(board)
  const scene: Scene = {
    id,
    layout: "points",
    heading: "New scene",
    subheading: "",
    items: [{ text: "A first point", detail: "", at: 0 }],
    code: "",
    narration: "Say what this scene is about here.",
  }
  const i = afterId ? board.scenes.findIndex((s) => s.id === afterId) : board.scenes.length - 1
  const scenes = [...board.scenes]
  scenes.splice(i + 1, 0, scene)
  return { board: { ...board, scenes }, id }
}

export function duplicateScene(board: Storyboard, id: string): { board: Storyboard; id: string } {
  const i = board.scenes.findIndex((s) => s.id === id)
  if (i < 0) return { board, id }
  const copy = { ...structuredClone(board.scenes[i]), id: nextId(board) }
  const scenes = [...board.scenes]
  scenes.splice(i + 1, 0, copy)
  return { board: { ...board, scenes }, id: copy.id }
}

export function deleteScene(board: Storyboard, id: string): Storyboard {
  if (board.scenes.length <= 1) return board
  return { ...board, scenes: board.scenes.filter((s) => s.id !== id) }
}

export function moveScene(board: Storyboard, id: string, by: -1 | 1): Storyboard {
  const i = board.scenes.findIndex((s) => s.id === id)
  const j = i + by
  if (i < 0 || j < 0 || j >= board.scenes.length) return board
  const scenes = [...board.scenes]
  ;[scenes[i], scenes[j]] = [scenes[j], scenes[i]]
  return { ...board, scenes }
}
