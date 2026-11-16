import { WifiOff } from "lucide-react"
import { useSyncExternalStore } from "react"

const subscribe = (cb: () => void) => {
  window.addEventListener("online", cb)
  window.addEventListener("offline", cb)
  return () => {
    window.removeEventListener("online", cb)
    window.removeEventListener("offline", cb)
  }
}

/** Says so when the phone loses its connection, instead of letting buttons fail silently. */
export function OfflineNotice() {
  const online = useSyncExternalStore(subscribe, () => navigator.onLine)
  if (online) return null
  return (
    <div role="status" className="fixed inset-x-0 bottom-4 z-50 flex justify-center px-4">
      <p className="flex items-center gap-2 rounded-full border border-border bg-popover px-4 py-2 text-sm shadow-lg">
        <WifiOff className="size-4 text-destructive" aria-hidden /> You're offline. Keep this page open; your changes save when the connection is back.
      </p>
    </div>
  )
}
