/** A tiny router: three pages don't need a library. */
import { useSyncExternalStore } from "react"

export type Route =
  | { page: "home" }
  | { page: "lesson"; id: string }
  | { page: "demo" }
  | { page: "missing" }

function parse(path: string): Route {
  if (path === "/" || path === "") return { page: "home" }
  if (path === "/demo") return { page: "demo" }
  const m = path.match(/^\/l\/([A-Za-z0-9_-]+)\/?$/)
  if (m) return { page: "lesson", id: m[1] }
  return { page: "missing" }
}

const listeners = new Set<() => void>()
window.addEventListener("popstate", () => listeners.forEach((l) => l()))

export function navigate(path: string) {
  if (path === window.location.pathname) return
  window.history.pushState({}, "", path)
  window.scrollTo(0, 0)
  listeners.forEach((l) => l())
}

export function useRoute(): Route {
  const path = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => window.location.pathname,
  )
  return parse(path)
}
