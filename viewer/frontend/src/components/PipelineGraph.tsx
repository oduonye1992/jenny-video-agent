import { useMemo, useState, useCallback } from "react"
import {
  ReactFlow,
  type Node,
  type Edge,
  Position,
  Background,
  BackgroundVariant,
} from "@xyflow/react"
import dagre from "dagre"
import { Badge } from "@/components/ui/badge"
import type { PipelineNode, StepStatus } from "@/types"
import "@xyflow/react/dist/style.css"

interface Props {
  nodes: PipelineNode[]
  steps: Record<string, StepStatus>
}

const NODE_WIDTH = 180
const NODE_HEIGHT = 52

function getStatusColor(status?: string): string {
  switch (status) {
    case "completed":
      return "#10b981" // emerald-500
    case "failed":
      return "#f43f5e" // rose-500
    case "running":
      return "#f59e0b" // amber-500
    default:
      return "#3f3f46" // zinc-700
  }
}

function getStatusBg(status?: string): string {
  switch (status) {
    case "completed":
      return "#10b98115"
    case "failed":
      return "#f43f5e15"
    case "running":
      return "#f59e0b15"
    default:
      return "#18181b"
  }
}

function getSelectedBg(status?: string): string {
  switch (status) {
    case "completed":
      return "#10b98130"
    case "failed":
      return "#f43f5e30"
    case "running":
      return "#f59e0b30"
    default:
      return "#27272a"
  }
}

/** Pretty-print a node ID for display */
function formatNodeId(id: string): string {
  return id.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Filter out internal/noisy config keys */
const HIDDEN_CONFIG_KEYS = new Set(["output_filename", "output_dir"])

function layoutGraph(pipelineNodes: PipelineNode[], steps: Record<string, StepStatus>, selectedId: string | null) {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: "TB", ranksep: 60, nodesep: 30 })

  for (const node of pipelineNodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  }

  for (const node of pipelineNodes) {
    for (const dep of node.depends_on) {
      g.setEdge(dep, node.id)
    }
  }

  dagre.layout(g)

  const flowNodes: Node[] = pipelineNodes.map((node) => {
    const pos = g.node(node.id)
    const step = steps[node.id]
    const status = step?.status
    const isSelected = node.id === selectedId
    const borderColor = getStatusColor(status)
    const bgColor = isSelected ? getSelectedBg(status) : getStatusBg(status)
    const duration = step?.duration_s ? `${step.duration_s.toFixed(1)}s` : ""

    const beatName = formatNodeId(node.id)

    return {
      id: node.id,
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: {
        label: (
          <div className="text-center leading-tight cursor-pointer">
            <div className="text-[11px] font-semibold text-zinc-200 truncate">
              {beatName}
            </div>
            <div className="text-[11px] text-zinc-400 font-mono mt-0.5">
              {node.adapter}
              {duration ? ` · ${duration}` : ""}
            </div>
          </div>
        ),
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      style: {
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        background: bgColor,
        border: `${isSelected ? 2 : 1.5}px solid ${isSelected ? "#a1a1aa" : borderColor}`,
        borderRadius: 10,
        padding: "6px 10px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "pointer",
      },
    }
  })

  const flowEdges: Edge[] = []
  for (const node of pipelineNodes) {
    for (const dep of node.depends_on) {
      flowEdges.push({
        id: `${dep}->${node.id}`,
        source: dep,
        target: node.id,
        style: { stroke: "#3f3f46", strokeWidth: 1.5 },
        animated: steps[node.id]?.status === "running",
      })
    }
  }

  return { flowNodes, flowEdges }
}

