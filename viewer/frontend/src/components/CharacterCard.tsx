import { Img } from "@/components/Img"
import { Card, CardContent } from "@/components/ui/card"
import type { Character } from "@/types"

interface Props {
  character: Character
  anchorFrameUrl?: string | null
}

export function CharacterCard({ character, anchorFrameUrl }: Props) {
  return (
    <Card className="bg-card/40 border-border/50">
      <CardContent className="flex gap-5 items-start">
        {anchorFrameUrl && (
          <Img
            src={anchorFrameUrl}
            alt={character.name}
            className="w-32 h-32 rounded-lg object-cover flex-shrink-0"
          />
        )}
        <div className="space-y-1">
          <p className="text-lg font-semibold tracking-tight">{character.name}</p>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {character.description}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
