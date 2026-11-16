/**
 * A short light that travels around its parent's border. The parent needs `relative` and
 * a border radius. From 21st.dev (magicui/border-beam); colors default to ember.
 * The keyframes are `border-beam` in index.css; reduced motion hides it.
 */
import type { CSSProperties } from "react"

import { cn } from "@/lib/utils"

export function BorderBeam({
  className,
  size = 160,
  duration = 9,
  anchor = 90,
  borderWidth = 1.5,
  colorFrom = "var(--ember)",
  colorTo = "oklch(0.85 0.12 70)",
  delay = 0,
}: {
  className?: string
  size?: number
  duration?: number
  anchor?: number
  borderWidth?: number
  colorFrom?: string
  colorTo?: string
  delay?: number
}) {
  return (
    <div
      aria-hidden
      style={
        {
          "--size": size,
          "--duration": duration,
          "--anchor": anchor,
          "--border-width": borderWidth,
          "--color-from": colorFrom,
          "--color-to": colorTo,
          "--delay": `-${delay}s`,
        } as CSSProperties
      }
      className={cn(
        "pointer-events-none absolute inset-0 rounded-[inherit] [border:calc(var(--border-width)*1px)_solid_transparent] motion-reduce:hidden",
        "![mask-clip:padding-box,border-box] ![mask-composite:intersect] [mask:linear-gradient(transparent,transparent),linear-gradient(white,white)]",
        "after:absolute after:aspect-square after:w-[calc(var(--size)*1px)] after:animate-border-beam after:[animation-delay:var(--delay)] after:[background:linear-gradient(to_left,var(--color-from),var(--color-to),transparent)] after:[offset-anchor:calc(var(--anchor)*1%)_50%] after:[offset-path:rect(0_auto_auto_0_round_calc(var(--size)*1px))]",
        className,
      )}
    />
  )
}
