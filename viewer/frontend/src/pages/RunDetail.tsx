import { useState, useEffect, useRef } from "react"
import { useParams, Link } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { StatusBadge } from "@/components/StatusBadge"
import { CharacterCard } from "@/components/CharacterCard"
import { ShotCard } from "@/components/ShotCard"
import { CostBar } from "@/components/CostBar"
import { ConceptProgression } from "@/components/ConceptProgression"
import { PipelineGraph } from "@/components/PipelineGraph"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { useApi, triggerRerun } from "@/hooks/use-api"
import type { RunDetail as RunDetailType } from "@/types"

function formatTime(seconds: number | null | undefined): string {
  if (!seconds) return ""
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

export function RunDetail() {
  const { "*": wildcard } = useParams()
  const name = wildcard ?? ""
  const { data, loading, error, refetch } = useApi<RunDetailType>(
    `/api/runs/${name}`
  )
  const [pipelineOpen, setPipelineOpen] = useState(false)
  const [rerunningAll, setRerunningAll] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Auto-poll while any step is running
  const isRunning = data?.status && !data.status.complete && !data.status.failed
  useEffect(() => {
    if (isRunning || rerunningAll) {
      pollRef.current = setInterval(refetch, 4000)
      return () => { if (pollRef.current) clearInterval(pollRef.current) }
    }
    if (pollRef.current) clearInterval(pollRef.current)
  }, [isRunning, rerunningAll, refetch])

  // Clear rerunning state once the run completes/fails
  useEffect(() => {
    if (data?.status.complete || data?.status.failed) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRerunningAll(false)
    }
  }, [data?.status.complete, data?.status.failed])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-3 text-muted-foreground">
          <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="font-mono text-sm">Loading...</span>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="min-h-screen p-8 md:p-12">
        <div className="max-w-4xl mx-auto">
          <Link
            to="/"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            &#8592; Back
          </Link>
          <Card className="bg-rose-500/10 border-rose-500/20 mt-4">
            <CardContent>
              <p className="text-rose-400 text-sm">{error ?? "Run not found"}</p>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  const { status, pipeline, spec, assets, versions, concept } = data
  const character = spec?.character
  const allNodes = pipeline.nodes ?? []

  const anchorAsset =
    assets["anchor_frame.png"] ?? assets["frame.png"] ?? null

  const finalVideo = assets["final.mp4"] ?? null
  const costData = status.cost

  return (
    <div className="min-h-screen p-8 md:p-12">
      <div className="max-w-4xl mx-auto space-y-10">
        {/* Top bar: back + name + status + rerun */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link
                to="/"
                className="text-muted-foreground hover:text-foreground transition-colors text-lg"
              >
                &#8592;
              </Link>
              <h1 className="text-2xl font-bold tracking-tight">
                {data.run_name}
              </h1>
              <StatusBadge complete={status.complete} failed={status.failed} />
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={rerunningAll}
              onClick={async () => {
                setRerunningAll(true)
                try {
                  await triggerRerun(data.run_name)
                } catch (e) {
                  console.error(e)
                  setRerunningAll(false)
                }
              }}
              className="text-xs font-mono opacity-60 hover:opacity-100"
            >
              {rerunningAll && (
                <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin mr-1.5" />
              )}
              {rerunningAll ? "Running..." : "Re-run All"}
            </Button>
          </div>

          {/* Metadata pills */}
          <div className="flex items-center gap-3 font-mono text-sm text-muted-foreground">
            <span>{allNodes.length} steps</span>
            {formatTime(status.elapsed_s) && (
              <>
                <span className="text-border">&#183;</span>
                <span>{formatTime(status.elapsed_s)}</span>
              </>
            )}
            {costData && (
              <>
                <span className="text-border">&#183;</span>
                <span className="text-primary">${costData.total.toFixed(2)}</span>
              </>
            )}
          </div>

          {/* Cost bar */}
          {costData && costData.breakdown.length > 0 && (
            <CostBar total={costData.total} breakdown={costData.breakdown} />
          )}
        </div>

        {/* Creative Journey */}
        {concept && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
                Creative Journey
              </h2>
              <Link
                to={`/concepts/${concept.slug}`}
                className="text-xs font-mono text-primary/60 hover:text-primary transition-colors"
              >
                Compare runs &#8594;
              </Link>
            </div>
            <ConceptProgression concept={concept} />
          </div>
        )}

        {/* Character */}
        {character && (
          <div>
            <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold mb-4">
              Character
            </h2>
            <CharacterCard
              character={character}
              anchorFrameUrl={anchorAsset}
            />
          </div>
        )}

        {/* Shots */}
        <div className="space-y-5">
          <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
            Shots
          </h2>
          {allNodes
            .filter(
              (n) =>
                n.id.startsWith("video_gen") ||
                n.id.startsWith("image_gen") ||
                n.config.prompt
            )
            .map((node) => {
              const step = status.steps?.[node.id]
              const costEntry = costData?.breakdown.find(
                (b) => b.step === node.id
              )
              return (
                <ShotCard
                  key={node.id}
                  node={node}
                  stepStatus={step}
                  runName={data.run_name}
                  assets={assets}
                  costEntry={costEntry}
                  versions={versions?.[node.id]}
                  onRefresh={refetch}
                />
              )
            })}
        </div>

        {/* Final Output */}
        {finalVideo && (
          <div className="space-y-4">
            <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
              Final Output
            </h2>
            <Card className="bg-card/40 border-border/50">
              <CardContent>
                <video
                  src={finalVideo}
                  controls
                  className="w-full rounded-lg"
                  preload="none"
                />
              </CardContent>
            </Card>
          </div>
        )}

        {/* Errors */}
        {status.errors && status.errors.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-xs uppercase tracking-[0.2em] text-rose-400 font-semibold">
              Errors
            </h2>
            {status.errors.map((err, i) => (
              <Card key={i} className="bg-rose-500/10 border-rose-500/20">
                <CardContent>
                  <p className="text-xs font-mono text-rose-400">
                    <span className="font-semibold">{err.step}</span>
                    {err.retries ? ` (${err.retries} retries)` : ""}
                  </p>
                  <p className="text-xs text-rose-400/70 mt-1 break-all">
                    {err.error}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Pipeline Graph + Details */}
        <div className="space-y-4">
          <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
            Pipeline
          </h2>
          <PipelineGraph nodes={allNodes} steps={status.steps ?? {}} />

          <Collapsible open={pipelineOpen} onOpenChange={setPipelineOpen}>
            <CollapsibleTrigger className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer font-mono">
              {pipelineOpen ? "Hide node list" : "Show node list"}
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3">
              <Card className="bg-card/40">
                <CardContent className="space-y-1">
                  {allNodes.map((node) => {
                    const step = status.steps?.[node.id]
                    return (
                      <div
                        key={node.id}
                        className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-muted/10 transition-colors"
                      >
                        <span className="text-xs font-mono truncate flex-1 text-muted-foreground">
                          {node.id}
                        </span>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <Badge variant="outline" className="font-mono text-xs text-muted-foreground">
                            {node.adapter}
                          </Badge>
                          {step?.duration_s && (
                            <span className="text-xs text-muted-foreground font-mono">
                              {step.duration_s.toFixed(1)}s
                            </span>
                          )}
                          <div
                            className={`w-2 h-2 rounded-full ${
                              step?.status === "completed"
                                ? "bg-emerald-500"
                                : step?.status === "failed"
                                  ? "bg-rose-500"
                                  : step?.status === "running"
                                    ? "bg-amber-500 animate-pulse"
                                    : "bg-muted-foreground/20"
                            }`}
                          />
                        </div>
                      </div>
                    )
                  })}
                </CardContent>
              </Card>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </div>
    </div>
  )
}
