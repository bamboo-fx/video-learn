/**
 * The stage: one scene drawn as a 16:9 slide on warm paper.
 *
 * Everything is laid out on a fixed 1280 x 720 canvas and scaled to fit, so a scene
 * looks the same on a phone, in the editor and in a thumbnail.
 */
import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react"

import type { Item, Scene } from "@/lib/api"
import { cn } from "@/lib/utils"

export const STAGE_W = 1280
export const STAGE_H = 720

interface StageProps {
  scene: Scene | null
  /** which items are showing (by index); undefined = all of them */
  shown?: boolean[]
  index?: number
  count?: number
  lessonTitle?: string
  caption?: string | null
  /** thumbnails skip the caption and the animations */
  thumb?: boolean
  className?: string
  children?: ReactNode
}

export function Stage({ scene, shown, index, count, lessonTitle, caption, thumb, className, children }: StageProps) {
  const box = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const fit = () => setScale(el.clientWidth / STAGE_W)
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <div
      ref={box}
      className={cn("relative aspect-video w-full overflow-hidden bg-paper select-none", className)}
      role={thumb ? undefined : "img"}
      aria-label={thumb ? undefined : scene ? `Scene: ${scene.heading}` : "Empty stage"}
    >
      {scale > 0 && (
        <div
          className="absolute top-0 left-0 origin-top-left text-ink"
          style={{ width: STAGE_W, height: STAGE_H, transform: `scale(${scale})` }}
        >
          <Paper />
          {scene ? (
            <SceneBody key={scene.id} scene={scene} shown={shown} thumb={thumb} />
          ) : (
            <div className="flex h-full items-center justify-center font-serif text-[56px] text-ink-soft">No scenes yet</div>
          )}
          {!thumb && scene && (
            <div className="absolute top-[46px] right-[72px] left-[104px] flex items-center justify-between font-mono text-[17px] tracking-wide text-ink-soft uppercase">
              <span className="truncate pr-8">{lessonTitle}</span>
              {count ? (
                <span className="tabular-nums">
                  {String((index ?? 0) + 1).padStart(2, "0")} / {String(count).padStart(2, "0")}
                </span>
              ) : null}
            </div>
          )}
          {!thumb && caption ? (
            <div className="absolute right-0 bottom-[34px] left-0 flex justify-center px-[120px]">
              <p
                className="rounded-[14px] bg-ink/88 px-[26px] py-[12px] text-center leading-[1.3] font-medium text-paper shadow-lg"
                style={{ fontSize: Math.max(30, 14 / scale) }}
              >
                {caption}
              </p>
            </div>
          ) : null}
        </div>
      )}
      {children}
    </div>
  )
}

/** A faint ruled-paper texture and a margin line, drawn in CSS. */
function Paper() {
  return (
    <div aria-hidden className="absolute inset-0">
      <div
        className="absolute inset-0 opacity-[0.55]"
        style={{
          backgroundImage:
            "radial-gradient(1200px 600px at 85% -10%, oklch(0.93 0.035 70 / 0.55), transparent 60%), radial-gradient(900px 500px at -10% 110%, oklch(0.93 0.03 230 / 0.35), transparent 60%)",
        }}
      />
      <div className="absolute top-0 bottom-0 left-[72px] w-px bg-stage-accent/25" />
    </div>
  )
}

function Reveal({ on, thumb, delay = 0, children, className, style }: {
  on: boolean
  thumb?: boolean
  delay?: number
  children: ReactNode
  className?: string
  style?: CSSProperties
}) {
  return (
    <div
      className={cn(!thumb && "transition-[opacity,transform] duration-500 ease-out motion-reduce:transition-none", className)}
      style={{
        opacity: on ? 1 : 0,
        transform: on ? "none" : "translateY(14px)",
        transitionDelay: on ? `${delay}ms` : "0ms",
        ...style,
      }}
    >
      {children}
    </div>
  )
}

function SceneBody({ scene, shown, thumb }: { scene: Scene; shown?: boolean[]; thumb?: boolean }) {
  const on = (i: number) => (shown ? !!shown[i] : true)
  const props = { scene, on, thumb }
  switch (scene.layout) {
    case "title":
      return <TitleLayout {...props} />
    case "steps":
      return <StepsLayout {...props} />
    case "compare":
      return <CompareLayout {...props} />
    case "definition":
      return <DefinitionLayout {...props} />
    case "example":
      return <ExampleLayout {...props} />
    case "code":
      return <CodeLayout {...props} />
    case "summary":
      return <SummaryLayout {...props} />
    default:
      return <PointsLayout {...props} />
  }
}

