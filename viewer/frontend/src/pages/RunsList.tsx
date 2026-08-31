import { Link } from "react-router-dom"
import { Img } from "@/components/Img"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { StatusBadge } from "@/components/StatusBadge"
import { useApi } from "@/hooks/use-api"
import type { RunListItem } from "@/types"

interface ConceptListItem {
  slug: string
  has_plan: boolean
  frame_count: number
  linked_runs: string[]
  stage?: string
  title?: string | null
}

const STAGE_CONFIG: Record<string, { label: string; color: string }> = {
  intake: { label: "Intake", color: "bg-slate-500/10 text-slate-400 border-slate-500/20" },
  creative: { label: "Creative", color: "bg-violet-500/10 text-violet-400 border-violet-500/20" },
  characters: { label: "Characters", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  director: { label: "Ready", color: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20" },
  production: { label: "Producing", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  review: { label: "Review", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
  done: { label: "Done", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
}

function StageBadge({ stage }: { stage: string }) {
  const config = STAGE_CONFIG[stage] ?? STAGE_CONFIG.intake
  return (
    <Badge variant="secondary" className={`gap-1.5 font-mono text-xs ${config.color}`}>
      {config.label}
    </Badge>
  )
}

function formatTime(seconds: number | null): string {
  if (!seconds) return ""
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

function ConceptCard({ slug, runs }: { slug: string; runs: RunListItem[] }) {
  const latest = runs[0]
  const totalCost = runs.reduce((sum, r) => sum + (r.cost ?? 0), 0)
  const totalShots = runs.reduce((sum, r) => sum + r.shot_count, 0)
  const displayName = slug.replace(/-\d{8}-\d{6}$/, "").replace(/-/g, " ")

  return (
    <Link to={`/concepts/${slug}`}>
      <Card className="bg-card/40 border-border/50 hover:border-primary/25 hover:bg-card/60 transition-all cursor-pointer">
        <CardContent className="flex gap-5">
          {latest.thumbnail ? (
            <Img
              src={latest.thumbnail}
              alt=""
              className="w-[120px] h-[120px] rounded-lg object-cover flex-shrink-0"
            />
          ) : (
            <div className="w-[120px] h-[120px] rounded-lg bg-muted/10 flex-shrink-0 flex items-center justify-center">
              <span className="text-muted-foreground text-3xl">&#9654;</span>
            </div>
          )}
          <div className="flex-1 min-w-0 flex flex-col justify-center gap-2">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold tracking-tight hover:text-primary transition-colors truncate capitalize">
                {displayName}
              </h2>
              <StatusBadge complete={latest.complete} failed={latest.failed} />
            </div>
            <p className="font-mono text-sm text-muted-foreground">
              {[
                `${totalShots} shot${totalShots !== 1 ? "s" : ""}`,
                runs.length > 1 ? `${runs.length} runs` : null,
                totalCost > 0 ? `$${totalCost.toFixed(2)}` : null,
                formatTime(latest.elapsed_s),
              ]
                .filter(Boolean)
                .join(" \u00b7 ")}
            </p>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function StageConceptCard({ concept }: { concept: ConceptListItem }) {
  const displayName = concept.title
    || concept.slug.replace(/-\d{8}-\d{6}$/, "").replace(/-/g, " ")
  const stage = concept.stage || "intake"

  return (
    <Link to={`/concepts/${concept.slug}`}>
      <Card className="bg-card/40 border-border/50 hover:border-primary/25 hover:bg-card/60 transition-all cursor-pointer">
        <CardContent className="flex gap-5">
          <div className="w-[120px] h-[120px] rounded-lg bg-muted/10 flex-shrink-0 flex items-center justify-center">
            <span className="text-muted-foreground text-2xl">
              {stage === "director" ? "🎬" : stage === "creative" ? "📝" : stage === "characters" ? "👤" : "📋"}
            </span>
          </div>
          <div className="flex-1 min-w-0 flex flex-col justify-center gap-2">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold tracking-tight hover:text-primary transition-colors truncate capitalize">
                {displayName}
              </h2>
              <StageBadge stage={stage} />
            </div>
            <p className="font-mono text-sm text-muted-foreground">
              {[
                stage === "director" ? "Ready to produce" : null,
                stage === "creative" ? "Story approved" : null,
                stage === "characters" ? "Generating characters" : null,
                stage === "intake" ? "In progress" : null,
              ].filter(Boolean).join(" \u00b7 ")}
            </p>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

export function RunsList() {
  const { data: runs, loading: runsLoading, error: runsError } = useApi<RunListItem[]>("/api/runs")
  const { data: allConcepts, loading: conceptsLoading } = useApi<ConceptListItem[]>("/api/concepts")

  const loading = runsLoading || conceptsLoading
  const error = runsError

  // Group runs by concept slug
  const conceptRuns = (runs ?? []).filter((r) => r.concept_slug)
  const grouped = new Map<string, RunListItem[]>()
  for (const run of conceptRuns) {
    const key = run.concept_slug!
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key)!.push(run)
  }
  const conceptsWithRuns = Array.from(grouped.entries())
  const slugsWithRuns = new Set(conceptsWithRuns.map(([slug]) => slug))

  // Concepts without runs (have creative/director but no production yet)
  const conceptsWithoutRuns = (allConcepts ?? []).filter(
    (c) => !slugsWithRuns.has(c.slug) && (c.stage === "creative" || c.stage === "characters" || c.stage === "director")
  )

  const hasAnything = conceptsWithRuns.length > 0 || conceptsWithoutRuns.length > 0

  return (
    <div className="min-h-screen p-8 md:p-12">
      <div className="max-w-4xl mx-auto space-y-10">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold tracking-tight">Concepts</h1>
            <div className="w-12 h-0.5 bg-primary mt-3" />
          </div>
          <Link to="/new">
            <Button size="sm">+ New Concept</Button>
          </Link>
        </div>

        {loading && (
          <div className="flex items-center gap-3 text-muted-foreground">
            <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="font-mono text-sm">Loading...</span>
          </div>
        )}

        {error && (
          <Card className="bg-rose-500/10 border-rose-500/20">
            <CardContent>
              <p className="text-rose-400 text-sm">{error}</p>
            </CardContent>
          </Card>
        )}

        {/* Concept cards — with runs first, then without runs */}
        <div className="space-y-4">
          {conceptsWithRuns.map(([slug, group]) => (
            <ConceptCard key={slug} slug={slug} runs={group} />
          ))}
          {conceptsWithoutRuns.map((concept) => (
            <StageConceptCard key={concept.slug} concept={concept} />
          ))}
        </div>

        {!hasAnything && !loading && (
          <div className="text-center py-24 text-muted-foreground">
            <p className="text-xl font-light">No concepts yet</p>
            <p className="text-sm mt-2 font-mono">Create a concept to get started</p>
          </div>
        )}
      </div>
    </div>
  )
}
