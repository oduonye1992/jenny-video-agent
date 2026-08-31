import { useState, useEffect, useMemo } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Img } from "@/components/Img"
import { StageStepper } from "@/components/StageStepper"
import { PromptDiff } from "@/components/PromptDiff"
import {
  useApi,
  listShotVersions,
  selectShotVersion,
  getPromptDiff,
  approveShot,
  advanceConcept,
} from "@/hooks/use-api"
import type {
  Director,
  DirectorShot,
  ShotVersionDetail,
  DiffLine,
} from "@/types"

function ShotStrip({
  shots,
  selectedId,
  approvedIds,
  onSelect,
}: {
  shots: DirectorShot[]
  selectedId: string | null
  approvedIds: Set<string>
  onSelect: (id: string) => void
}) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {shots.map((shot) => {
        const isSelected = selectedId === shot.shot_id
        const isApproved = approvedIds.has(shot.shot_id)
        return (
          <button
            key={shot.shot_id}
            onClick={() => onSelect(shot.shot_id)}
            className={`relative flex-shrink-0 rounded-lg overflow-hidden transition-all ${
              isSelected
                ? "ring-2 ring-primary ring-offset-2 ring-offset-background"
                : "hover:ring-1 hover:ring-border"
            }`}
          >
            {shot.frame.generated_frame ? (
              <Img
                src={shot.frame.generated_frame}
                alt={shot.beat_name}
                className="w-20 h-14 object-cover"
              />
            ) : (
              <div className="w-20 h-14 bg-muted/20 flex items-center justify-center">
                <span className="text-xs text-muted-foreground">
                  {shot.shot_id}
                </span>
              </div>
            )}
            <div className="absolute bottom-0 inset-x-0 bg-black/60 px-1 py-0.5">
              <span className="text-xs text-white truncate block">
                {shot.beat_name}
              </span>
            </div>
            {isApproved && (
              <div className="absolute top-1 right-1 w-4 h-4 rounded-full bg-emerald-500 flex items-center justify-center">
                <span className="text-white text-[10px]">✓</span>
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}

function VersionPanel({
  slug,
  shotId,
}: {
  slug: string
  shotId: string
}) {
  const [versions, setVersions] = useState<ShotVersionDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [compareV1, setCompareV1] = useState<number | null>(null)
  const [compareV2, setCompareV2] = useState<number | null>(null)
  const [diffLines, setDiffLines] = useState<DiffLine[]>([])
  const [selecting, setSelecting] = useState(false)

  useEffect(() => {
    setLoading(true)
    setCompareV1(null)
    setCompareV2(null)
    setDiffLines([])
    listShotVersions(slug, shotId)
      .then((vs) => setVersions(vs as unknown as ShotVersionDetail[]))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [slug, shotId])

  async function handleCompare() {
    if (compareV1 == null || compareV2 == null) return
    try {
      const result = await getPromptDiff(slug, shotId, compareV1, compareV2)
      setDiffLines(result.diff_lines as unknown as DiffLine[])
    } catch (e) {
      console.error(e)
    }
  }

  async function handleSelectVersion(version: number) {
    setSelecting(true)
    try {
      await selectShotVersion(slug, shotId, version)
      const vs = (await listShotVersions(slug, shotId)) as unknown as ShotVersionDetail[]
      setVersions(vs)
    } catch (e) {
      console.error(e)
    } finally {
      setSelecting(false)
    }
  }

  if (loading)
    return (
      <div className="text-sm text-muted-foreground">Loading versions...</div>
    )
  if (versions.length === 0)
    return (
      <div className="text-sm text-muted-foreground">
        No versions generated yet.
      </div>
    )

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold">Versions</h3>

      <div className="grid grid-cols-2 gap-3">
        {versions.map((v) => (
          <Card
            key={v.version}
            className="bg-card/40 border-border/50 overflow-hidden"
          >
            <CardContent className="pt-3 space-y-2">
              <div className="flex items-center justify-between">
                <Badge variant="outline">v{v.version}</Badge>
                <div className="flex gap-1">
                  <button
                    className={`text-xs px-2 py-0.5 rounded ${
                      compareV1 === v.version
                        ? "bg-blue-500/20 text-blue-400"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    onClick={() => setCompareV1(v.version)}
                  >
                    A
                  </button>
                  <button
                    className={`text-xs px-2 py-0.5 rounded ${
                      compareV2 === v.version
                        ? "bg-amber-500/20 text-amber-400"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    onClick={() => setCompareV2(v.version)}
                  >
                    B
                  </button>
                </div>
              </div>

              {v.clip_url ? (
                <video
                  src={v.clip_url}
                  className="w-full rounded-md aspect-video object-cover"
                  controls
                  muted
                  playsInline
                />
              ) : v.frame_url ? (
                <Img
                  src={v.frame_url}
                  alt={`v${v.version}`}
                  className="w-full rounded-md aspect-video object-cover"
                />
              ) : (
                <div className="w-full aspect-video bg-muted/20 rounded-md flex items-center justify-center">
                  <span className="text-muted-foreground text-xs">
                    No media
                  </span>
                </div>
              )}

              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={selecting}
                onClick={() => handleSelectVersion(v.version)}
              >
                Select v{v.version}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Prompt diff */}
      {compareV1 != null && compareV2 != null && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">
              Comparing v{compareV1} vs v{compareV2}
            </span>
            <Button variant="outline" size="sm" onClick={handleCompare}>
              Show Diff
            </Button>
          </div>
          {diffLines.length > 0 && <PromptDiff lines={diffLines} />}
        </div>
      )}
    </div>
  )
}

export function ShotReview() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { data, loading, error, refetch } = useApi<{
    slug: string
    director: Director
    director_md: string | null
  }>(`/api/concepts/${slug}/director`)

  const [selectedShot, setSelectedShot] = useState<string | null>(null)
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set())
  const [approving, setApproving] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  // const videoRef = useRef<HTMLVideoElement>(null)

  const d = data?.director
  const shots = useMemo(() => d?.shots ?? [], [d?.shots])
  const selected = shots.find((s) => s.shot_id === selectedShot) ?? null

  // Auto-select first shot
  useEffect(() => {
    if (shots.length > 0 && !selectedShot) {
      setSelectedShot(shots[0].shot_id)
    }
  }, [shots, selectedShot])

  async function handleApproveShot() {
    if (!slug || !selectedShot) return
    setApproving(true)
    try {
      await approveShot(slug, selectedShot)
      setApprovedIds((prev) => new Set([...prev, selectedShot]))
    } catch (e) {
      console.error(e)
    } finally {
      setApproving(false)
    }
  }

  async function handleFinalize() {
    if (!slug) return
    setFinalizing(true)
    try {
      await advanceConcept(slug, "done")
      navigate(`/concepts/${slug}`)
    } catch (e) {
      console.error(e)
    } finally {
      setFinalizing(false)
    }
  }

  if (loading)
    return <div className="p-8 text-muted-foreground">Loading shots...</div>
  if (error) return <div className="p-8 text-rose-400">Error: {error}</div>
  if (!d)
    return (
      <div className="p-8 text-muted-foreground">No director plan found.</div>
    )

  const allApproved = shots.length > 0 && shots.every((s) => approvedIds.has(s.shot_id))

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-5xl mx-auto space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Shot Review</h1>
            <p className="text-muted-foreground mt-1">
              Approve each shot or compare versions.
            </p>
          </div>
          <StageStepper current="review" />
        </div>

        {/* Shot strip */}
        <ShotStrip
          shots={shots}
          selectedId={selectedShot}
          approvedIds={approvedIds}
          onSelect={setSelectedShot}
        />

        {/* Main content */}
        {selected && (
          <div className="grid grid-cols-5 gap-6">
            {/* Video / frame preview — 3 cols */}
            <div className="col-span-3 space-y-4">
              <Card className="bg-card/40 border-border/50 overflow-hidden">
                <div className="aspect-[9/16] max-h-[600px] bg-black flex items-center justify-center">
                  {selected.frame.generated_frame ? (
                    <Img
                      src={selected.frame.generated_frame}
                      alt={selected.beat_name}
                      className="max-w-full max-h-full object-contain"
                    />
                  ) : (
                    <span className="text-muted-foreground">No preview</span>
                  )}
                </div>
              </Card>

              {/* Approve / actions */}
              <div className="flex gap-2">
                <Button
                  onClick={handleApproveShot}
                  disabled={
                    approving || approvedIds.has(selected.shot_id)
                  }
                  className="flex-1"
                >
                  {approvedIds.has(selected.shot_id)
                    ? "Approved"
                    : approving
                      ? "Approving..."
                      : "Approve Shot"}
                </Button>
                <Button variant="outline" onClick={refetch}>
                  Regen
                </Button>
              </div>
            </div>

            {/* Version comparison — 2 cols */}
            <div className="col-span-2">
              <VersionPanel slug={slug!} shotId={selected.shot_id} />
            </div>
          </div>
        )}

        {/* Finalize */}
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={() => navigate(`/concepts/${slug}/progress`)}
          >
            Back
          </Button>
          <Button
            onClick={handleFinalize}
            disabled={!allApproved || finalizing}
            size="lg"
          >
            {finalizing ? "Finalizing..." : "Finalize"}
          </Button>
        </div>
      </div>
    </div>
  )
}
