import { useState, useEffect, useCallback, useRef } from "react"

const BASE = ""

export function useApi<T>(url: string) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const hasLoaded = useRef(false)

  const refetch = useCallback(() => {
    // Only show loading spinner on initial fetch, not on refetches
    if (!hasLoaded.current) {
      setLoading(true)
      setError(null)
    }
    fetch(`${BASE}${url}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
        return r.json()
      })
      .then((d) => {
        setData(d)
        hasLoaded.current = true
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [url])

  useEffect(() => {
    // The effect starts the initial request; the request callbacks update state asynchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refetch()
  }, [refetch])

  return { data, loading, error, refetch }
}

export async function patchNodePrompt(
  runName: string,
  nodeId: string,
  prompt: string
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/runs/${runName}/nodes/${nodeId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function triggerRerun(
  runName: string,
  step?: string,
  adapter?: string
): Promise<{ ok: boolean; pid: number; message: string }> {
  const res = await fetch(`${BASE}/api/runs/${runName}/rerun`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step: step ?? null, adapter: adapter ?? null }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function regenerateShot(
  slug: string,
  nodeId: string,
  sourceRun: string,
  prompt?: string,
  adapter?: string,
): Promise<{ ok: boolean; pid: number; new_run: string; message: string }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/regenerate-shot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      node_id: nodeId,
      source_run: sourceRun,
      prompt: prompt ?? null,
      adapter: adapter ?? null,
    }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Stage-based Concept API (creative / director / status / characters / shots)
// ---------------------------------------------------------------------------

export async function getCreative(
  slug: string
): Promise<{ slug: string; creative: Record<string, unknown>; creative_md: string | null }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/creative`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function saveCreative(
  slug: string,
  creative: Record<string, unknown>
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/creative`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(creative),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function getDirector(
  slug: string
): Promise<{ slug: string; director: Record<string, unknown>; director_md: string | null }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/director`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function saveDirector(
  slug: string,
  director: Record<string, unknown>
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/director`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(director),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function getConceptStatus(
  slug: string
): Promise<{ stage: string; shots?: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/status`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function advanceConcept(
  slug: string,
  toStage: string
): Promise<{ ok: boolean; stage: string }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/advance`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_stage: toStage }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function listCharacters(
  slug: string
): Promise<Array<{ name: string; options: Array<{ name: string; url: string }>; selected_url: string | null }>> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/characters`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function selectCharacter(
  slug: string,
  name: string,
  filename: string
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/characters/${name}/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function listShotVersions(
  slug: string,
  shotId: string
): Promise<Array<Record<string, unknown>>> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/shots/${shotId}/versions`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function selectShotVersion(
  slug: string,
  shotId: string,
  version: number
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/shots/${shotId}/select-version`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function getPromptDiff(
  slug: string,
  shotId: string,
  v1: number,
  v2: number
): Promise<{ v1_prompt: string; v2_prompt: string; diff_lines: Array<{ type: string; text: string }> }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/shots/${shotId}/prompt-diff?v1=${v1}&v2=${v2}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function approveShot(
  slug: string,
  shotId: string
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/shots/${shotId}/approve`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function updateShotSpec(
  slug: string,
  shotId: string,
  updates: Record<string, unknown>
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/shots/${shotId}/spec`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function getConceptProgress(
  slug: string
): Promise<{ stage: string; shots: Array<Record<string, unknown>>; total_cost: number; elapsed_s: number }> {
  const res = await fetch(`${BASE}/api/concepts/${slug}/progress`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function createProject(
  sourceUrl?: string,
  brief?: string,
  notes?: string
): Promise<{ ok: boolean; slug: string; stage: string }> {
  const res = await fetch(`${BASE}/api/projects/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_url: sourceUrl, brief, notes }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Plan API (legacy, preserved for compat)
// ---------------------------------------------------------------------------

export async function generatePlan(
  brief: string,
  profile: string = "cheap",
  aspectRatio: string = "9:16"
): Promise<{ ok: boolean; slug: string; plan: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/api/plans/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief, profile, aspect_ratio: aspectRatio }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function getPlan(
  slug: string
): Promise<{ slug: string; plan_json: Record<string, unknown> | null; plan_md?: string }> {
  const res = await fetch(`${BASE}/api/plans/${slug}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function savePlan(
  slug: string,
  plan: Record<string, unknown>
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/plans/${slug}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(plan),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function updatePlan(
  slug: string,
  updates: Record<string, unknown>
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/plans/${slug}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function updateShot(
  slug: string,
  shotIndex: number,
  updates: Record<string, unknown>
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/plans/${slug}/shots/${shotIndex}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function optimizeShotPrompt(
  slug: string,
  shotIndex: number,
  model: string
): Promise<{ ok: boolean; prompt: string }> {
  const res = await fetch(`${BASE}/api/plans/${slug}/shots/${shotIndex}/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}
