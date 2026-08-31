import type { ConceptStage } from "@/types"

const STAGES: { key: ConceptStage; label: string }[] = [
  { key: "creative", label: "Creative" },
  { key: "characters", label: "Characters" },
  { key: "director", label: "Director" },
  { key: "production", label: "Production" },
  { key: "review", label: "Review" },
]

export function StageStepper({ current }: { current: ConceptStage }) {
  const currentIdx = STAGES.findIndex((s) => s.key === current)

  return (
    <div className="flex items-center gap-1">
      {STAGES.map((stage, i) => {
        const isDone = i < currentIdx
        const isActive = i === currentIdx
        return (
          <div key={stage.key} className="flex items-center gap-1">
            <div
              className={`
                px-3 py-1.5 rounded-full text-xs font-medium transition-colors
                ${isActive ? "bg-primary text-primary-foreground" : ""}
                ${isDone ? "bg-primary/20 text-primary" : ""}
                ${!isDone && !isActive ? "bg-muted/10 text-muted-foreground" : ""}
              `}
            >
              {stage.label}
            </div>
            {i < STAGES.length - 1 && (
              <div
                className={`w-4 h-px ${i < currentIdx ? "bg-primary/40" : "bg-muted/20"}`}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
