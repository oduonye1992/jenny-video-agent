import { Badge } from "@/components/ui/badge"

interface Props {
  complete: boolean
  failed: boolean
}

export function StatusBadge({ complete, failed }: Props) {
  if (failed) {
    return (
      <Badge variant="destructive" className="gap-1.5 font-mono text-xs">
        <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
        failed
      </Badge>
    )
  }
  if (complete) {
    return (
      <Badge variant="secondary" className="gap-1.5 font-mono text-xs bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        complete
      </Badge>
    )
  }
  return (
    <Badge variant="secondary" className="gap-1.5 font-mono text-xs bg-amber-500/10 text-amber-400 border-amber-500/20">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
      running
    </Badge>
  )
}
