import { Shell } from "@/components/common/bits"
import { Button } from "@/components/ui/button"
import { navigate } from "@/lib/router"

export function Missing() {
  return (
    <Shell>
      <div className="py-24 text-center">
        <h1 className="font-serif text-5xl">Nothing here</h1>
        <p className="mt-3 text-muted-foreground">That page doesn't exist. The link may be mistyped.</p>
        <Button className="mt-8" onClick={() => navigate("/")}>
          Make a lesson
        </Button>
      </div>
    </Shell>
  )
}
