import { useState } from "react"
import Markdown from "react-markdown"
import { Img } from "@/components/Img"
import { Card, CardContent } from "@/components/ui/card"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import type { ConceptData } from "@/types"

interface Props {
  concept: ConceptData
}

export function ConceptProgression({ concept }: Props) {
  const [planOpen, setPlanOpen] = useState(true)
  const frames = concept.frames ?? []

  // Group frames by shot name
  const groups: Record<string, typeof frames> = {}
  for (const f of frames) {
    const base = f.name
      .replace(/_v\d+$/, "")
      .replace(/_final$/, "")
      .replace(/_st$/, "")
    if (!groups[base]) groups[base] = []
    groups[base].push(f)
  }

  const groupEntries = Object.entries(groups)

  return (
    <div className="space-y-6">
      {/* Plan — the core creative doc */}
      {concept.plan && (
        <Collapsible open={planOpen} onOpenChange={setPlanOpen}>
          <CollapsibleTrigger className="text-sm text-primary/80 hover:text-primary transition-colors cursor-pointer">
            {planOpen ? "Hide plan" : "View plan"}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3">
            <Card className="bg-card/60 border-border/50">
              <CardContent className="max-h-[600px] overflow-y-auto">
                <div className="prose prose-invert prose-sm max-w-none prose-headings:font-semibold prose-headings:tracking-tight prose-h1:text-lg prose-h2:text-base prose-h3:text-sm prose-p:text-muted-foreground prose-p:leading-relaxed prose-li:text-muted-foreground prose-strong:text-foreground prose-code:text-primary/80 prose-code:bg-primary/5 prose-code:px-1 prose-code:rounded prose-hr:border-border/50">
                  <Markdown>{concept.plan}</Markdown>
                </div>
              </CardContent>
            </Card>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Filmstrip */}
      {frames.length > 0 && (
        <ScrollArea className="w-full">
          <div className="flex gap-4 pb-3 px-2">
            {groupEntries.map(([groupName, groupFrames], gi) => (
              <div key={groupName} className="flex gap-3 flex-shrink-0">
                {gi > 0 && (
                  <div className="w-px bg-border self-stretch flex-shrink-0" />
                )}
                {groupFrames.map((frame, i) => (
                  <div key={frame.name} className="flex-shrink-0 space-y-2">
                    <Img
                      src={frame.url}
                      alt={frame.name}
                      className="h-[200px] w-auto rounded-md object-cover"
                    />
                    <p className="text-xs text-muted-foreground font-mono text-center">
                      {frame.name.includes("_v")
                        ? `v${frame.name.split("_v").pop()}`
                        : frame.name.includes("_final")
                          ? "final"
                          : frame.name.includes("_st")
                            ? "transfer"
                            : `v${i + 1}`}
                    </p>
                  </div>
                ))}
              </div>
            ))}
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      )}
    </div>
  )
}
