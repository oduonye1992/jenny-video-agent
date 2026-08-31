import { useState, useCallback, useEffect, useRef } from "react"
import { useParams, Link } from "react-router-dom"
import { Img } from "@/components/Img"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { PipelineGraph } from "@/components/PipelineGraph"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useApi, regenerateShot, triggerRerun } from "@/hooks/use-api"
import type { ConceptDetail as ConceptDetailType, ConceptRun, VideoAsset, DirectorShot } from "@/types"

/** Pretty-print a filename for display */
function prettyName(filename: string): string {
  return filename
    .replace(/\.(mp4|webm|png|jpg|jpeg)$/, "")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Collapsible prompt viewer with copy button */
function PromptToggle({ prompt, label }: { prompt: string; label?: string }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  // Try to pretty-print JSON
  let formatted = prompt
  try {
    const parsed = JSON.parse(prompt)
    formatted = JSON.stringify(parsed, null, 2)
  } catch {
    // not JSON, use as-is
  }

  const handleCopy = async () => {
    await navigator.clipboard.writeText(prompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="space-y-1.5">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-primary/60 hover:text-primary cursor-pointer border border-primary/20 rounded-md px-2.5 py-1 hover:bg-primary/5 transition-colors"
      >
        {open ? `Hide video prompt` : (label || "Show prompt")}
      </button>
      {open && (
        <>
          <pre className="text-xs text-muted-foreground font-mono whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto bg-muted/5 rounded-md p-3">
            {formatted}
          </pre>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            className="text-xs text-primary/60 hover:text-primary h-auto px-0 py-0"
          >
            {copied ? "Copied!" : "Copy"}
          </Button>
        </>
      )}
    </div>
  )
}

/** Exclusive prompt viewer — video or anchor, one at a time */
function PromptSwitcher({ videoPrompt, anchorPrompt }: { videoPrompt?: string; anchorPrompt?: string }) {
  const [active, setActive] = useState<"video" | "anchor" | null>(null)

  const togglePrompt = (type: "video" | "anchor") => {
    setActive((prev) => (prev === type ? null : type))
  }

  return (
    <div className="space-y-1.5">
      <div className="flex gap-2">
        {videoPrompt && (
          <button
            onClick={() => togglePrompt("video")}
            className={`text-xs cursor-pointer border rounded-md px-2.5 py-1 transition-colors ${
              active === "video"
                ? "text-primary border-primary/40 bg-primary/5"
                : "text-primary/60 border-primary/20 hover:text-primary hover:bg-primary/5"
            }`}
          >
            {active === "video" ? "Hide video prompt" : "Video prompt"}
          </button>
        )}
        {anchorPrompt && (
          <button
            onClick={() => togglePrompt("anchor")}
            className={`text-xs cursor-pointer border rounded-md px-2.5 py-1 transition-colors ${
              active === "anchor"
                ? "text-primary border-primary/40 bg-primary/5"
                : "text-primary/60 border-primary/20 hover:text-primary hover:bg-primary/5"
            }`}
          >
            {active === "anchor" ? "Hide anchor prompt" : "Anchor prompt"}
          </button>
        )}
      </div>
      {active === "video" && videoPrompt && (
        <PromptContent prompt={videoPrompt} />
      )}
      {active === "anchor" && anchorPrompt && (
        <PromptContent prompt={anchorPrompt} />
      )}
    </div>
  )
}

/** Prompt content block with copy */
function PromptContent({ prompt }: { prompt: string }) {
  const [copied, setCopied] = useState(false)
  let formatted = prompt
  try {
    formatted = JSON.stringify(JSON.parse(prompt), null, 2)
  } catch { /* not JSON */ }

  return (
    <div className="space-y-1.5">
      <pre className="text-xs text-muted-foreground font-mono whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto bg-muted/5 rounded-md p-3">
        {formatted}
      </pre>
      <button
        onClick={async () => {
          await navigator.clipboard.writeText(prompt)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
        className="text-xs text-primary/60 hover:text-primary cursor-pointer border border-primary/20 rounded-md px-2.5 py-1 hover:bg-primary/5 transition-colors"
      >
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  )
}

/** Find the video_gen node_id, prompt, and adapter for a shot video asset */
function findShotNode(video: VideoAsset, run?: ConceptRun): { nodeId: string; prompt: string; adapter: string } | null {
  if (!run?.shots) return null
  for (const shot of run.shots) {
    // Match by URL (output or upscaled)
    const videoFilename = video.url.split("/").pop() ?? ""
    const shotOutput = shot.output_url?.split("/").pop() ?? ""
    const shotUpscaled = shot.upscaled_url?.split("/").pop() ?? ""
    if (videoFilename && (videoFilename === shotOutput || videoFilename === shotUpscaled)) {
      return { nodeId: shot.node_id, prompt: shot.prompt, adapter: shot.adapter }
    }
  }
  return null
}

/** Videos + pipeline + prompts for a single run */
function RunVideos({
  group,
  run,
  slug,
  onRegenerate,
  regenerating,
}: {
  group: { label: string; finals: VideoAsset[]; shots: VideoAsset[]; hidden: VideoAsset[] }
  run?: ConceptRun
  slug: string
  onRegenerate: (newRunLabel: string) => void
  regenerating?: boolean
}) {
  const [finalOpen, setFinalOpen] = useState(true)
  const [shotsOpen, setShotsOpen] = useState(true)
  const [pipelineOpen, setPipelineOpen] = useState(false)
  const [selectedShotIdx, setSelectedShotIdx] = useState(0)
  const [regenTarget, setRegenTarget] = useState<string | null>(null) // node_id being edited
  const [regenPrompt, setRegenPrompt] = useState("")
  const [regenLoading, setRegenLoading] = useState(false)
  const [regenError, setRegenError] = useState<string | null>(null)
  const [retryLoading, setRetryLoading] = useState(false)
  const [musicRegenOpen, setMusicRegenOpen] = useState(false)
  const [musicRegenPrompt, setMusicRegenPrompt] = useState("")
  const [musicRegenLoading, setMusicRegenLoading] = useState(false)
  const [shotPromptsOpen, setShotPromptsOpen] = useState(false)

  const isIncomplete = run ? (!run.complete && !run.failed) : false
  const isFailed = run?.failed ?? false

  // For incomplete/failed runs, filter out cached shots (only show newly generated ones)
  const visibleShots = (isFailed || isIncomplete)
    ? group.shots.filter((v) => {
        const node = findShotNode(v, run)
        if (!node) return false
        const stepStatus = run?.status?.steps?.[node.nodeId]
        const upscaleId = node.nodeId.replace("video_gen", "upscale")
        const upscaleStatus = run?.status?.steps?.[upscaleId]
        // Show if this shot's video_gen completed, or its upscale ran (even if failed)
        return stepStatus?.status === "completed" || upscaleStatus?.status === "failed" || upscaleStatus?.status === "completed"
      })
    : group.shots

  if (group.finals.length === 0 && visibleShots.length === 0 && !isIncomplete) return null

  const hasPipeline = run?.pipeline?.nodes && run.pipeline.nodes.length > 0

  const handleRegenerate = async () => {
    if (!regenTarget || !slug || !group.label) return
    setRegenLoading(true)
    setRegenError(null)
    try {
      const result = await regenerateShot(slug, regenTarget, group.label, regenPrompt || undefined)
      setRegenTarget(null)
      setRegenPrompt("")
      // Refetch concept data and switch to the new run tab
      onRegenerate(result.new_run)
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Regeneration failed")
    } finally {
      setRegenLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Regenerating indicator */}
      {regenerating && (
        <Card className="bg-primary/5 border-primary/20">
          <CardContent className="flex items-center gap-3 py-3">
            <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-primary/80">Regenerating shot...</span>
          </CardContent>
        </Card>
      )}

      {/* Run summary */}
      {run && (() => {
        const adapters = [...new Set(run.shots.map((s) => s.adapter).filter(Boolean))]
        const cost = run.total_cost ?? run.estimated_cost
        return (
          <div className="space-y-1.5">
            <h3 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
              Summary
            </h3>
            <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground font-mono">
              {run.shots.length > 0 && (
                <span>🎬 {run.shots.length} shot{run.shots.length !== 1 ? "s" : ""}</span>
              )}
              {adapters.length > 0 && <span className="text-border">·</span>}
              {adapters.map((a, i) => (
                <span key={a} className="inline-flex items-center gap-2">
                  <Badge variant="outline" className="text-xs font-mono text-primary/60 border-primary/20">
                    🔧 {a}
                  </Badge>
                  {i < adapters.length - 1 ? null : null}
                </span>
              ))}
              {run.elapsed_s != null && (
                <>
                  <span className="text-border">·</span>
                  <span>⏱ {run.elapsed_s < 60 ? `${Math.round(run.elapsed_s)}s` : `${Math.floor(run.elapsed_s / 60)}m ${Math.round(run.elapsed_s % 60)}s`}</span>
                </>
              )}
              {cost != null && (
                <>
                  <span className="text-border">·</span>
                  <span>
                    💰 {run.total_cost == null ? "~" : ""}${cost.toFixed(2)}
                  </span>
                </>
              )}
              {(run.complete || run.failed) && <span className="text-border">·</span>}
              {run.complete && <span className="text-emerald-400">✅ complete</span>}
              {run.failed && <span className="text-rose-400">❌ failed</span>}
              {!run.complete && !run.failed && <span className="text-border">·</span>}
              {!run.complete && !run.failed && <span className="text-amber-400">⏳ running</span>}
            </div>
            {/* Error details */}
            {run.failed && run.status?.errors && run.status.errors.length > 0 && (
              <div className="space-y-1 mt-2">
                {run.status.errors.map((err, i) => (
                  <div key={i} className="text-xs text-rose-400/80 bg-rose-400/5 border border-rose-400/10 rounded-md px-3 py-2 font-mono">
                    <span className="text-rose-400 font-semibold">{err.step}</span>
                    <span className="text-rose-400/50 mx-1.5">→</span>
                    {err.error}
                  </div>
                ))}
              </div>
            )}
            {/* Retry button for failed runs */}
            {run.failed && (
              <Button
                variant="outline"
                size="sm"
                className="text-xs border-rose-400/20 text-rose-400 hover:text-rose-300 hover:bg-rose-400/5 mt-2"
                disabled={retryLoading}
                onClick={async () => {
                  setRetryLoading(true)
                  try {
                    await triggerRerun(run.run_name)
                    onRegenerate(run.label)
                  } catch {
                    // best effort
                  } finally {
                    setRetryLoading(false)
                  }
                }}
              >
                {retryLoading ? "Retrying..." : "Retry Failed Steps"}
              </Button>
            )}
          </div>
        )
      })()}

      {/* Music player — if this run has a music asset or a music node */}
      {run && (() => {
        const musicUrl = run.assets ? Object.entries(run.assets).find(([k]) => k.endsWith(".mp3") || k.endsWith(".wav")) : null
        const musicNode = run.pipeline?.nodes?.find((n) => n.id === "music" || n.adapter === "elevenlabs_music")
        const musicPrompt = musicNode?.config?.prompt as string | undefined
        if (!musicUrl && !musicNode) return null
        return (
          <div className="space-y-1.5">
            <h3 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
              Music
            </h3>
            {musicUrl && (
              <div className="flex items-center gap-3">
                <audio src={musicUrl[1]} controls preload="metadata" className="h-8 flex-1" />
                <span className="text-xs text-muted-foreground font-mono flex-shrink-0">{musicUrl[0]}</span>
              </div>
            )}
            {!musicRegenOpen ? (
              <div className="flex items-center gap-2">
                {musicPrompt && (
                  <PromptToggle prompt={musicPrompt} label="Show music prompt" />
                )}
                <button
                  onClick={() => {
                    setMusicRegenOpen(true)
                    setMusicRegenPrompt(musicPrompt || "")
                  }}
                  disabled={regenerating}
                  className="text-xs cursor-pointer border border-primary/20 rounded-md px-2.5 py-1 text-primary/60 hover:text-primary hover:bg-primary/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Regenerate music
                </button>
              </div>
            ) : (
              <div className="space-y-2 pt-1 border-t border-border/30">
                <label className="text-xs text-muted-foreground font-mono">Music prompt</label>
                <Textarea
                  value={musicRegenPrompt}
                  onChange={(e) => setMusicRegenPrompt(e.target.value)}
                  rows={4}
                  className="text-xs font-mono bg-muted/10 border-border/40 resize-y"
                />
                <p className="text-xs text-muted-foreground">
                  Re-runs only the music step. Other steps are cached.
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    className="text-xs h-7"
                    disabled={musicRegenLoading}
                    onClick={async () => {
                      if (!run.run_name) return
                      setMusicRegenLoading(true)
                      try {
                        await triggerRerun(run.run_name, "music")
                        onRegenerate(group.label)
                        setMusicRegenOpen(false)
                      } catch {
                        // best effort
                      } finally {
                        setMusicRegenLoading(false)
                      }
                    }}
                  >
                    {musicRegenLoading ? "Regenerating..." : "Regenerate Music"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs h-7 text-muted-foreground"
                    onClick={() => setMusicRegenOpen(false)}
                    disabled={musicRegenLoading}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {/* Shot prompts — shown for failed/running runs where no video is available yet */}
      {(isFailed || isIncomplete) && run?.shots && run.shots.filter((s) => s.prompt).length > 0 && (
        <Collapsible open={shotPromptsOpen} onOpenChange={setShotPromptsOpen}>
          <CollapsibleTrigger className="flex items-center gap-2 cursor-pointer group">
            <h3 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold group-hover:text-foreground transition-colors">
              Shot Prompts
            </h3>
            <span className="text-muted-foreground text-xs">{shotPromptsOpen ? "−" : "+"}</span>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3 space-y-2">
            {run.shots.filter((s) => s.prompt).map((shot) => (
              <Card key={shot.node_id} className="bg-card/40 border-border/50">
                <CardContent className="space-y-1.5 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold">{prettyName(shot.node_id)}</span>
                    <Badge variant="outline" className="text-[10px] font-mono text-primary/60 border-primary/20">
                      {shot.adapter}
                    </Badge>
                    {shot.status === "failed" && (
                      <Badge variant="outline" className="text-[10px] font-mono text-rose-400 border-rose-400/20">
                        failed
                      </Badge>
                    )}
                    {shot.status === "running" && (
                      <Badge variant="outline" className="text-[10px] font-mono text-amber-400 border-amber-400/20">
                        running
                      </Badge>
                    )}
                    {shot.status === "pending" && (
                      <Badge variant="outline" className="text-[10px] font-mono text-muted-foreground border-border/40">
                        pending
                      </Badge>
                    )}
                  </div>
                  <PromptToggle prompt={shot.prompt} label="Show prompt" />
                </CardContent>
              </Card>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Final assembled video — hide for failed/running runs (no valid assembled cut) */}
      {group.finals.length > 0 && !isFailed && !isIncomplete && (
        <Collapsible open={finalOpen} onOpenChange={setFinalOpen}>
          <CollapsibleTrigger className="flex items-center gap-2 cursor-pointer group">
            <h3 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold group-hover:text-foreground transition-colors">
              Final
            </h3>
            <span className="text-muted-foreground text-xs">{finalOpen ? "−" : "+"}</span>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3 space-y-3">
            {group.finals.map((video) => (
              <Card key={video.filename} className="bg-card/40 border-border/50 overflow-hidden">
                <div className="p-4 pb-0">
                  <video src={video.url} controls className="max-h-[400px] w-auto mx-auto rounded-lg" preload="metadata" />
                </div>
                <CardContent className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold">{prettyName(video.filename)}</span>
                    <span className="text-xs text-muted-foreground font-mono">
                      {video.size_mb}MB
                    </span>
                  </div>
                  {video.prompt && <PromptToggle prompt={video.prompt} label="Show video prompt" />}
                </CardContent>
              </Card>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Individual shot clips — YouTube-style: selected player left, shot list right */}
      {visibleShots.length > 0 && (() => {
        const selectedVideo = visibleShots[selectedShotIdx] ?? visibleShots[0]
        const selectedNode = findShotNode(selectedVideo, run)
        const isRegenTarget = regenTarget === selectedNode?.nodeId

        return (
          <Collapsible open={shotsOpen} onOpenChange={setShotsOpen}>
            <CollapsibleTrigger className="flex items-center gap-2 cursor-pointer group">
              <h3 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold group-hover:text-foreground transition-colors">
                Shots
              </h3>
              <span className="text-muted-foreground text-xs">{shotsOpen ? "−" : "+"}</span>
              {!shotsOpen && (
                <span className="text-xs text-muted-foreground">
                  {visibleShots.length} clip{visibleShots.length !== 1 ? "s" : ""}
                </span>
              )}
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3">
              <div className="flex gap-4">
                {/* Left: selected shot player */}
                <div className="flex-1 min-w-0">
                  <Card className="bg-card/40 border-border/50 overflow-hidden">
                    <div className="p-4 pb-0 flex gap-3">
                      {selectedVideo.anchor_url && (
                        <a
                          href={selectedVideo.anchor_url}
                          download
                          className="flex-shrink-0 w-16 group/anchor"
                          title="Download anchor frame"
                        >
                          <Img
                            src={selectedVideo.anchor_url}
                            alt="anchor"
                            className="w-16 h-auto rounded-md object-cover opacity-70 group-hover/anchor:opacity-100 transition-opacity"
                          />
                          <span className="text-xs text-muted-foreground block text-center mt-1">anchor</span>
                        </a>
                      )}
                      <video
                        key={selectedVideo.url}
                        src={selectedVideo.url}
                        controls
                        className="max-h-[500px] w-auto mx-auto rounded-lg"
                        preload="metadata"
                      />
                    </div>
                    <CardContent className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold">
                          <span className="text-muted-foreground mr-1.5">#{selectedShotIdx + 1}</span>
                          {prettyName(selectedVideo.filename)}
                        </span>
                        <div className="flex items-center gap-2">
                          {selectedNode?.adapter && (
                            <Badge variant="outline" className="text-xs font-mono text-primary/60 border-primary/20">
                              {selectedNode.adapter}
                            </Badge>
                          )}
                          <span className="text-xs text-muted-foreground font-mono">
                            {selectedVideo.size_mb}MB
                          </span>
                          {selectedNode && !isRegenTarget && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="text-xs text-primary/60 hover:text-primary border-primary/20 h-auto px-2.5 py-1"
                              onClick={() => {
                                setRegenTarget(selectedNode.nodeId)
                                setRegenPrompt(selectedNode.prompt)
                                setRegenError(null)
                              }}
                            >
                              Regenerate
                            </Button>
                          )}
                        </div>
                      </div>
                      {!isRegenTarget && (() => {
                        const videoPrompt = selectedVideo.prompt || selectedNode?.prompt
                        const anchorPrompt = selectedVideo.anchor_prompt
                        if (!videoPrompt && !anchorPrompt) return null
                        return (
                          <PromptSwitcher
                            videoPrompt={videoPrompt || undefined}
                            anchorPrompt={anchorPrompt || undefined}
                          />
                        )
                      })()}

                      {/* Inline regeneration editor */}
                      {isRegenTarget && (
                        <div className="space-y-2 pt-1 border-t border-border/30">
                          <label className="text-xs text-muted-foreground font-mono">Prompt</label>
                          <Textarea
                            value={regenPrompt}
                            onChange={(e) => setRegenPrompt(e.target.value)}
                            rows={6}
                            className="text-xs font-mono bg-muted/10 border-border/40 resize-y"
                          />
                          <p className="text-xs text-muted-foreground">
                            Creates a new run — only this shot + upscale re-runs. Other shots are cached.
                          </p>
                          {regenError && (
                            <p className="text-xs text-rose-400">{regenError}</p>
                          )}
                          <div className="flex items-center gap-2">
                            <Button
                              size="sm"
                              className="text-xs h-7"
                              onClick={handleRegenerate}
                              disabled={regenLoading}
                            >
                              {regenLoading ? "Regenerating..." : "Regenerate Shot"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-xs h-7 text-muted-foreground"
                              onClick={() => { setRegenTarget(null); setRegenError(null) }}
                              disabled={regenLoading}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>

                {/* Right: shot list (scrollable) */}
                {visibleShots.length >= 1 && (
                  <div className="w-72 flex-shrink-0">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-xs uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                        All Shots
                      </h4>
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {selectedShotIdx + 1} / {visibleShots.length}
                      </span>
                    </div>
                    <ScrollArea className="h-[540px] rounded-none [&_[data-slot=scroll-area-viewport]]:!outline-none [&_[data-slot=scroll-area-viewport]]:!ring-0 [&_[data-slot=scroll-area-viewport]]:!rounded-none [&_[data-slot=scroll-area-viewport]]:!shadow-none">
                      <div className="space-y-2 pr-2">
                        {visibleShots.map((video, idx) => {
                          const node = findShotNode(video, run)
                          const isActive = idx === selectedShotIdx
                          return (
                            <button
                              key={video.filename}
                              className={`w-full text-left rounded-lg border p-2 transition-colors cursor-pointer ${
                                isActive
                                  ? "border-primary/50 bg-primary/10 ring-1 ring-primary/30"
                                  : "border-border/30 bg-card/30 hover:bg-card/60 hover:border-border/50"
                              }`}
                              onClick={() => setSelectedShotIdx(idx)}
                            >
                              <div className="flex gap-2.5 items-start">
                                {/* Shot number indicator */}
                                <div className={`flex-shrink-0 w-5 h-5 mt-0.5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                                  isActive
                                    ? "bg-primary/80 text-primary-foreground"
                                    : "bg-muted/40 text-muted-foreground"
                                }`}>
                                  {idx + 1}
                                </div>
                                <div className="flex-shrink-0 w-24 h-16 rounded overflow-hidden bg-muted/20">
                                  <video
                                    src={video.url}
                                    className="w-full h-full object-cover"
                                    preload="metadata"
                                    muted
                                  />
                                </div>
                                <div className="flex-1 min-w-0 py-0.5">
                                  <p className={`text-xs font-medium leading-tight ${isActive ? "text-foreground" : "text-muted-foreground"}`}>
                                    {prettyName(video.filename)}
                                  </p>
                                  {node?.adapter && (
                                    <p className="text-[10px] text-muted-foreground font-mono truncate mt-1">
                                      {node.adapter}
                                    </p>
                                  )}
                                  <p className="text-[10px] text-muted-foreground mt-0.5">
                                    {video.size_mb}MB
                                  </p>
                                </div>
                              </div>
                            </button>
                          )
                        })}
                      </div>
                      <ScrollBar orientation="vertical" />
                    </ScrollArea>
                  </div>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )
      })()}

      {/* Pipeline graph (scoped to this run) */}
      {hasPipeline && (
        <Collapsible open={pipelineOpen} onOpenChange={setPipelineOpen}>
          <CollapsibleTrigger className="flex items-center gap-2 cursor-pointer group">
            <h3 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold group-hover:text-foreground transition-colors">
              Pipeline
            </h3>
            <span className="text-muted-foreground text-xs">{pipelineOpen ? "−" : "+"}</span>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3">
            <Card className="bg-card/40 border-border/50">
              <CardContent>
                <PipelineGraph
                  nodes={run!.pipeline!.nodes}
                  steps={run!.status?.steps ?? {}}
                />
              </CardContent>
            </Card>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

export function ConceptDetail() {
  const { slug } = useParams()
  const { data, loading, error, refetch } = useApi<ConceptDetailType>(`/api/concepts/${slug}`)
  const [directorOpen, setDirectorOpen] = useState(false)
  const [characterOpen, setCharacterOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<string | null>(null)
  const [regeneratingRun, setRegeneratingRun] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // On load, resume polling if any run is actively running (has a started timestamp or running steps)
  useEffect(() => {
    if (!data || regeneratingRun) return
    const inProgress = data.runs?.find((r) => {
      if (r.complete || r.failed) return false
      // Must have actually started — not just an un-executed pipeline
      const hasStarted = r.status?.started
      const hasRunningStep = r.status?.steps && Object.values(r.status.steps).some(
        (s) => s.status === "running"
      )
      return hasStarted || hasRunningStep
    })
    if (inProgress) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRegeneratingRun(inProgress.label)
    }
  }, [data?.runs?.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Poll for updates while a run is regenerating
  useEffect(() => {
    if (!regeneratingRun) return
    pollRef.current = setInterval(() => {
      refetch()
    }, 30000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [regeneratingRun, refetch])

  // Stop polling when the regenerating run completes
  useEffect(() => {
    if (!regeneratingRun || !data) return
    const run = data.runs?.find((r) => r.label === regeneratingRun)
    if (run && (run.complete || run.failed)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRegeneratingRun(null)
    }
  }, [regeneratingRun, data])

  const handleRegenerated = useCallback((newRunLabel: string) => {
    setRegeneratingRun(newRunLabel)
    setActiveTab(newRunLabel)
    refetch()
  }, [refetch])

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
        <div className="max-w-6xl mx-auto">
          <Link to="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
            &#8592; Back
          </Link>
          <Card className="bg-rose-500/10 border-rose-500/20 mt-4">
            <CardContent>
              <p className="text-rose-400 text-sm">{error ?? "Concept not found"}</p>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  const runs = data.runs ?? []
  const creative = data.creative
  const shotDetails = data.shot_details ?? []
  const videoAssets = data.video_assets ?? []

  // Pretty title
  const displayTitle = creative?.title
    || slug?.replace(/-\d{8}-\d{6}$/, "").replace(/-/g, " ") || slug

  // Group videos by run_label, then categorize within each group:
  // - final: the assembled cut (final*.mp4)
  // - shots: individual shot clips (upscaled versions preferred)
  // - raw: pre-upscale duplicates (hidden behind toggle)
  const runLabels = [...new Set(videoAssets.map((v) => v.run_label || "ungrouped"))]
  const videosByRun = runLabels.map((label) => {
    const assets = videoAssets.filter((v) => (v.run_label || "ungrouped") === label)
    let finals = assets.filter((v) => v.filename.startsWith("final"))
    const nonFinal = assets.filter((v) => !v.filename.startsWith("final") && !v.filename.includes("thumb"))

    // Split non-final clips: if an upscaled version exists, the raw version is a duplicate
    // Upscaled files typically contain "upscale" in the name
    const upscaled = nonFinal.filter((v) => v.filename.includes("upscale"))
    const raw = nonFinal.filter((v) => !v.filename.includes("upscale"))

    // If we have upscaled versions, show those as shots and hide raw as duplicates
    // If no upscaled versions, show raw as the shots
    const shots = upscaled.length > 0 ? upscaled : raw
    const hidden = upscaled.length > 0 ? raw : []

    // Single-shot pipeline: no merge step produces a final*.mp4,
    // so duplicate the lone clip into the final/hero position too
    if (finals.length === 0 && shots.length === 1) {
      finals = [...shots]
    }

    return { label, finals, shots, hidden }
  })

  // Ensure in-progress runs appear as tabs even if they have no video assets yet
  for (const run of runs) {
    if (!run.complete && !run.failed && !videosByRun.find((g) => g.label === run.label)) {
      videosByRun.push({ label: run.label, finals: [], shots: [], hidden: [] })
    }
  }

  return (
    <div className="min-h-screen p-8 md:p-12">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <Link to="/" className="text-muted-foreground hover:text-foreground transition-colors text-lg">
              &#8592;
            </Link>
            <h1 className="text-3xl font-bold tracking-tight capitalize">{displayTitle}</h1>
          </div>

          {creative?.angle && (
            <p className="text-lg text-muted-foreground italic leading-relaxed max-w-2xl">
              &ldquo;{creative.angle}&rdquo;
            </p>
          )}

          {data.input && (
            <div className="text-sm text-muted-foreground space-y-1.5 max-w-2xl">
              <h3 className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Input</h3>
              {data.input.brief && (
                <p className="leading-relaxed">{data.input.brief}</p>
              )}
              {data.input.source_url && (
                <p className="font-mono text-xs">
                  Source:{" "}
                  <a
                    href={data.input.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary/60 hover:text-primary underline underline-offset-2"
                  >
                    {data.input.source_url}
                  </a>
                </p>
              )}
            </div>
          )}

        </div>

        <hr className="border-border/30" />

        {/* ── VIDEO OUTPUTS (primary content — what the user came to see) ── */}
        {videosByRun.length === 1 ? (
          // Single run — no tabs needed
          <RunVideos
            group={videosByRun[0]}
            run={runs.find((r) => r.label === videosByRun[0].label)}
            slug={slug!}
            onRegenerate={handleRegenerated}
            regenerating={regeneratingRun === videosByRun[0].label}
          />
        ) : videosByRun.length > 1 ? (
          // Multiple runs — tabbed interface for instant comparison
          <Tabs
            value={activeTab || videosByRun[videosByRun.length - 1].label}
            onValueChange={setActiveTab}
            className="space-y-4"
          >
            <TabsList className="bg-muted/30 border border-border/40">
              {videosByRun.map((group) => (
                <TabsTrigger key={group.label} value={group.label} className="text-xs font-mono gap-2">
                  {group.label}
                  {regeneratingRun === group.label && (
                    <div className="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  )}
                </TabsTrigger>
              ))}
            </TabsList>
            {videosByRun.map((group) => (
              <TabsContent key={group.label} value={group.label}>
                <RunVideos
                  group={group}
                  run={runs.find((r) => r.label === group.label)}
                  slug={slug!}
                  onRegenerate={handleRegenerated}
                  regenerating={regeneratingRun === group.label}
                />
              </TabsContent>
            ))}
          </Tabs>
        ) : null}

        {/* ── CREATIVE CONTEXT (collapsible — reference, not primary) ── */}
        <hr className="border-border/30" />

        {/* Character + Anchor Frames */}
        {(creative?.character || shotDetails.some((s) => s.anchors && s.anchors.length > 0)) && (
          <Collapsible open={characterOpen} onOpenChange={setCharacterOpen}>
            <CollapsibleTrigger className="flex items-center gap-2 cursor-pointer group">
              <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold group-hover:text-foreground transition-colors">
                Character
              </h2>
              <span className="text-muted-foreground text-xs">{characterOpen ? "−" : "+"}</span>
              {creative?.character && !characterOpen && (
                <span className="text-xs text-muted-foreground">
                  {creative.character.name} · {creative.character.age}
                </span>
              )}
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-4 space-y-4">
              {creative?.character && (
                <div className="space-y-1">
                  <h3 className="text-base font-semibold">{creative.character.name}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {[creative.character.age, creative.character.ethnicity, creative.character.hair].filter(Boolean).join(" · ")}
                  </p>
                  {creative.character.wardrobe && (
                    <p className="text-[12px] text-muted-foreground">{creative.character.wardrobe}</p>
                  )}
                </div>
              )}

              {shotDetails.some((s) => s.anchors && s.anchors.length > 0) && (
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  {shotDetails.flatMap((shot) =>
                    (shot.anchors ?? []).map((anchor) => (
                      <Card key={`${shot.shot_id}-${anchor.name}`} className="bg-card/40 border-border/50 overflow-hidden">
                        <div className="p-3 pb-0">
                          <Img
                            src={anchor.url}
                            alt={anchor.name}
                            className="w-full rounded-md object-contain max-h-[300px]"
                          />
                        </div>
                        <CardContent className="space-y-2">
                          <span className="text-[12px] font-mono text-muted-foreground">{anchor.name}</span>
                          {anchor.prompt && <PromptToggle prompt={anchor.prompt} label="Show image prompt" />}
                        </CardContent>
                      </Card>
                    ))
                  )}
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Legacy character refs */}
        {data.character_refs && data.character_refs.length > 0 && !creative?.character && (
          <div className="space-y-4">
            <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
              Character References
            </h2>
            <ScrollArea className="w-full">
              <div className="flex gap-3 pb-3">
                {data.character_refs.map((ref) => (
                  <Img key={ref.name} src={ref.url} alt={ref.name}
                    className="h-[180px] w-auto rounded-md object-cover flex-shrink-0" />
                ))}
              </div>
              <ScrollBar orientation="horizontal" />
            </ScrollArea>
          </div>
        )}

        {/* Legacy frames */}
        {data.frames && data.frames.length > 0 && (
          <div className="space-y-4">
            <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold">
              Starting Frames
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {data.frames.map((frame) => (
                <Card key={frame.name} className="bg-card/40 border-border/50 overflow-hidden">
                  <div className="p-3 pb-0">
                    <Img src={frame.url} alt={frame.name} className="w-full rounded-md object-contain max-h-[240px]" />
                  </div>
                  <CardContent className="space-y-2">
                    <span className="text-[12px] font-mono text-muted-foreground">{frame.name}</span>
                    {frame.prompt && <PromptToggle prompt={frame.prompt} label="Show image prompt" />}
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Director Details (collapsible) */}
        {data.director && (
          <Collapsible open={directorOpen} onOpenChange={setDirectorOpen}>
            <CollapsibleTrigger className="flex items-center gap-2 cursor-pointer group">
              <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-semibold group-hover:text-foreground transition-colors">
                Production Details
              </h2>
              <span className="text-muted-foreground text-xs">{directorOpen ? "−" : "+"}</span>
              {!directorOpen && data.director && (
                <span className="text-xs text-muted-foreground">
                  {data.director.shots.length} shot{data.director.shots.length !== 1 ? "s" : ""} · {data.director.aspect_ratio} · {data.director.profile}
                </span>
              )}
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-4 space-y-3">
              {data.director.shots.map((shot: DirectorShot, shotIdx: number) => (
                  <Card key={shot.shot_id} className="bg-card/40 border-border/50">
                    <CardContent className="space-y-3">
                      {/* Shot header */}
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs text-muted-foreground font-mono">#{shotIdx + 1}</span>
                        <span className="text-sm font-semibold">{shot.beat_name}</span>
                        <Badge variant="outline" className="text-xs text-muted-foreground font-mono">
                          {shot.beat_role}
                        </Badge>
                        <Badge variant="outline" className="text-xs font-mono">
                          {shot.type}
                        </Badge>
                        <span className="text-xs text-muted-foreground font-mono">{shot.duration}s</span>
                        {shot.audio?.strategy && (
                          <Badge variant="outline" className="text-xs font-mono text-primary/50 border-primary/20">
                            {shot.audio.strategy.replace(/_/g, " ")}
                          </Badge>
                        )}
                      </div>

                      {/* Action / choreography */}
                      {shot.action && (
                        <div className="space-y-1">
                          <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Action</span>
                          <p className="text-sm text-foreground/90 leading-relaxed italic border-l-2 border-primary/20 pl-3">
                            {shot.action}
                          </p>
                        </div>
                      )}

                      {/* Dialogue */}
                      {shot.audio?.dialogue && (
                        <div className="space-y-1">
                          <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Dialogue</span>
                          <p className="text-sm text-foreground/80 leading-relaxed">
                            &ldquo;{shot.audio.dialogue}&rdquo;
                          </p>
                          {shot.audio.dialogue_delivery && (
                            <p className="text-xs text-muted-foreground">{shot.audio.dialogue_delivery}</p>
                          )}
                        </div>
                      )}

                      {/* Voiceover (b-roll / voiceover_plus_music shots) */}
                      {shot.audio?.voiceover && (
                        <div className="space-y-1">
                          <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Voiceover</span>
                          <p className="text-sm text-foreground/80 leading-relaxed">
                            &ldquo;{shot.audio.voiceover}&rdquo;
                          </p>
                          {shot.audio.voiceover_delivery && (
                            <p className="text-xs text-muted-foreground">{shot.audio.voiceover_delivery}</p>
                          )}
                          {(shot as DirectorShot & { visual_vo_relationship?: string }).visual_vo_relationship && (
                            <p className="text-xs text-muted-foreground font-mono">
                              VO relationship: {(shot as DirectorShot & { visual_vo_relationship?: string }).visual_vo_relationship!.replace(/_/g, " ")}
                            </p>
                          )}
                        </div>
                      )}

                      {/* Character */}
                      {shot.character && (
                        <div className="space-y-1">
                          <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Character</span>
                          <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                            <span className="text-muted-foreground font-medium">Name</span>
                            <span className="text-foreground/70">{shot.character.name}</span>
                            {shot.character.physical_description && (
                              <>
                                <span className="text-muted-foreground font-medium">Description</span>
                                <span className="text-foreground/70">{shot.character.physical_description}</span>
                              </>
                            )}
                            {shot.character.wardrobe && (
                              <>
                                <span className="text-muted-foreground font-medium">Wardrobe</span>
                                <span className="text-foreground/70">{shot.character.wardrobe}</span>
                              </>
                            )}
                            {shot.character.accessories && (
                              <>
                                <span className="text-muted-foreground font-medium">Accessories</span>
                                <span className="text-foreground/70">{shot.character.accessories}</span>
                              </>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Production specs grid */}
                      <div className="space-y-1">
                      <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Production</span>
                      <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                        {shot.setting && (
                          <>
                            <span className="text-muted-foreground font-medium">Setting</span>
                            <span className="text-foreground/70">{shot.setting}</span>
                          </>
                        )}
                        {shot.camera && (
                          <>
                            <span className="text-muted-foreground font-medium">Camera</span>
                            <span className="text-foreground/70">{shot.camera}</span>
                          </>
                        )}
                        {shot.lighting && (
                          <>
                            <span className="text-muted-foreground font-medium">Lighting</span>
                            <span className="text-foreground/70">{shot.lighting}</span>
                          </>
                        )}
                        {shot.color_grade && (
                          <>
                            <span className="text-muted-foreground font-medium">Color</span>
                            <span className="text-foreground/70">{shot.color_grade}</span>
                          </>
                        )}
                        {shot.imperfection && (
                          <>
                            <span className="text-muted-foreground font-medium">Imperfection</span>
                            <span className="text-foreground/70">{shot.imperfection}</span>
                          </>
                        )}
                        {shot.frame?.strategy && (
                          <>
                            <span className="text-muted-foreground font-medium">Frame source</span>
                            <span className="text-foreground/70">
                              {shot.frame.strategy}
                              {shot.frame.anchor_group && ` (${shot.frame.anchor_group})`}
                            </span>
                          </>
                        )}
                      </div>
                      </div>

                      {/* Avoid list */}
                      {shot.avoid && shot.avoid.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-xs text-muted-foreground font-medium">Avoid:</span>
                          {shot.avoid.map((a) => (
                            <Badge key={a} variant="outline" className="text-xs text-rose-400/70 border-rose-400/20 font-normal">
                              {a}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}

              {/* Director-level details */}
              {(data.director.music_prompt || data.director.voice_design_prompt) && (
                <Card className="bg-card/40 border-border/50">
                  <CardContent className="space-y-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold">Audio Direction</span>
                      {data.director.format && (
                        <Badge variant="outline" className="text-xs font-mono text-primary/50 border-primary/20">
                          {data.director.format}
                        </Badge>
                      )}
                    </div>
                    {data.director.music_prompt && (
                      <div className="space-y-1">
                        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Music Prompt</span>
                        <p className="text-sm text-foreground/80 leading-relaxed">{data.director.music_prompt}</p>
                      </div>
                    )}
                    {data.director.voice_design_prompt && (
                      <div className="space-y-1">
                        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold">Voice Design</span>
                        <p className="text-sm text-foreground/80 leading-relaxed">{data.director.voice_design_prompt}</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}


        {runs.length === 0 && !creative && videoAssets.length === 0 && (
          <div className="text-center py-16 text-muted-foreground">
            <p className="text-lg font-light">No runs yet</p>
            <p className="text-sm mt-2 font-mono">Run a pipeline for this concept to see results</p>
          </div>
        )}
      </div>
    </div>
  )
}
