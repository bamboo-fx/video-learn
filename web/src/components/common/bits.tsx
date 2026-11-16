import { AlertTriangle, Loader2 } from "lucide-react"
import { useEffect, useState, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { navigate } from "@/lib/router"
import { cn } from "@/lib/utils"

export function Logo({ className }: { className?: string }) {
  return (
    <a
      href="/"
      onClick={(e) => {
        e.preventDefault()
        navigate("/")
      }}
      className={cn("group inline-flex items-center gap-2.5 rounded-md text-foreground", className)}
      aria-label="Video Learn, home"
    >
      <span className="relative flex size-7 items-center justify-center rounded-[9px] bg-ember text-primary-foreground shadow-[0_0_0_1px_oklch(1_0_0/0.12)_inset]">
        <svg viewBox="0 0 24 24" className="size-[15px]" aria-hidden>
          <path d="M8 5.5v13l10.5-6.5z" fill="currentColor" />
        </svg>
      </span>
      <span className="font-serif text-[22px] leading-none tracking-tight">Video Learn</span>
    </a>
  )
}

/** Nothing for 600 ms, then one small spinner and a line of text. */
export function QuietLoading({ label, className }: { label: string; className?: string }) {
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 600)
    return () => clearTimeout(t)
  }, [])
  return (
    <div role="status" aria-label={label} className={cn("flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground", className)}>
      {visible ? (
        <>
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          <span>{label}</span>
        </>
      ) : null}
    </div>
  )
}

export function Problem({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive/8 p-4 text-sm">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-foreground">{title}</p>
        {children ? <div className="mt-1 text-muted-foreground">{children}</div> : null}
        {action ? <div className="mt-3">{action}</div> : null}
      </div>
    </div>
  )
}

export function Shell({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="min-h-full animate-in duration-200 fade-in">
      <header className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <Logo />
        <nav className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => navigate("/connect")}>
            <span className="sm:hidden">From Claude</span>
            <span className="hidden sm:inline">Use it from Claude</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => navigate("/demo")}>
            <span className="sm:hidden">Example</span>
            <span className="hidden sm:inline">Watch an example</span>
          </Button>
        </nav>
      </header>
      <main className={cn("mx-auto px-5 pb-24", wide ? "max-w-6xl" : "max-w-3xl")}>{children}</main>
    </div>
  )
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const s = Math.round((Date.now() - then) / 1000)
  if (s < 60) return "just now"
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.round(h / 24)
  if (d < 7) return `${d} d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" })
}
