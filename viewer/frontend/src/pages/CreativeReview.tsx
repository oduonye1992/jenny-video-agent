import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { StageStepper } from "@/components/StageStepper"
import { ShotTimeline } from "@/components/ShotTimeline"
import { useApi, saveCreative, advanceConcept } from "@/hooks/use-api"
import type { Creative, CreativeBeat, PlanShotType } from "@/types"

const TYPE_COLORS: Record<PlanShotType, string> = {
  TALKING_HEAD: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  "B-ROLL": "bg-amber-500/15 text-amber-400 border-amber-500/30",
  PRODUCT: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  MONTAGE: "bg-purple-500/15 text-purple-400 border-purple-500/30",
}

function BeatCard({
  beat,
  index,
  isSelected,
  onSelect,
  onUpdate,
}: {
  beat: CreativeBeat
  index: number
  isSelected: boolean
  onSelect: () => void
  onUpdate: (field: keyof CreativeBeat, value: string) => void
}) {
  const [editing, setEditing] = useState<keyof CreativeBeat | null>(null)
  const [editValue, setEditValue] = useState("")

  function startEdit(field: keyof CreativeBeat) {
    setEditing(field)
    setEditValue(String(beat[field] || ""))
  }

  function commitEdit() {
    if (editing) {
      onUpdate(editing, editValue)
      setEditing(null)
    }
  }

  return (
    <Card
      className={`bg-card/40 border-border/50 transition-all cursor-pointer ${
        isSelected ? "ring-1 ring-primary/40" : "hover:border-border"
      }`}
      onClick={onSelect}
    >
      <CardContent className="pt-4 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm font-mono">{index + 1}.</span>
          <h3 className="font-semibold">{beat.name}</h3>
          <Badge variant="outline" className={TYPE_COLORS[beat.type]}>
            {beat.type}
          </Badge>
          <span className="text-muted-foreground text-sm ml-auto">{beat.duration}s</span>
          <Badge variant="outline" className="text-muted-foreground border-border/50">
            {beat.role}
          </Badge>
        </div>

        {beat.emotion && (
          <p className="text-sm text-muted-foreground italic">{beat.emotion}</p>
        )}

        {beat.action_summary && (
          <p className="text-sm">{beat.action_summary}</p>
        )}

        {beat.dialogue && (
          <div
            className="text-sm bg-blue-500/5 border-l-2 border-blue-500/30 pl-3 py-1 cursor-text"
            onClick={(e) => { e.stopPropagation(); startEdit("dialogue") }}
          >
            {editing === "dialogue" ? (
              <Textarea
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onBlur={commitEdit}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && commitEdit()}
                autoFocus
                rows={2}
                className="bg-transparent border-0 p-0 text-sm"
              />
            ) : (
              <span>{beat.dialogue}</span>
            )}
          </div>
        )}

        {beat.voiceover && (
          <div
            className="text-sm text-muted-foreground bg-amber-500/5 border-l-2 border-amber-500/30 pl-3 py-1 cursor-text"
            onClick={(e) => { e.stopPropagation(); startEdit("voiceover") }}
          >
            {editing === "voiceover" ? (
              <Textarea
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onBlur={commitEdit}
                autoFocus
                rows={2}
                className="bg-transparent border-0 p-0 text-sm"
              />
            ) : (
              <span>VO: {beat.voiceover}</span>
            )}
          </div>
        )}

        {beat.text_overlay && (
          <p className="text-sm font-medium text-emerald-400">[{beat.text_overlay}]</p>
        )}
      </CardContent>
    </Card>
  )
}

