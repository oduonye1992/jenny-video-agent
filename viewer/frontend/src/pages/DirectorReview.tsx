import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Img } from "@/components/Img"
import { StageStepper } from "@/components/StageStepper"
import { useApi, saveDirector, advanceConcept } from "@/hooks/use-api"
import type { Director, DirectorShot, PlanShotType } from "@/types"

const TYPE_COLORS: Record<PlanShotType, string> = {
  TALKING_HEAD: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  "B-ROLL": "bg-amber-500/15 text-amber-400 border-amber-500/30",
  PRODUCT: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  MONTAGE: "bg-purple-500/15 text-purple-400 border-purple-500/30",
}

type EditableField = "setting" | "camera" | "lighting" | "color_grade" | "action" | "imperfection"

const SPEC_FIELDS: { key: EditableField; label: string }[] = [
  { key: "setting", label: "Setting" },
  { key: "camera", label: "Camera" },
  { key: "lighting", label: "Lighting" },
  { key: "color_grade", label: "Color Grade" },
  { key: "action", label: "Action" },
  { key: "imperfection", label: "Imperfection" },
]

function ShotCard({
  shot,
  isExpanded,
  onToggle,
  onUpdate,
}: {
  shot: DirectorShot
  isExpanded: boolean
  onToggle: () => void
  onUpdate: (field: EditableField, value: string) => void
}) {
  const [editing, setEditing] = useState<EditableField | null>(null)
  const [editValue, setEditValue] = useState("")

  function startEdit(field: EditableField, e: React.MouseEvent) {
    e.stopPropagation()
    setEditing(field)
    setEditValue(shot[field])
  }

  function commitEdit() {
    if (editing) {
      onUpdate(editing, editValue)
      setEditing(null)
    }
  }

  return (
    <Card className="bg-card/40 border-border/50">
      <CardContent className="pt-4 space-y-3">
        {/* Collapsed header — always visible */}
        <button
          onClick={onToggle}
          className="w-full flex items-center gap-3 text-left"
        >
          {/* Thumbnail */}
          {shot.frame.generated_frame ? (
            <Img
              src={shot.frame.generated_frame}
              alt={shot.beat_name}
              className="w-12 h-12 rounded-md object-cover flex-shrink-0"
            />
          ) : (
            <div className="w-12 h-12 rounded-md bg-muted/20 flex-shrink-0" />
          )}

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-xs font-mono">
                {shot.shot_id}
              </span>
              <h3 className="font-semibold truncate">{shot.beat_name}</h3>
              <Badge variant="outline" className={TYPE_COLORS[shot.type]}>
                {shot.type}
              </Badge>
              <span className="text-muted-foreground text-sm ml-auto flex-shrink-0">
                {shot.duration}s
              </span>
            </div>
            {!isExpanded && (
              <p className="text-sm text-muted-foreground truncate mt-0.5">
                {shot.setting}
              </p>
            )}
          </div>

          <span className="text-muted-foreground text-xs flex-shrink-0">
            {isExpanded ? "▲" : "▼"}
          </span>
        </button>

        {/* Expanded spec grid */}
        {isExpanded && (
          <div className="space-y-4 pt-2 border-t border-border/30">
            {/* Production specs */}
            <div className="grid grid-cols-2 gap-3">
              {SPEC_FIELDS.map(({ key, label }) => (
                <div key={key} className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    {label}
                  </span>
                  {editing === key ? (
                    <Textarea
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onBlur={commitEdit}
                      onKeyDown={(e) =>
                        e.key === "Enter" && !e.shiftKey && commitEdit()
                      }
                      autoFocus
                      rows={3}
                      className="bg-background/50 text-sm"
                    />
                  ) : (
                    <p
                      className="text-sm cursor-text hover:bg-muted/10 rounded px-1 py-0.5 -mx-1"
                      onClick={(e) => startEdit(key, e)}
                    >
                      {shot[key] || (
                        <span className="text-muted-foreground italic">
                          Click to edit
                        </span>
                      )}
                    </p>
                  )}
                </div>
              ))}
            </div>

            {/* Character */}
            {shot.character.name && (
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Character
                </span>
                <div className="text-sm space-y-0.5">
                  <p className="font-medium">{shot.character.name}</p>
                  {shot.character.physical_description && (
                    <p className="text-muted-foreground">
                      {shot.character.physical_description}
                    </p>
                  )}
                  {shot.character.wardrobe && (
                    <p className="text-muted-foreground">
                      Wardrobe: {shot.character.wardrobe}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Audio */}
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Audio
              </span>
              <div className="text-sm space-y-0.5">
                <p>
                  <span className="text-muted-foreground">Strategy:</span>{" "}
                  {shot.audio.strategy}
                </p>
                {shot.audio.dialogue && (
                  <p className="bg-blue-500/5 border-l-2 border-blue-500/30 pl-2 py-0.5">
                    {shot.audio.dialogue}
                  </p>
                )}
                {shot.audio.voiceover && (
                  <p className="text-muted-foreground bg-amber-500/5 border-l-2 border-amber-500/30 pl-2 py-0.5">
                    VO: {shot.audio.voiceover}
                  </p>
                )}
              </div>
            </div>

            {/* Frame source */}
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Frame Source
              </span>
              <div className="text-sm space-y-0.5">
                <p>
                  <span className="text-muted-foreground">Strategy:</span>{" "}
                  {shot.frame.strategy}
                </p>
                {shot.frame.anchor_group && (
                  <p className="text-muted-foreground">
                    Anchor group: {shot.frame.anchor_group}
                  </p>
                )}
                {shot.frame.edit_from_shot && (
                  <p className="text-muted-foreground">
                    Edit from: {shot.frame.edit_from_shot}
                  </p>
                )}
                {shot.frame.chain_from_shot && (
                  <p className="text-muted-foreground">
                    Chain from: {shot.frame.chain_from_shot}
                  </p>
                )}
              </div>
            </div>

            {/* Avoid list */}
            {shot.avoid.length > 0 && (
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Avoid
                </span>
                <div className="flex flex-wrap gap-1">
                  {shot.avoid.map((item, i) => (
                    <Badge
                      key={i}
                      variant="outline"
                      className="text-rose-400 border-rose-500/30 bg-rose-500/10"
                    >
                      {item}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function DirectorReview() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { data, loading, error } = useApi<{
    slug: string
    director: Director
    director_md: string | null
  }>(`/api/concepts/${slug}/director`)

  const [director, setDirector] = useState<Director | null>(null)
  const [expandedShot, setExpandedShot] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const d = director || data?.director
  if (data?.director && !director) {
    setTimeout(() => setDirector(data.director), 0)
  }

  function updateShot(
    shotId: string,
    field: EditableField,
    value: string
  ) {
    if (!d) return
    const shots = d.shots.map((s) =>
      s.shot_id === shotId ? { ...s, [field]: value } : s
    )
    setDirector({ ...d, shots })
  }

  async function handleApprove() {
    if (!d || !slug) return
    setSaving(true)
    try {
      const updated = { ...d, status: "ready" as const }
      await saveDirector(slug, updated as unknown as Record<string, unknown>)
      await advanceConcept(slug, "production")
      navigate(`/concepts/${slug}/progress`)
    } catch (e) {
      console.error(e)
    } finally {
      setSaving(false)
    }
  }

  if (loading)
    return (
      <div className="p-8 text-muted-foreground">Loading director...</div>
    )
  if (error) return <div className="p-8 text-rose-400">Error: {error}</div>
  if (!d) return <div className="p-8 text-muted-foreground">No director plan found.</div>

  const totalDuration = d.shots.reduce((sum, s) => sum + s.duration, 0)

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Director Review
            </h1>
            <p className="text-muted-foreground mt-1">
              Review and edit production specs for each shot.
            </p>
          </div>
          <StageStepper current="director" />
        </div>

        {/* Summary */}
        <div className="flex gap-3 text-sm text-muted-foreground">
          <span>{d.shots.length} shots</span>
          <span>·</span>
          <span>{totalDuration}s</span>
          <span>·</span>
          <span>{d.aspect_ratio}</span>
          <span>·</span>
          <span>Profile: {d.profile}</span>
        </div>

        {/* Shot list */}
        <div className="space-y-3">
          {d.shots.map((shot) => (
            <ShotCard
              key={shot.shot_id}
              shot={shot}
              isExpanded={expandedShot === shot.shot_id}
              onToggle={() =>
                setExpandedShot(
                  expandedShot === shot.shot_id ? null : shot.shot_id
                )
              }
              onUpdate={(field, value) =>
                updateShot(shot.shot_id, field, value)
              }
            />
          ))}
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={() => navigate(`/concepts/${slug}/characters`)}
          >
            Back
          </Button>
          <Button onClick={handleApprove} disabled={saving} size="lg">
            {saving ? "Saving..." : "Approve Director"}
          </Button>
        </div>
      </div>
    </div>
  )
}
