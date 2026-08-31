import { useState, useEffect, useRef } from "react"
import { Img } from "@/components/Img"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { patchNodePrompt, triggerRerun } from "@/hooks/use-api"
import type { PipelineNode, StepStatus, ShotVersion } from "@/types"

interface Props {
  node: PipelineNode
  stepStatus?: StepStatus
  runName: string
  assets: Record<string, string>
  costEntry?: { cost: number }
  versions?: ShotVersion[]
  onRefresh: () => void
}

export function ShotCard({
  node,
  stepStatus,
  runName,
  assets,
  costEntry,
  versions,
  onRefresh,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [promptText, setPromptText] = useState(
    (node.config.prompt as string) ?? ""
  )
  const [saving, setSaving] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)

  // Resolve output asset
  const outputFile =
    stepStatus?.output?.split("/").pop() ??
    (node.config.output_filename as string | undefined)
  const assetUrl = outputFile ? assets[outputFile] : null

  // Find start frame
  const startFrameUrl = (() => {
    const dep = node.config.start_frame_from as string | undefined
    if (!dep) return null
    for (const candidate of ["anchor_frame.png", "frame.png"]) {
      if (assets[candidate]) return assets[candidate]
    }
    const lastFrame = Object.keys(assets).find(
      (k) =>
        k.includes("last_frame") &&
        k.includes(dep.replace(/\./g, "_").replace("extract_last_frame_", ""))
    )
    return lastFrame ? assets[lastFrame] : null
  })()

  const isVideo = outputFile?.endsWith(".mp4")
  const isImage = outputFile?.match(/\.(png|jpg|jpeg)$/)

  const adapter = node.adapter
  const hasVersions = versions && versions.length > 0

  // The URL to display — either the selected version or current output
  const displayUrl = selectedVersion !== null
    ? versions?.find((v) => v.version === selectedVersion)?.url ?? assetUrl
    : assetUrl
  const displayIsVideo = selectedVersion !== null
    ? versions?.find((v) => v.version === selectedVersion)?.filename.endsWith(".mp4")
    : isVideo

  async function handleSave() {
    setSaving(true)
    try {
      await patchNodePrompt(runName, node.id, promptText)
      setEditing(false)
    } catch (e) {
      console.error(e)
    } finally {
      setSaving(false)
    }
  }

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // When rerunning, poll parent for updates; stop when step completes/fails
  useEffect(() => {
    if (rerunning) {
      pollRef.current = setInterval(onRefresh, 4000)
      return () => { if (pollRef.current) clearInterval(pollRef.current) }
    }
  }, [rerunning, onRefresh])

  // Clear rerunning state when step finishes
  useEffect(() => {
    if (rerunning && stepStatus?.status && stepStatus.status !== "running" && stepStatus.status !== "pending") {
      setRerunning(false)
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [rerunning, stepStatus?.status])

  async function handleRerun() {
    setRerunning(true)
    try {
      await triggerRerun(runName, node.id)
    } catch (e) {
      console.error(e)
      setRerunning(false)
    }
  }

  const statusColor =
    stepStatus?.status === "completed"
      ? "bg-emerald-500"
      : stepStatus?.status === "failed"
        ? "bg-rose-500"
        : stepStatus?.status === "running"
          ? "bg-amber-500 animate-pulse"
          : "bg-muted-foreground/30"

  return (
    <Card
      className="bg-card/40 border-border/50 hover:border-primary/20 transition-all"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Media area */}
      <div className="relative">
        <div className="flex items-start gap-4 px-4">
          {/* Start frame (small) with arrow */}
          {startFrameUrl && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <Img
                src={startFrameUrl}
                alt="Start frame"
                className="h-28 w-auto rounded-md object-cover opacity-70"
              />
              <span className="text-muted-foreground text-lg">&#8594;</span>
            </div>
          )}

          {/* Output (large) */}
          {displayUrl && (
            <div className="flex-1 min-w-0">
              {displayIsVideo ? (
                <video
                  key={displayUrl}
                  src={displayUrl}
                  controls
                  className="w-full max-h-[360px] rounded-lg"
                  preload="none"
                />
              ) : isImage ? (
                <Img
                  key={displayUrl}
                  src={displayUrl}
                  alt="Output"
                  className="w-full max-h-[360px] rounded-lg object-contain"
                />
              ) : (
                <audio key={displayUrl} src={displayUrl} controls className="w-full" />
              )}
            </div>
          )}
        </div>

        {/* Regenerate on hover (always visible while rerunning) */}
        {(hovered || rerunning) && (
          <div className="absolute top-3 right-3">
            <Button
              size="sm"
              variant="secondary"
              onClick={handleRerun}
              disabled={rerunning}
              className="text-xs opacity-90 hover:opacity-100 bg-card/80 backdrop-blur-sm"
            >
              {rerunning && (
                <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin mr-1.5" />
              )}
              {rerunning ? "Running..." : "Regenerate"}
            </Button>
          </div>
        )}
      </div>

      {/* Version history filmstrip */}
      {hasVersions && (
        <div className="px-4 pt-3">
          <ScrollArea className="w-full">
            <div className="flex items-center gap-2 pb-2">
              <span className="text-xs text-muted-foreground font-mono flex-shrink-0">
                History
              </span>
              {versions!.map((v) => (
                <button
                  key={v.version}
                  onClick={() => setSelectedVersion(
                    selectedVersion === v.version ? null : v.version
                  )}
                  className={`flex-shrink-0 rounded-md overflow-hidden transition-all cursor-pointer ${
                    selectedVersion === v.version
                      ? "ring-2 ring-primary"
                      : "ring-1 ring-border/50 opacity-60 hover:opacity-100"
                  }`}
                >
                  {v.filename.endsWith(".mp4") ? (
                    <div className="w-16 h-12 bg-muted/20 flex items-center justify-center">
                      <span className="text-xs font-mono text-muted-foreground">
                        v{v.version}
                      </span>
                    </div>
                  ) : (
                    <Img
                      src={v.url}
                      alt={`v${v.version}`}
                      className="h-12 w-auto object-cover"
                    />
                  )}
                </button>
              ))}
              {/* Current version indicator */}
              <button
                onClick={() => setSelectedVersion(null)}
                className={`flex-shrink-0 rounded-md overflow-hidden transition-all cursor-pointer ${
                  selectedVersion === null
                    ? "ring-2 ring-primary"
                    : "ring-1 ring-border/50 opacity-60 hover:opacity-100"
                }`}
              >
                <div className="w-16 h-12 bg-emerald-500/10 flex items-center justify-center">
                  <span className="text-xs font-mono text-emerald-400 font-semibold">
                    latest
                  </span>
                </div>
              </button>
            </div>
            <ScrollBar orientation="horizontal" />
          </ScrollArea>
        </div>
      )}

      {/* Caption area */}
      <CardContent className="space-y-3">
        {/* Shot name + status dot + metadata */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold tracking-tight">
              {node.id
                .replace(/[._]/g, " ")
                .replace(/\b\w/g, (c) => c.toUpperCase())}
            </h3>
            {stepStatus && (
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${statusColor}`} />
            )}
            {selectedVersion !== null && (
              <Badge variant="outline" className="font-mono text-xs text-amber-400 border-amber-500/30 bg-amber-500/10">
                viewing v{selectedVersion}
              </Badge>
            )}
          </div>
          <Badge variant="outline" className="font-mono text-xs text-muted-foreground">
            {adapter}
            {costEntry ? ` \u00b7 $${costEntry.cost.toFixed(2)}` : ""}
          </Badge>
        </div>

        {/* Error */}
        {stepStatus?.error && (
          <Card className="bg-rose-500/10 border-rose-500/20">
            <CardContent>
              <p className="text-xs text-rose-400 font-mono break-all">
                {stepStatus.error}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Prompt toggle */}
        {promptText && (
          <div>
            {!promptOpen && !editing ? (
              <button
                onClick={() => setPromptOpen(true)}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                Show prompt
              </button>
            ) : editing ? (
              <div className="space-y-2">
                <Textarea
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                  rows={8}
                  className="font-mono text-xs bg-background/50"
                />
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleSave} disabled={saving}>
                    {saving ? "Saving..." : "Save"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditing(false)
                      setPromptText((node.config.prompt as string) ?? "")
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <Card
                  className="bg-background/30 cursor-pointer hover:bg-background/50 transition-colors"
                  onClick={() => setEditing(true)}
                >
                  <CardContent>
                    <p className="text-xs text-muted-foreground font-mono whitespace-pre-wrap leading-relaxed">
                      {promptText}
                    </p>
                  </CardContent>
                </Card>
                <button
                  onClick={() => {
                    setPromptOpen(false)
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                >
                  Hide prompt
                </button>
              </div>
            )}
          </div>
        )}

        {/* Timing */}
        {stepStatus?.duration_s && (
          <p className="text-xs text-muted-foreground font-mono">
            {stepStatus.duration_s.toFixed(1)}s
            {stepStatus.cache_hit && " (cached)"}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
