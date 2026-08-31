import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { createProject } from "@/hooks/use-api"

type Mode = "video" | "brief"

export function NewProject() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>("brief")
  const [sourceUrl, setSourceUrl] = useState("")
  const [brief, setBrief] = useState("")
  const [notes, setNotes] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    try {
      const result = await createProject(
        mode === "video" ? sourceUrl || undefined : undefined,
        mode === "brief" ? brief || undefined : undefined,
        notes || undefined
      )
      navigate(`/concepts/${result.slug}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create project")
    } finally {
      setLoading(false)
    }
  }

  const canGenerate = mode === "video" ? sourceUrl.trim() : brief.trim()

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-2xl mx-auto space-y-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">New Project</h1>
          <p className="text-muted-foreground mt-1">Start from a competitor video or a text brief.</p>
        </div>

        {/* Mode toggle */}
        <div className="flex gap-2">
          <button
            onClick={() => setMode("brief")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              mode === "brief"
                ? "bg-primary text-primary-foreground"
                : "bg-muted/10 text-muted-foreground hover:bg-muted/20"
            }`}
          >
            From a brief
          </button>
          <button
            onClick={() => setMode("video")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              mode === "video"
                ? "bg-primary text-primary-foreground"
                : "bg-muted/10 text-muted-foreground hover:bg-muted/20"
            }`}
          >
            From a video
          </button>
        </div>

        <Card className="bg-card/40 border-border/50">
          <CardContent className="space-y-6 pt-6">
            {mode === "video" ? (
              <div className="space-y-2">
                <label className="text-sm font-medium">Video URL</label>
                <Textarea
                  placeholder="Paste a TikTok, Instagram, or YouTube URL..."
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                  rows={2}
                  className="bg-background/50"
                />
              </div>
            ) : (
              <div className="space-y-2">
                <label className="text-sm font-medium">Brief or script</label>
                <Textarea
                  placeholder="Describe the video you want to make, or paste a full script..."
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                  rows={6}
                  className="bg-background/50"
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium text-muted-foreground">Notes (optional)</label>
              <Textarea
                placeholder="Target audience, tone, things to avoid..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                className="bg-background/50"
              />
            </div>

            {error && (
              <p className="text-sm text-rose-400">{error}</p>
            )}

            <Button
              onClick={handleGenerate}
              disabled={!canGenerate || loading}
              className="w-full"
              size="lg"
            >
              {loading ? "Creating project..." : "Generate"}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
