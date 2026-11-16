/**
 * Turns a storyboard (plus whatever narration has been voiced) into a timeline:
 * when each scene starts, when each word is spoken, when each item appears and
 * which caption is on screen.
 *
 * A voiced scene uses ElevenLabs' real word timings. A scene with no voice yet gets
 * estimated timings (about 150 words a minute), so the lesson still plays, with
 * captions, before anything has been paid for.
 */
import type { Scene, Storyboard, Voice, Word } from "./api"

/** Silence before a scene's narration starts, and after it ends. */
export const LEAD = 0.35
export const TAIL = 0.65

export interface Span {
  start: number
  end: number
}

export interface Caption extends Span {
  text: string
}

export interface SceneTiming {
  id: string
  index: number
  /** global start, seconds */
  start: number
  duration: number
  voiced: boolean
  voice: Voice | null
  /** times below are local to the scene, LEAD included */
  words: Word[]
  sentences: Span[]
  reveals: number[]
  captions: Caption[]
}

export interface Timeline {
  scenes: SceneTiming[]
  total: number
}

// A sentence ends at . ! or ? followed by a space or the end, so "Node.js" and "3.14" stay whole.
const SENTENCE = /\S[\s\S]*?(?:[.!?]+["')\]]*(?=\s|$)|$)/g

/** Character spans of each sentence. Mirrors backend/app/storyboard.py sentences(). */
export function sentenceSpans(text: string): [number, number][] {
  const spans: [number, number][] = []
  for (const m of text.matchAll(SENTENCE)) {
    const a = m.index ?? 0
    let b = a + m[0].length
    while (b > a && /\s/.test(text[b - 1])) b--
    if (b > a) spans.push([a, b])
  }
  return spans.length ? spans : [[0, text.length]]
}

/** Words with estimated timings, for narration that hasn't been voiced. */
export function estimateWords(text: string): Word[] {
  const words: Word[] = []
  let t = 0
  for (const m of text.matchAll(/\S+/g)) {
    const w = m[0]
    const len = 0.16 + 0.052 * w.replace(/[^\p{L}\p{N}]/gu, "").length
    words.push({ text: w, start_char: m.index ?? 0, end_char: (m.index ?? 0) + w.length, start: t, end: t + len })
    t += len + 0.06
    if (/[.!?]["')\]]*$/.test(w)) t += 0.32
    else if (/[,;:]$/.test(w)) t += 0.14
  }
  return words
}

export function voiceFor(scene: Scene, voices: Record<string, Voice>): Voice | null {
  const v = voices[scene.id]
  return v && v.text === scene.narration ? v : null
}

function captionsFor(narration: string, words: Word[], sentences: [number, number][]): Caption[] {
  const out: Caption[] = []
  for (const [a, b] of sentences) {
    const ws = words.filter((w) => w.start_char >= a && w.end_char <= b + 1)
    if (!ws.length) continue
    // break a sentence into lines of at most ~48 characters, preferring commas
    let line: Word[] = []
    const flush = () => {
      if (!line.length) return
      out.push({
        text: narration.slice(line[0].start_char, line[line.length - 1].end_char),
        start: line[0].start,
        end: line[line.length - 1].end,
      })
      line = []
    }
    for (const w of ws) {
      const len = line.length ? w.end_char - line[0].start_char : 0
      if (line.length && len > 48) flush()
      line.push(w)
      if (/[,;:]$/.test(w.text) && w.end_char - line[0].start_char > 22) flush()
    }
    flush()
  }
  // hold each caption until the next one starts, unless there's a real pause
  for (let i = 0; i < out.length; i++) {
    const next = out[i + 1]
    out[i].end = next && next.start - out[i].end < 0.6 ? next.start : out[i].end + 0.3
  }
  return out
}

/** The server counts characters as Python does (code points); JavaScript strings count
 * UTF-16 units, and an emoji is two of them. Map the server's offsets onto this string. */
export function toUtf16Offsets(text: string, words: Word[]): Word[] {
  if (!/[\uD800-\uDFFF]/.test(text)) return words
  const at: number[] = []
  let u = 0
  for (const ch of text) {
    at.push(u)
    u += ch.length
  }
  at.push(u)
  const map = (cp: number) => at[Math.min(cp, at.length - 1)]
  return words.map((w) => ({ ...w, start_char: map(w.start_char), end_char: map(w.end_char) }))
}

export function sceneTiming(scene: Scene, index: number, start: number, voice: Voice | null): SceneTiming {
  const raw = voice ? toUtf16Offsets(scene.narration, voice.words) : estimateWords(scene.narration)
  const words = raw.map((w) => ({ ...w, start: w.start + LEAD, end: w.end + LEAD }))
  const spans = sentenceSpans(scene.narration)
  const sentences: Span[] = spans.map(([a, b]) => {
    const ws = words.filter((w) => w.start_char >= a && w.end_char <= b + 1)
    return ws.length ? { start: ws[0].start, end: ws[ws.length - 1].end } : { start: LEAD, end: LEAD }
  })
  const spoken = voice ? voice.duration : raw.length ? raw[raw.length - 1].end : 1.5
  const duration = Math.max(2, LEAD + spoken + TAIL)
  const reveals = scene.items.map((item) => {
    const s = sentences[Math.min(item.at, sentences.length - 1)]
    return Math.max(0.2, (s?.start ?? LEAD) - 0.08)
  })
  return {
    id: scene.id,
    index,
    start,
    duration,
    voiced: !!voice,
    voice,
    words,
    sentences,
    reveals,
    captions: captionsFor(scene.narration, words, spans),
  }
}

export function buildTimeline(board: Storyboard | null, voices: Record<string, Voice>): Timeline {
  const scenes: SceneTiming[] = []
  let t = 0
  for (const [i, scene] of (board?.scenes ?? []).entries()) {
    const timing = sceneTiming(scene, i, t, voiceFor(scene, voices))
    scenes.push(timing)
    t += timing.duration
  }
  return { scenes, total: t }
}

export function sceneAt(timeline: Timeline, time: number): SceneTiming | null {
  const { scenes } = timeline
  if (!scenes.length) return null
  for (const s of scenes) if (time < s.start + s.duration) return s
  return scenes[scenes.length - 1]
}

export function captionAt(scene: SceneTiming | null, local: number): Caption | null {
  if (!scene) return null
  return scene.captions.find((c) => local >= c.start && local < c.end) ?? null
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

export function wordCount(text: string): number {
  return (text.match(/\S+/g) ?? []).length
}