interface LayoutProps {
  scene: Scene
  on: (i: number) => boolean
  thumb?: boolean
}

function Heading({ scene, size = 76 }: { scene: Scene; size?: number }) {
  return (
    <header>
      <h2 className="font-serif leading-[1.02] tracking-[-0.01em] text-ink" style={{ fontSize: size }}>
        {scene.heading}
      </h2>
      {scene.subheading ? <p className="mt-[14px] text-[28px] leading-snug text-ink-soft">{scene.subheading}</p> : null}
    </header>
  )
}

const frame = "absolute inset-0 px-[104px] pt-[112px] pb-[110px] flex flex-col"

function TitleLayout({ scene }: LayoutProps) {
  return (
    <div className={cn(frame, "justify-center")}>
      <div className="mb-[34px] h-[7px] w-[132px] rounded-full bg-stage-accent" />
      <h1 className="max-w-[1000px] font-serif text-[128px] leading-[0.95] tracking-[-0.02em]">{scene.heading}</h1>
      {scene.subheading ? (
        <p className="mt-[30px] max-w-[900px] font-serif text-[44px] leading-tight text-ink-soft italic">{scene.subheading}</p>
      ) : null}
    </div>
  )
}

function PointsLayout({ scene, on, thumb }: LayoutProps) {
  return (
    <div className={frame}>
      <Heading scene={scene} />
      <ul className="mt-[52px] flex flex-col gap-[30px]">
        {scene.items.map((item, i) => (
          <Reveal key={i} on={on(i)} thumb={thumb}>
            <li className="flex gap-[26px]">
              <span className="mt-[17px] size-[14px] shrink-0 rounded-full bg-stage-accent" />
              <ItemText item={item} />
            </li>
          </Reveal>
        ))}
      </ul>
    </div>
  )
}

function ItemText({ item, size = 38 }: { item: Item; size?: number }) {
  return (
    <div className="min-w-0">
      <p className="leading-[1.22] font-medium text-ink" style={{ fontSize: size }}>
        {item.text}
      </p>
      {item.detail ? <p className="mt-[6px] text-[26px] leading-snug text-ink-soft">{item.detail}</p> : null}
    </div>
  )
}

function StepsLayout({ scene, on, thumb }: LayoutProps) {
  const n = scene.items.length
  const size = n > 4 ? 32 : 36
  return (
    <div className={frame}>
      <Heading scene={scene} />
      <ol className="relative mt-[46px] flex flex-col gap-[22px]">
        <div className="absolute top-[30px] bottom-[30px] left-[29px] w-[2px] bg-ink-faint" aria-hidden />
        {scene.items.map((item, i) => (
          <Reveal key={i} on={on(i)} thumb={thumb}>
            <li className="relative flex items-start gap-[28px]">
              <span className="flex size-[60px] shrink-0 items-center justify-center rounded-full border-[3px] border-stage-accent bg-paper font-mono text-[26px] font-semibold text-stage-accent">
                {i + 1}
              </span>
              <div className="pt-[8px]">
                <ItemText item={item} size={size} />
              </div>
            </li>
          </Reveal>
        ))}
      </ol>
    </div>
  )
}

function CompareLayout({ scene, on, thumb }: LayoutProps) {
  const [a, b] = scene.items
  return (
    <div className={frame}>
      <Heading scene={scene} />
      <div className="mt-[48px] grid flex-1 grid-cols-[1fr_auto_1fr] items-stretch gap-[28px]">
        {[a, b].map((item, i) =>
          item ? (
            <Reveal key={i} on={on(i)} thumb={thumb} className={i === 1 ? "col-start-3" : ""}>
              <div className="flex h-full flex-col rounded-[28px] border-2 border-ink-faint bg-paper-deep/70 p-[38px]">
                <p className="font-serif text-[54px] leading-none">{item.text}</p>
                <div className="my-[22px] h-[4px] w-[64px] rounded-full bg-stage-accent" />
                <p className="text-[29px] leading-[1.35] text-ink-soft">{item.detail}</p>
              </div>
            </Reveal>
          ) : null,
        )}
        <div className="col-start-2 row-start-1 flex items-center font-serif text-[40px] text-ink-soft italic">vs</div>
      </div>
    </div>
  )
}

