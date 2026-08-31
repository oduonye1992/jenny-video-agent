import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Img } from "@/components/Img"
import { StageStepper } from "@/components/StageStepper"
import { useApi, selectCharacter, advanceConcept } from "@/hooks/use-api"
import type { CharacterGenState } from "@/types"

function CharacterPanel({
  character,
  slug,
  onSelected,
}: {
  character: CharacterGenState
  slug: string
  onSelected: () => void
}) {
  async function handleSelect(filename: string) {
    await selectCharacter(slug, character.name, filename)
    onSelected()
  }

  return (
    <Card className="bg-card/40 border-border/50">
      <CardContent className="pt-4 space-y-4">
        <h3 className="text-lg font-semibold">{character.name}</h3>

        {character.options.length === 0 ? (
          <div className="text-muted-foreground text-sm">
            No reference images generated yet. Use the agent to generate character options.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {character.options.map((opt) => {
              const isSelected = character.selected_url === opt.url
              return (
                <button
                  key={opt.name}
                  onClick={() => handleSelect(opt.name)}
                  className={`relative rounded-lg overflow-hidden transition-all ${
                    isSelected
                      ? "ring-2 ring-primary ring-offset-2 ring-offset-background"
                      : "hover:ring-1 hover:ring-border"
                  }`}
                >
                  <Img
                    src={opt.url}
                    alt={opt.name}
                    className="w-full aspect-[3/4] object-cover"
                  />
                  {isSelected && (
                    <div className="absolute top-2 right-2 w-6 h-6 rounded-full bg-primary flex items-center justify-center">
                      <span className="text-primary-foreground text-xs">✓</span>
                    </div>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function CharacterGeneration() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { data, loading, error, refetch } = useApi<CharacterGenState[]>(
    `/api/concepts/${slug}/characters`
  )

  async function handleContinue() {
    if (!slug) return
    await advanceConcept(slug, "director")
    navigate(`/concepts/${slug}/director`)
  }

  const allSelected = data ? data.every((c) => c.selected_url) : false

  if (loading) return <div className="p-8 text-muted-foreground">Loading characters...</div>
  if (error) return <div className="p-8 text-rose-400">Error: {error}</div>

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Character Generation</h1>
            <p className="text-muted-foreground mt-1">
              Select or generate reference images for each character.
            </p>
          </div>
          <StageStepper current="characters" />
        </div>

        {(!data || data.length === 0) ? (
          <Card className="bg-card/40 border-border/50">
            <CardContent className="py-12 text-center">
              <p className="text-muted-foreground">
                No characters generated yet. Use the agent to create character reference photos,
                then refresh this page.
              </p>
              <Button variant="outline" className="mt-4" onClick={refetch}>
                Refresh
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-6">
            {data.map((character) => (
              <CharacterPanel
                key={character.name}
                character={character}
                slug={slug!}
                onSelected={refetch}
              />
            ))}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={() => navigate(`/concepts/${slug}/creative`)}
          >
            Back
          </Button>
          <Button onClick={handleContinue} disabled={!allSelected} size="lg">
            Lock & Continue
          </Button>
        </div>
      </div>
    </div>
  )
}
