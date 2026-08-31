import type { DiffLine } from "@/types"

export function PromptDiff({ lines }: { lines: DiffLine[] }) {
  if (lines.length === 0) {
    return <p className="text-muted-foreground text-sm">No differences.</p>
  }

  return (
    <pre className="text-xs font-mono leading-relaxed rounded-lg bg-muted/5 p-4 overflow-x-auto">
      {lines.map((line, i) => (
        <div
          key={i}
          className={`
            px-2 -mx-2 rounded-sm
            ${line.type === "add" ? "bg-emerald-500/10 text-emerald-400" : ""}
            ${line.type === "remove" ? "bg-rose-500/10 text-rose-400" : ""}
            ${line.type === "same" ? "text-muted-foreground" : ""}
          `}
        >
          <span className="select-none opacity-80 mr-2">
            {line.type === "add" ? "+" : line.type === "remove" ? "-" : " "}
          </span>
          {line.text}
        </div>
      ))}
    </pre>
  )
}