function DefinitionLayout({ scene, on, thumb }: LayoutProps) {
  const item = scene.items[0]
  return (
    <div className={cn(frame, "justify-center")}>
      <p className="mb-[12px] font-mono text-[20px] tracking-[0.2em] text-stage-accent uppercase">Definition</p>
      <h2 className="font-serif text-[104px] leading-none tracking-[-0.015em]">{scene.heading}</h2>
      {scene.subheading ? <p className="mt-[16px] text-[30px] text-ink-soft">{scene.subheading}</p> : null}
      {item ? (
        <Reveal on={on(0)} thumb={thumb}>
          <div className="mt-[48px] border-l-[6px] border-stage-accent pl-[34px]">
            <p className="max-w-[960px] text-[46px] leading-[1.22] font-medium">{item.text}</p>
            {item.detail ? <p className="mt-[16px] max-w-[960px] font-serif text-[34px] text-ink-soft italic">{item.detail}</p> : null}
          </div>
        </Reveal>
      ) : null}
    </div>
  )
}

function ExampleLayout({ scene, on, thumb }: LayoutProps) {
  return (
    <div className={frame}>
      <p className="mb-[10px] font-mono text-[20px] tracking-[0.2em] text-stage-accent uppercase">Example</p>
      <Heading scene={scene} size={64} />
      <div className="mt-[40px] flex flex-col gap-[16px]">
        {scene.items.map((item, i) => (
          <Reveal key={i} on={on(i)} thumb={thumb}>
            <div className="flex items-baseline gap-[24px] rounded-[18px] bg-paper-deep/80 px-[30px] py-[18px]">
              <span className="font-mono text-[22px] text-stage-accent">{i + 1}.</span>
              <p className="font-mono text-[30px] leading-snug">{item.text}</p>
              {item.detail ? <p className="ml-auto pl-[24px] text-right text-[24px] text-ink-soft">{item.detail}</p> : null}
            </div>
          </Reveal>
        ))}
      </div>
    </div>
  )
}

function CodeLayout({ scene, on, thumb }: LayoutProps) {
  const lines = scene.code.split("\n").slice(0, 14)
  // shrink the code to fit its card: the widest line and the line count both decide
  const widest = Math.max(20, ...lines.map((l) => l.replace(/\t/g, "    ").length))
  const byWidth = Math.floor(540 / ((widest + 2.4) * 0.6))
  const byHeight = Math.floor(400 / (Math.max(lines.length, 4) * 1.55))
  const font = Math.max(14, Math.min(26, byWidth, byHeight))
  return (
    <div className={frame}>
      <Heading scene={scene} size={64} />
      <div className="mt-[36px] grid flex-1 grid-cols-[1.45fr_1fr] gap-[36px]">
        <pre className="overflow-hidden rounded-[24px] bg-ink p-[34px] font-mono leading-[1.55] text-paper shadow-xl" style={{ fontSize: font }}>
          {lines.map((ln, i) => (
            <div key={i} className="flex">
              <span className="w-[2.2em] shrink-0 text-paper/35 tabular-nums">{i + 1}</span>
              <code className="whitespace-pre">{ln || " "}</code>
            </div>
          ))}
        </pre>
        <div className="flex flex-col justify-center gap-[24px]">
          {scene.items.map((item, i) => (
            <Reveal key={i} on={on(i)} thumb={thumb}>
              <div className="flex gap-[18px]">
                <span className="mt-[8px] h-[34px] w-[6px] shrink-0 rounded-full bg-stage-accent" />
                <ItemText item={item} size={32} />
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </div>
  )
}

function SummaryLayout({ scene, on, thumb }: LayoutProps) {
  return (
    <div className={frame}>
      <Heading scene={scene} />
      <ul className="mt-[50px] flex flex-col gap-[26px]">
        {scene.items.map((item, i) => (
          <Reveal key={i} on={on(i)} thumb={thumb}>
            <li className="flex items-start gap-[24px]">
              <svg viewBox="0 0 24 24" className="mt-[4px] size-[44px] shrink-0 text-stage-accent" aria-hidden>
                <circle cx="12" cy="12" r="11" fill="currentColor" opacity="0.14" />
                <path d="M7 12.5l3.2 3.2L17.5 8.5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <ItemText item={item} size={38} />
            </li>
          </Reveal>
        ))}
      </ul>
    </div>
  )
}
