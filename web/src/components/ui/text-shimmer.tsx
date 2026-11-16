/**
 * Text with a light sweeping across it, for "working on it" lines.
 * From 21st.dev (ibelick/text-shimmer, motion-primitives), on the app's tokens.
 * Under prefers-reduced-motion it is plain text.
 */
import { motion, useReducedMotion } from "motion/react"
import type { CSSProperties } from "react"

import { cn } from "@/lib/utils"

export function TextShimmer({
  children,
  className,
  duration = 2,
  spread = 2,
}: {
  children: string
  className?: string
  duration?: number
  spread?: number
}) {
  const reduce = useReducedMotion()
  if (reduce) return <span className={className}>{children}</span>
  return (
    <motion.span
      className={cn(
        "relative inline-block bg-[length:250%_100%,auto] bg-clip-text text-transparent [background-repeat:no-repeat,padding-box]",
        "[--base:var(--muted-foreground)] [--shine:var(--foreground)]",
        className,
      )}
      initial={{ backgroundPosition: "100% center" }}
      animate={{ backgroundPosition: "0% center" }}
      transition={{ repeat: Infinity, duration, ease: "linear" }}
      style={
        {
          "--spread": `${children.length * spread}px`,
          backgroundImage:
            "linear-gradient(90deg,#0000 calc(50% - var(--spread)),var(--shine),#0000 calc(50% + var(--spread))), linear-gradient(var(--base),var(--base))",
        } as CSSProperties
      }
    >
      {children}
    </motion.span>
  )
}