export function CreativeReview() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { data, loading, error } = useApi<{
    slug: string
    creative: Creative
    creative_md: string | null
  }>(`/api/concepts/${slug}/creative`)

  const [creative, setCreative] = useState<Creative | null>(null)
  const [selectedBeat, setSelectedBeat] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  // Sync fetched data into local state
  const c = creative || data?.creative
  if (data?.creative && !creative) {
    // Only set once on load
    setTimeout(() => setCreative(data.creative), 0)
  }

  async function handleApprove() {
    if (!c || !slug) return
    setSaving(true)
    try {
      const updated = { ...c, status: "approved" as const }
      await saveCreative(slug, updated as unknown as Record<string, unknown>)
      await advanceConcept(slug, "characters")
      navigate(`/concepts/${slug}/characters`)
    } catch (e) {
      console.error(e)
    } finally {
      setSaving(false)
    }
  }

  function updateBeat(index: number, field: keyof CreativeBeat, value: string) {
    if (!c) return
    const beats = [...c.beats]
    beats[index] = { ...beats[index], [field]: value }
    setCreative({ ...c, beats })
  }

  if (loading) return <div className="p-8 text-muted-foreground">Loading creative...</div>
  if (error) return <div className="p-8 text-rose-400">Error: {error}</div>
  if (!c) return <div className="p-8 text-muted-foreground">No creative found.</div>

  const totalDuration = c.beats.reduce((sum, b) => sum + b.duration, 0)

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{c.title}</h1>
            <p className="text-muted-foreground mt-1">{c.angle}</p>
          </div>
          <StageStepper current="creative" />
        </div>

        {/* Summary */}
        <div className="flex gap-3 text-sm text-muted-foreground">
          <span>{c.beats.length} beats</span>
          <span>·</span>
          <span>{totalDuration}s</span>
          <span>·</span>
          <span>{c.target_platform}</span>
          <span>·</span>
          <span>Arc: {c.arc.join(" → ")}</span>
        </div>

        {/* Character */}
        <Card className="bg-card/40 border-border/50">
          <CardContent className="pt-4">
            <h2 className="text-lg font-semibold mb-2">Character</h2>
            <div className="flex gap-6">
              <div className="flex-1 space-y-1">
                <p className="font-medium">{c.character.name}</p>
                {c.character.who && (
                  <p className="text-sm text-muted-foreground">{c.character.who}</p>
                )}
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground mt-2">
                  {c.character.age && <span>Age: {c.character.age}</span>}
                  {c.character.ethnicity && <span>Ethnicity: {c.character.ethnicity}</span>}
                  {c.character.hair && <span>Hair: {c.character.hair}</span>}
                  {c.character.wardrobe && <span>Wardrobe: {c.character.wardrobe}</span>}
                  {c.character.voice && <span>Voice: {c.character.voice}</span>}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Shot Timeline */}
        <div className="space-y-2">
          <h2 className="text-lg font-semibold">Timeline</h2>
          <ShotTimeline
            beats={c.beats}
            selectedIndex={selectedBeat}
            onSelect={setSelectedBeat}
          />
        </div>

        {/* Beats */}
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Beats</h2>
          {c.beats.map((beat, i) => (
            <BeatCard
              key={i}
              beat={beat}
              index={i}
              isSelected={selectedBeat === i}
              onSelect={() => setSelectedBeat(i)}
              onUpdate={(field, value) => updateBeat(i, field, value)}
            />
          ))}
        </div>

        {/* Audio */}
        <Card className="bg-card/40 border-border/50">
          <CardContent className="pt-4">
            <h2 className="text-lg font-semibold mb-2">Audio</h2>
            <div className="space-y-1 text-sm">
              {c.audio.music_direction && (
                <p><span className="text-muted-foreground">Music:</span> {c.audio.music_direction}</p>
              )}
              {c.audio.voice_direction && (
                <p><span className="text-muted-foreground">Voice:</span> {c.audio.voice_direction}</p>
              )}
              <p><span className="text-muted-foreground">Strategy:</span> {c.audio.audio_strategy}</p>
            </div>
          </CardContent>
        </Card>

        {/* Hook variations */}
        {c.hook_variations.length > 0 && (
          <Card className="bg-card/40 border-border/50">
            <CardContent className="pt-4">
              <h2 className="text-lg font-semibold mb-2">Hook Variations</h2>
              <ol className="space-y-1 text-sm list-decimal list-inside">
                {c.hook_variations.map((hook, i) => (
                  <li key={i}>{hook}</li>
                ))}
              </ol>
            </CardContent>
          </Card>
        )}

        {/* Approve */}
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={() => navigate(`/concepts/${slug}`)}
          >
            Back
          </Button>
          <Button onClick={handleApprove} disabled={saving} size="lg">
            {saving ? "Saving..." : "Approve Creative"}
          </Button>
        </div>
      </div>
    </div>
  )
}
