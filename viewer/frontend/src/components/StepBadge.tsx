import { Badge } from "@/components/ui/badge"

interface Props {
  status: "pending" | "running" | "completed" | "failed"
}

const styles: Record<string, string> = {
  completed: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
  failed: "bg-red-500/15 text-red-400 border-red-500/25",
  running: "bg-blue-500/15 text-blue-400 border-blue-500/25 animate-pulse",
  pending: "bg-zinc-500/15 text-zinc-400 border-zinc-500/25",
}

export function StepBadge({ status }: Props) {
  return (
    <Badge className={`${styles[status]} font-mono text-xs uppercase tracking-widest`}>
      {status}
    </Badge>
  )
}
