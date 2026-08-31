import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Img } from "@/components/Img"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { generatePlan, optimizeShotPrompt, updateShot } from "@/hooks/use-api"
import type { Plan, PlanShot, PlanShotType, PlanShotStatus } from "@/types"

const SHOT_TYPE_COLORS: Record<PlanShotType, string> = {
  TALKING_HEAD: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  "B-ROLL": "bg-amber-500/15 text-amber-400 border-amber-500/30",
  PRODUCT: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  MONTAGE: "bg-purple-500/15 text-purple-400 border-purple-500/30",
}

const STATUS_COLORS: Record<PlanShotStatus, string> = {
  draft: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  prompted: "bg-sky-500/15 text-sky-400 border-sky-500/30",
  framed: "bg-indigo-500/15 text-indigo-400 border-indigo-500/30",
  ready: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  generating: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  done: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-400 border-rose-500/30",
}

const VIDEO_MODELS = [
  { value: "kling_v3", label: "Kling 3.0" },
  { value: "veo_v3", label: "Veo 3.1" },
  { value: "sora_v2", label: "Sora 2" },
  { value: "kling_v2", label: "Kling 2.6" },
  { value: "seedance_v1_5", label: "Seedance 1.5" },
  { value: "hailuo_02", label: "Hailuo 02" },
]

