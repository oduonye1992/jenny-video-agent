import type { CreativeBeat, PlanShotType } from "@/types"

const MODE_COLORS: Record<PlanShotType, string> = {
  TALKING_HEAD: "bg-blue-500/60",
  "B-ROLL": "bg-amber-500/60",
  PRODUCT: "bg-emerald-500/60",
  MONTAGE: "bg-purple-500/60",
}

const MODE_LABELS: Record<PlanShotType, string> = {
  TALKING_HEAD: "TH",
  "B-ROLL": "BR",
  PRODUCT: "PR",
  MONTAGE: "MO",
}

export function ShotTimeline({
  beats,
  selectedIndex,
  onSelect,
}: {
  beats: CreativeBeat[]
  selectedIndex: number | null
  onSelect: (index: number) => void
}) {
  const totalDuration = beats.reduce((sum, b) => sum + b.duration, 0)

  return (
    <div className="flex gap-1 h-12 rounded-lg overflow-hidden">
      {beats.map((beat, i) => {
        const widthPct = (beat.duration / totalDuration) * 100
        const isSelected = selectedIndex === i
        return (
          <button
            key={i}
            onClick={() => onSelect(i)}
            className={`
              relative flex items-center justify-center rounded-md transition-all
              ${MODE_COLORS[beat.type] || "bg-zinc-500/40"}
              ${isSelected ? "ring-2 ring-primary ring-offset-1 ring-offset-background" : ""}
              hover:brightness-110
            `}
            style={{ width: `${Math.max(widthPct, 8)}%` }}
            title={`${beat.name} · ${beat.duration}s · ${beat.type}`}
          >
            <div className="flex flex-col items-center gap-0.5 px-1 overflow-hidden">
              <span className="text-[10px] font-medium text-white/90 truncate max-w-full">
                {beat.name}
              </span>
              <span className="text-[10px] text-white/80">
                {beat.duration}s · {MODE_LABELS[beat.type] || beat.type}
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
