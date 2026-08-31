import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip"
import type { CostBreakdown } from "@/types"

interface Props {
  total: number
  breakdown: CostBreakdown[]
}

const COLORS = [
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-orange-500",
  "bg-teal-500",
  "bg-pink-500",
  "bg-lime-500",
]

export function CostBar({ total, breakdown }: Props) {
  if (total === 0) return null

  return (
    <TooltipProvider>
      <div className="flex h-1 rounded-full overflow-hidden bg-muted/20">
        {breakdown.map((entry, i) => {
          const pct = (entry.cost / total) * 100
          if (pct === 0) return null
          return (
            <Tooltip key={entry.step}>
              <TooltipTrigger
                className={`${COLORS[i % COLORS.length]} transition-all cursor-default`}
                style={{ width: `${pct}%` }}
              />
              <TooltipContent>
                <span className="font-mono text-xs">
                  {entry.step.replace(/[._]/g, " ")}: ${entry.cost.toFixed(2)}
                </span>
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
