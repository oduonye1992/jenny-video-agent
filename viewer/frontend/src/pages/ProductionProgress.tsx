import { useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Img } from "@/components/Img"
import { StageStepper } from "@/components/StageStepper"
import { useApi } from "@/hooks/use-api"
import type { ShotProgress, ConceptStage } from "@/types"

const STAGE_LABELS: Record<ShotProgress["stage"], string> = {
  pending: "Waiting...",
  frame: "Generating frame...",
  video: "Generating video...",
  upscale: "Upscaling...",
  complete: "Done",
  failed: "Failed",
}

const STAGE_COLORS: Record<ShotProgress["stage"], string> = {
  pending: "text-muted-foreground",
  frame: "text-blue-400",
  video: "text-amber-400",
  upscale: "text-purple-400",
  complete: "text-emerald-400",
  failed: "text-rose-400",
}

function ShotProgressCard({ shot }: { shot: ShotProgress }) {
  return (
    <Card className="bg-card/40 border-border/50">
      <CardContent className="pt-4">
        <div className="flex items-center gap-4">
          {/* Thumbnail or placeholder */}
          {shot.thumbnail_url ? (
            <Img
              src={shot.thumbnail_url}
              alt={shot.name}
              className="w-16 h-16 rounded-md object-cover flex-shrink-0"
            />
          ) : (
            <div className="w-16 h-16 rounded-md bg-muted/20 flex-shrink-0 flex items-center justify-center">
              <span className="text-muted-foreground text-xs">
                {shot.shot_id}
              </span>
            </div>
          )}

          <div className="flex-1 min-w-0 space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold truncate">{shot.name}</h3>
              <span className={`text-sm ${STAGE_COLORS[shot.stage]}`}>
                {STAGE_LABELS[shot.stage]}
              </span>
            </div>

            {/* Progress bar */}
            <div className="w-full h-1.5 rounded-full bg-muted/20 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  shot.stage === "failed"
                    ? "bg-rose-500"
                    : shot.stage === "complete"
                      ? "bg-emerald-500"
                      : "bg-primary"
                }`}
                style={{ width: `${shot.progress_pct}%` }}
              />
            </div>

            {/* Meta */}
            <div className="flex gap-3 text-xs text-muted-foreground">
              <span>{shot.shot_id}</span>
              {shot.cost > 0 && <span>${shot.cost.toFixed(2)}</span>}
              {shot.error && (
                <span className="text-rose-400 truncate">{shot.error}</span>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function ProductionProgress() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { data, loading, error, refetch } = useApi<{
    stage: ConceptStage
    shots: ShotProgress[]
    total_cost: number
    elapsed_s: number
  }>(`/api/concepts/${slug}/progress`)

  // Poll every 4 seconds while in production
  useEffect(() => {
    if (!data || data.stage !== "production") return
    const allDone = data.shots.every(
      (s) => s.stage === "complete" || s.stage === "failed"
    )
    if (allDone) return

    const interval = setInterval(refetch, 4000)
    return () => clearInterval(interval)
  }, [data, refetch])

  if (loading)
    return (
      <div className="p-8 text-muted-foreground">Loading progress...</div>
    )
  if (error) return <div className="p-8 text-rose-400">Error: {error}</div>
  if (!data)
    return <div className="p-8 text-muted-foreground">No progress data.</div>

  const completedCount = data.shots.filter(
    (s) => s.stage === "complete"
  ).length
  const failedCount = data.shots.filter((s) => s.stage === "failed").length
  const allDone = data.shots.every(
    (s) => s.stage === "complete" || s.stage === "failed"
  )

  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Production</h1>
            <p className="text-muted-foreground mt-1">
              Generating video clips for each shot.
            </p>
          </div>
          <StageStepper current="production" />
        </div>

        {/* Summary bar */}
        <div className="flex gap-4 text-sm">
          <span className="text-muted-foreground">
            {completedCount} of {data.shots.length} shots complete
          </span>
          {failedCount > 0 && (
            <Badge
              variant="outline"
              className="text-rose-400 border-rose-500/30"
            >
              {failedCount} failed
            </Badge>
          )}
          <span className="text-muted-foreground ml-auto">
            ${data.total_cost.toFixed(2)}
          </span>
          <span className="text-muted-foreground">
            {formatTime(data.elapsed_s)}
          </span>
        </div>

        {/* Overall progress */}
        <div className="w-full h-2 rounded-full bg-muted/20 overflow-hidden">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{
              width: `${data.shots.length > 0 ? (completedCount / data.shots.length) * 100 : 0}%`,
            }}
          />
        </div>

        {/* Shot cards */}
        <div className="space-y-3">
          {data.shots.map((shot) => (
            <ShotProgressCard key={shot.shot_id} shot={shot} />
          ))}
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={() => navigate(`/concepts/${slug}/director`)}
          >
            Back
          </Button>
          {allDone && failedCount === 0 && (
            <Button
              size="lg"
              onClick={() => navigate(`/concepts/${slug}/review`)}
            >
              Review Shots
            </Button>
          )}
          {allDone && failedCount > 0 && (
            <Button size="lg" variant="outline" onClick={refetch}>
              Retry Failed
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
