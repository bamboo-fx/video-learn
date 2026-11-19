/** Sharing a lesson: a link to watch it, and (for the people who can edit) a link that lets
 * someone else edit it too, the list of who can, and the name they see next to your changes. */
import { Check, Copy, Link2, Loader2, UserPlus, X } from "lucide-react"
import { useEffect, useId, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ApiError } from "@/lib/api"

import type { SharingHost } from "./types"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  shareUrl: string
  sharing?: SharingHost
}

const why = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

export function ShareDialog({ open, onOpenChange, shareUrl, sharing }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* focus goes to the dialog itself, not into the first link (which would select it, and on a phone raise the keyboard) */}
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] gap-5 overflow-y-auto sm:max-w-md"
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          ;(e.currentTarget as HTMLElement).focus()
        }}
      >
        <DialogHeader>
          <DialogTitle>Share this lesson</DialogTitle>
          <DialogDescription className="sr-only">Links for watching the lesson and for editing it together.</DialogDescription>
        </DialogHeader>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Watch</h3>
          <p className="text-xs text-muted-foreground">Anyone with this link can watch. They can't change anything.</p>
          <CopyField label="Link to watch the lesson" value={shareUrl} />
        </section>

        {sharing ? <Together sharing={sharing} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function Together({ sharing }: { sharing: SharingHost }) {
  const [busy, setBusy] = useState<string | null>(null)
  const owner = sharing.people.find((p) => p.role === "owner")

  const run = (what: string, action: () => Promise<void>, failed: string) => {
    setBusy(what)
    action()
      .catch((e) => toast.error(why(e, failed)))
      .finally(() => setBusy(null))
  }

  return (
    <>
      <section className="flex flex-col gap-2 border-t border-border pt-4">
        <h3 className="text-sm font-medium">Edit together</h3>
        {sharing.isOwner ? (
          <>
            <p className="text-xs text-muted-foreground">
              Anyone who opens the invite link can edit this lesson with you. Every change is kept in History, so anything they do can be undone.
            </p>
            {sharing.inviteUrl ? (
              <>
                <CopyField label="Link that invites someone to edit" value={sharing.inviteUrl} />
                <div className="flex flex-wrap gap-1.5">
                  <Button size="xs" variant="outline" disabled={!!busy} onClick={() => run("reset", () => sharing.invite(true), "Couldn't make a new link.")}>
                    {busy === "reset" ? <Loader2 className="animate-spin" /> : null} Make a new link
                  </Button>
                  <Button size="xs" variant="outline" disabled={!!busy} onClick={() => run("off", sharing.stopInviting, "Couldn't turn the link off.")}>
                    {busy === "off" ? <Loader2 className="animate-spin" /> : null} Turn the link off
                  </Button>
                </div>
                <p className="text-[11px] text-muted-foreground">A new link stops the old one working. People who already joined stay until you remove them.</p>
              </>
            ) : (
              <Button variant="secondary" className="self-start" disabled={!!busy} onClick={() => run("on", () => sharing.invite(), "Couldn't make an invite link.")}>
                {busy === "on" ? <Loader2 className="animate-spin" /> : <UserPlus />} Make an invite link
              </Button>
            )}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            You were invited to edit this lesson. Only {owner?.name || "the person who made it"} can invite more people.
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2 border-t border-border pt-4">
        <h3 className="text-sm font-medium">Who can edit</h3>
        <ul className="flex flex-col gap-1">
          {sharing.people.map((p) => (
            <li key={p.id} className="flex items-center gap-2.5 rounded-lg px-1 py-1 text-sm">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-panel-raised text-[11px] font-medium uppercase" aria-hidden>
                {(p.name || "?").slice(0, 1)}
              </span>
              <span className="min-w-0 flex-1 truncate">
                {p.name || <span className="text-muted-foreground">No name yet</span>}
                {p.you ? <span className="text-muted-foreground"> (you)</span> : null}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">{p.role === "owner" ? "Owner" : "Editor"}</span>
              {p.role === "editor" && (sharing.isOwner || p.you) ? (
                <Button
                  size="xs"
                  variant="ghost"
                  disabled={!!busy}
                  onClick={() => run(`remove-${p.id}`, () => sharing.remove(p.id), p.you ? "Couldn't leave the lesson." : "Couldn't remove them.")}
                  aria-label={p.you ? "Leave this lesson" : `Remove ${p.name || "this editor"}`}
                >
                  {busy === `remove-${p.id}` ? <Loader2 className="animate-spin" /> : <X />} {p.you ? "Leave" : "Remove"}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
        <YourName sharing={sharing} />
      </section>
    </>
  )
}

function YourName({ sharing }: { sharing: SharingHost }) {
  // what's typed, until it's saved; otherwise the name the server has
  const [typed, setTyped] = useState<string | null>(null)
  const name = typed ?? sharing.myName
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle")
  const id = useId()

  const save = () => {
    const next = name.trim()
    if (next === sharing.myName || state === "saving") return
    setState("saving")
    sharing.setMyName(next).then(
      () => (setState("saved"), setTyped(null)),
      (e) => {
        setState("idle")
        toast.error(why(e, "Couldn't save your name."))
      },
    )
  }

  return (
    <form
      className="mt-1 flex flex-col gap-1.5"
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      <label htmlFor={id} className="text-xs text-muted-foreground">
        Your name, shown next to your changes in History
      </label>
      <div className="flex gap-2">
        <Input id={id} value={name} onChange={(e) => (setTyped(e.target.value), setState("idle"))} maxLength={40} placeholder="Your name" autoComplete="nickname" />
        <Button type="submit" variant="outline" className="shrink-0" disabled={name.trim() === sharing.myName || state === "saving"}>
          {state === "saving" ? <Loader2 className="animate-spin" /> : state === "saved" ? <Check /> : null} {state === "saved" ? "Saved" : "Save"}
        </Button>
      </div>
    </form>
  )
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(t)
  }, [copied])
  return (
    <div className="flex gap-2">
      <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-input bg-input/30 px-2.5">
        <Link2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <input
          readOnly
          value={value}
          aria-label={label}
          onFocus={(e) => e.currentTarget.select()}
          className="h-8 min-w-0 flex-1 bg-transparent font-mono text-xs outline-none"
        />
      </div>
      <Button
        variant="secondary"
        className="shrink-0"
        onClick={() => {
          navigator.clipboard.writeText(value).then(
            () => setCopied(true),
            () => toast.error("Couldn't copy the link. Select it and copy it by hand."),
          )
        }}
      >
        {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  )
}