function NodeDetail({ node, step }: { node: PipelineNode; step?: StepStatus }) {
  const [promptExpanded, setPromptExpanded] = useState(false)
  const [configExpanded, setConfigExpanded] = useState(false)
  const config = node.config || {}
  const prompt = config.prompt as string | undefined
  const configEntries = Object.entries(config).filter(
    ([k]) => k !== "prompt" && !HIDDEN_CONFIG_KEYS.has(k)
  )

  return (
    <div className="mt-3 p-3 rounded-lg bg-zinc-900/80 border border-zinc-700/50 space-y-2">
      {/* Header row — name, adapter, status, toggles */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-semibold text-zinc-200">{formatNodeId(node.id)}</span>
        <Badge variant="outline" className="text-[10px] font-mono text-zinc-400 border-zinc-600">
          {node.adapter}
        </Badge>
        {step?.status && (
          <Badge
            variant="outline"
            className={`text-[10px] font-mono ${
              step.status === "completed"
                ? "text-emerald-400 border-emerald-500/30"
                : step.status === "failed"
                ? "text-rose-400 border-rose-500/30"
                : step.status === "running"
                ? "text-amber-400 border-amber-500/30"
                : "text-zinc-400 border-zinc-600"
            }`}
          >
            {step.status}
          </Badge>
        )}
        {step?.duration_s != null && (
          <span className="text-[10px] font-mono text-zinc-500">{step.duration_s.toFixed(1)}s</span>
        )}
        {step?.cache_hit && (
          <Badge variant="outline" className="text-[10px] font-mono text-blue-400 border-blue-500/30">
            cached
          </Badge>
        )}
        {node.depends_on.length > 0 && (
          <span className="text-[10px] text-zinc-500 font-mono ml-auto">
            depends on: {node.depends_on.map(formatNodeId).join(", ")}
          </span>
        )}
      </div>

      {/* Error — always visible */}
      {step?.error && (
        <p className="text-xs text-rose-400 leading-relaxed">{step.error}</p>
      )}

      {/* Toggle buttons row */}
      <div className="flex gap-2">
        {prompt && (
          <button
            onClick={() => { setPromptExpanded(!promptExpanded); setConfigExpanded(false) }}
            className={`text-xs cursor-pointer border rounded-md px-2.5 py-1 transition-colors ${
              promptExpanded
                ? "text-zinc-200 border-zinc-500 bg-zinc-800"
                : "text-zinc-500 border-zinc-700 hover:text-zinc-300 hover:border-zinc-500"
            }`}
          >
            {promptExpanded ? "Hide prompt" : "Prompt"}
          </button>
        )}
        {configEntries.length > 0 && (
          <button
            onClick={() => { setConfigExpanded(!configExpanded); setPromptExpanded(false) }}
            className={`text-xs cursor-pointer border rounded-md px-2.5 py-1 transition-colors ${
              configExpanded
                ? "text-zinc-200 border-zinc-500 bg-zinc-800"
                : "text-zinc-500 border-zinc-700 hover:text-zinc-300 hover:border-zinc-500"
            }`}
          >
            {configExpanded ? "Hide config" : "Config"}
          </button>
        )}
      </div>

      {/* Expanded content */}
      {promptExpanded && prompt && (
        <pre className="text-xs text-zinc-400 font-mono whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto bg-zinc-950/50 rounded p-2.5">
          {prompt}
        </pre>
      )}
      {configExpanded && configEntries.length > 0 && (
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {configEntries.map(([key, value]) => (
            <Fragment key={key}>
              <span className="text-zinc-500 font-mono">{key}</span>
              <span className="text-zinc-400 font-mono truncate">
                {typeof value === "string" ? value : JSON.stringify(value)}
              </span>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}

// Need Fragment for the grid
import { Fragment } from "react"

export function PipelineGraph({ nodes: pipelineNodes, steps }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { flowNodes, flowEdges } = useMemo(
    () => layoutGraph(pipelineNodes, steps, selectedId),
    [pipelineNodes, steps, selectedId]
  )

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedId((prev) => (prev === node.id ? null : node.id))
  }, [])

  // Calculate height from layout
  const maxY = Math.max(...flowNodes.map((n) => n.position.y)) + NODE_HEIGHT + 40
  const height = Math.max(300, Math.min(maxY, 700))

  const selectedNode = selectedId ? pipelineNodes.find((n) => n.id === selectedId) : null
  const selectedStep = selectedId ? steps[selectedId] : undefined

  return (
    <div>
      <div style={{ height, width: "100%" }} className="rounded-lg overflow-hidden">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
          panOnDrag={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          minZoom={0.5}
          maxZoom={1.5}
          onNodeClick={onNodeClick}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#27272a" />
        </ReactFlow>
      </div>
      {selectedNode && (
        <NodeDetail node={selectedNode} step={selectedStep} />
      )}
    </div>
  )
}
