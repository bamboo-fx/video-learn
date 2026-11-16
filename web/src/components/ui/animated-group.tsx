/**
 * Children that arrive one after another, fading up out of a slight blur.
 * From 21st.dev (ibelick/animated-group, motion-primitives), trimmed to the one preset we use.
 * Reduced motion: MotionConfig reducedMotion="user" in main.tsx drops the movement.
 */
import { motion, type Variants } from "motion/react"
import { Children, type ReactNode } from "react"

const container: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.07 } },
}

const item: Variants = {
  hidden: { opacity: 0, y: 12, filter: "blur(6px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
}

export function AnimatedGroup({ children, className, as = "div" }: { children: ReactNode; className?: string; as?: "div" | "ul" }) {
  const Wrap = as === "ul" ? motion.ul : motion.div
  const Item = as === "ul" ? motion.li : motion.div
  return (
    <Wrap initial="hidden" animate="visible" variants={container} className={className}>
      {Children.map(children, (child) => (child == null ? null : <Item variants={item}>{child}</Item>))}
    </Wrap>
  )
}