function ShotEditor({
  shot,
  index,
  slug,
  onUpdated,
}: {
  shot: PlanShot
  index: number
  slug: string
  onUpdated: (index: number, updates: Partial<PlanShot>) => void
}) {
  const [optimizing, setOptimizing] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  async function handleOptimize(model: string) {
    setOptimizing(model)
    try {
      const result = await optimizeShotPrompt(slug, index, model)
      onUpdated(index, {
        prompts: { ...shot.prompts, [model]: result.prompt },
        status: "prompted",
      })
    } catch (e) {
      console.error(e)
    } finally {
      setOptimizing(null)
    }
  }

  async function handleModelSelect(model: string | null) {
    if (!model) return
    try {
      await updateShot(slug, index, { selected_model: model })
      onUpdated(index, { selected_model: model })
    } catch (e) {
      console.error(e)
    }
  }

  const hasPrompts = Object.values(shot.prompts).some((p) => p)

  return (
    <Card className="bg-card/40 border-border/50">
      <CardContent className="space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">{shot.name}</h3>
            <Badge variant="outline" className={SHOT_TYPE_COLORS[shot.type]}>
              {shot.type}
            </Badge>
            <Badge variant="outline" className={STATUS_COLORS[shot.status]}>
              {shot.status}
            </Badge>
            <span className="text-xs text-muted-foreground font-mono">
              {shot.duration}s
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded(!expanded)}
            className="text-xs"
          >
            {expanded ? "Collapse" : "Expand"}
          </Button>
        </div>

        {/* Direction (always visible) */}
        <p className="text-sm text-muted-foreground leading-relaxed">
          {shot.direction}
        </p>

        {/* Dialogue / Voiceover */}
        {shot.dialogue && (
          <p className="text-xs text-blue-400 font-mono">
            Dialogue: "{shot.dialogue}"
          </p>
        )}
        {shot.voiceover && (
          <p className="text-xs text-amber-400 font-mono">
            VO: "{shot.voiceover}"
          </p>
        )}

        {expanded && (
          <>
            {/* Scene details */}
            <div className="grid grid-cols-3 gap-3 text-xs text-muted-foreground">
              {shot.setting && (
                <div>
                  <span className="text-muted-foreground">Setting:</span>{" "}
                  {shot.setting}
                </div>
              )}
              {shot.camera && (
                <div>
                  <span className="text-muted-foreground">Camera:</span>{" "}
                  {shot.camera}
                </div>
              )}
              {shot.lighting && (
                <div>
                  <span className="text-muted-foreground">Lighting:</span>{" "}
                  {shot.lighting}
                </div>
              )}
            </div>

            {/* Model selection + optimize */}
            <div className="flex items-center gap-3 pt-2 border-t border-border/30">
              <Select
                value={shot.selected_model || undefined}
                onValueChange={handleModelSelect}
              >
                <SelectTrigger className="w-[180px] h-8 text-xs">
                  <SelectValue placeholder="Select model" />
                </SelectTrigger>
                <SelectContent>
                  {VIDEO_MODELS.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {shot.selected_model && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleOptimize(shot.selected_model)}
                  disabled={!!optimizing}
                  className="text-xs h-8"
                >
                  {optimizing === shot.selected_model ? (
                    <>
                      <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin mr-1.5" />
                      Optimizing...
                    </>
                  ) : (
                    "Optimize prompt"
                  )}
                </Button>
              )}
            </div>

            {/* Model-specific prompts */}
            {hasPrompts && (
              <div className="space-y-2 pt-2 border-t border-border/30">
                <span className="text-xs text-muted-foreground font-mono">
                  Optimized Prompts
                </span>
                {Object.entries(shot.prompts).map(([model, prompt]) =>
                  prompt ? (
                    <div key={model} className="space-y-1">
                      <Badge
                        variant="outline"
                        className="text-xs font-mono"
                      >
                        {VIDEO_MODELS.find((m) => m.value === model)?.label ??
                          model}
                      </Badge>
                      <Card className="bg-background/30">
                        <CardContent>
                          <p className="text-xs font-mono text-muted-foreground whitespace-pre-wrap leading-relaxed">
                            {prompt}
                          </p>
                        </CardContent>
                      </Card>
                    </div>
                  ) : null
                )}
              </div>
            )}

            {/* Start frame */}
            {shot.start_frame && (
              <div className="pt-2 border-t border-border/30">
                <span className="text-xs text-muted-foreground font-mono">
                  Start Frame
                </span>
                <Img
                  src={shot.start_frame}
                  alt="Start frame"
                  className="mt-1 h-32 rounded-md object-cover"
                />
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function NewConcept() {
  const navigate = useNavigate()
  const [brief, setBrief] = useState("")
  const [profile, setProfile] = useState("cheap")
  const [aspectRatio, setAspectRatio] = useState("9:16")
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [slug, setSlug] = useState<string | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)

  async function handleGenerate() {
    if (!brief.trim()) return
    setGenerating(true)
    setError(null)
    try {
      const result = await generatePlan(brief, profile, aspectRatio)
      setSlug(result.slug)
      setPlan(result.plan as unknown as Plan)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate plan")
    } finally {
      setGenerating(false)
    }
  }

  function handleShotUpdated(index: number, updates: Partial<PlanShot>) {
    if (!plan) return
    const newShots = [...plan.shots]
    newShots[index] = { ...newShots[index], ...updates }
    setPlan({ ...plan, shots: newShots })
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border/50 bg-card/20">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/")}
              className="text-muted-foreground"
            >
              &larr; Back
            </Button>
            <h1 className="text-lg font-semibold tracking-tight">
              New Concept
            </h1>
          </div>
          {slug && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate(`/concepts/${slug}`)}
            >
              View concept &rarr;
            </Button>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-8">
        {/* Brief input */}
        {!plan && (
          <Card className="bg-card/40 border-border/50">
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium text-foreground/80 block mb-2">
                  What's the ad about?
                </label>
                <Textarea
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                  placeholder="e.g. A 30-second TikTok ad showing a stressed student finding a useful way to slow down during finals week"
                  rows={4}
                  className="bg-background/50 text-sm"
                />
              </div>

              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted-foreground">
                    Profile
                  </label>
                  <Select value={profile} onValueChange={(v) => v && setProfile(v)}>
                    <SelectTrigger className="w-[120px] h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="cheap">Cheap</SelectItem>
                      <SelectItem value="production">Production</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted-foreground">
                    Aspect
                  </label>
                  <Select value={aspectRatio} onValueChange={(v) => v && setAspectRatio(v)}>
                    <SelectTrigger className="w-[100px] h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="9:16">9:16</SelectItem>
                      <SelectItem value="16:9">16:9</SelectItem>
                      <SelectItem value="1:1">1:1</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button
                  onClick={handleGenerate}
                  disabled={generating || !brief.trim()}
                  className="ml-auto"
                >
                  {generating ? (
                    <>
                      <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin mr-2" />
                      Generating plan...
                    </>
                  ) : (
                    "Generate plan"
                  )}
                </Button>
              </div>

              {error && (
                <p className="text-sm text-rose-400">{error}</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Plan editor */}
        {plan && (
          <>
            {/* Plan header */}
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-bold">{plan.title}</h2>
                <Badge variant="outline" className="font-mono text-xs">
                  {plan.profile}
                </Badge>
                <Badge variant="outline" className="font-mono text-xs">
                  {plan.aspect_ratio}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">{plan.angle}</p>
              <div className="flex items-center gap-1 text-xs text-muted-foreground font-mono">
                {plan.arc.map((beat, i) => (
                  <span key={beat}>
                    {i > 0 && <span className="mx-1">&rarr;</span>}
                    {beat}
                  </span>
                ))}
              </div>
            </div>

            {/* Character */}
            {plan.character && plan.character.name && (
              <Card className="bg-card/40 border-border/50">
                <CardContent className="space-y-2">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold">Character</h3>
                    <Badge variant="outline" className="text-xs">
                      {plan.character.name}
                    </Badge>
                  </div>
                  {plan.character.description && (
                    <p className="text-sm text-muted-foreground">
                      {plan.character.description}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    {plan.character.age && <span>Age: {plan.character.age}</span>}
                    {plan.character.ethnicity && (
                      <span>Ethnicity: {plan.character.ethnicity}</span>
                    )}
                    {plan.character.hair && <span>Hair: {plan.character.hair}</span>}
                    {plan.character.wardrobe && (
                      <span>Wardrobe: {plan.character.wardrobe}</span>
                    )}
                    {plan.character.build && <span>Build: {plan.character.build}</span>}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Shot list */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground/80">
                  Shot List ({plan.shots.length} shots)
                </h3>
                <span className="text-xs text-muted-foreground font-mono">
                  {plan.shots.reduce((sum, s) => sum + s.duration, 0)}s total
                </span>
              </div>
              {plan.shots.map((shot, i) => (
                <ShotEditor
                  key={`${slug}-${i}`}
                  shot={shot}
                  index={i}
                  slug={slug!}
                  onUpdated={handleShotUpdated}
                />
              ))}
            </div>

            {/* Audio */}
            {plan.audio && (plan.audio.music_mood || plan.audio.voice_tone) && (
              <Card className="bg-card/40 border-border/50">
                <CardContent className="space-y-2">
                  <h3 className="text-sm font-semibold">Audio</h3>
                  {plan.audio.music_mood && (
                    <p className="text-xs text-muted-foreground">
                      <span className="text-muted-foreground">Music:</span>{" "}
                      {plan.audio.music_mood}
                    </p>
                  )}
                  {plan.audio.voice_tone && (
                    <p className="text-xs text-muted-foreground">
                      <span className="text-muted-foreground">Voice:</span>{" "}
                      {plan.audio.voice_tone}
                    </p>
                  )}
                </CardContent>
              </Card>
            )}

            {/* Hook variations */}
            {plan.hook_variations && plan.hook_variations.length > 0 && (
              <Card className="bg-card/40 border-border/50">
                <CardContent className="space-y-2">
                  <h3 className="text-sm font-semibold">Hook Variations</h3>
                  <ol className="list-decimal list-inside space-y-1 text-xs text-muted-foreground">
                    {plan.hook_variations.map((hook, i) => (
                      <li key={i}>{hook}</li>
                    ))}
                  </ol>
                </CardContent>
              </Card>
            )}

            {/* Compliance */}
            {plan.compliance_notes && (
              <Card className="bg-amber-500/5 border-amber-500/20">
                <CardContent>
                  <h3 className="text-sm font-semibold text-amber-400 mb-1">
                    Compliance
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    {plan.compliance_notes}
                  </p>
                </CardContent>
              </Card>
            )}
          </>
        )}
      </main>
    </div>
  )
}
