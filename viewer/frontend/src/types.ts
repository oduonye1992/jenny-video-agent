export interface RunListItem {
  run_name: string
  complete: boolean
  failed: boolean
  elapsed_s: number | null
  cost: number | null
  shot_count: number
  character_name: string | null
  video_type: string | null
  started: string | null
  thumbnail: string | null
  concept_slug: string | null
}

export interface ConceptFrame {
  name: string
  url: string
  prompt: string | null
  modified: number
}

export interface ConceptClip {
  name: string
  url: string
  prompt: string | null
  modified: number
}

export interface ShotAnchor {
  name: string
  url: string
  prompt?: string | null
}

export interface ShotDetail {
  shot_id: string
  anchors?: ShotAnchor[]
  prompts?: Record<string, string>
}

export interface VideoAsset {
  filename: string
  url: string
  prompt: string | null
  anchor_url?: string | null
  anchor_prompt?: string | null
  size_mb: number
  modified: number
  run_label?: string
}

export interface ConceptInput {
  brief: string
  source_url?: string | null
  source_video?: string | null
  video_type?: string | null
  duration?: number | null
  profile?: string
  mode?: string
  notes?: string
  created?: string
}

export interface ConceptData {
  slug: string
  path: string
  plan?: string
  character_description?: string
  character_refs?: Array<{ name: string; url: string }>
  frames?: ConceptFrame[]
  clips?: ConceptClip[]
  voices?: Array<{ name: string; url: string }>
  shot_descriptions?: Record<string, string>
  narration?: string
  concept_json?: Record<string, unknown>
  // 5-stage flow
  input?: ConceptInput
  creative?: Creative
  director?: Director
  director_md?: string
  shot_details?: ShotDetail[]
  video_assets?: VideoAsset[]
}

export interface StepStatus {
  status: "pending" | "running" | "completed" | "failed"
  adapter: string
  duration_s?: number
  output?: string
  error?: string
  retries?: number
  cache_hit?: boolean
  cache_key?: string
}

export interface CostBreakdown {
  step: string
  adapter: string
  cost: number
}

export interface RunStatus {
  job_id: string
  started: string
  updated: string
  complete: boolean
  failed: boolean
  elapsed_s: number
  total_step_duration_s: number
  steps: Record<string, StepStatus>
  fallbacks_used: string[]
  errors: Array<{ step: string; error: string; retries?: number }>
  cost?: {
    total: number
    breakdown: CostBreakdown[]
    currency: string
  }
  completed_at?: string
}

export interface PipelineNode {
  id: string
  adapter: string
  config: Record<string, unknown>
  depends_on: string[]
}

export interface Pipeline {
  pipeline_version: number
  run_name: string
  output_dir: string
  nodes: PipelineNode[]
}

export interface Shot {
  shot_id: string
  name: string
  duration: number
  video_prompt?: string
  scene?: string
  camera?: string
  lighting?: string
  color_grade?: string
  style?: string
  reference_image?: string
  wardrobe_top?: string
}

export interface Character {
  name: string
  description: string
}

export interface ProductionSpec {
  version: number
  video_type: string
  run_name: string
  profile: string
  aspect_ratio: string
  max_budget: number
  character?: Character
  shots?: Shot[]
  models?: Record<string, { adapter: string }>
  output?: { dir: string; final_filename: string }
}

export interface ShotVersion {
  version: number
  url: string
  filename: string
  modified: number
}

export interface RunDetail {
  run_name: string
  status: RunStatus
  pipeline: Pipeline
  spec: ProductionSpec | null
  prompts: Record<string, string>
  assets: Record<string, string>
  versions: Record<string, ShotVersion[]>
  concept: ConceptData | null
}

export interface RunShot {
  node_id: string
  adapter: string
  prompt: string
  status: "pending" | "running" | "completed" | "failed"
  duration_s: number | null
  output_url: string | null
  upscaled_url: string | null
  cost: number | null
}

export interface ConceptRun {
  run_name: string
  label: string
  complete: boolean
  failed: boolean
  elapsed_s: number | null
  total_cost: number | null
  estimated_cost: number | null
  shots: RunShot[]
  final_video: string | null
  thumbnail: string | null
  character_name: string | null
  assets: Record<string, string>
  pipeline?: Pipeline
  status?: RunStatus
}

export interface ConceptDetail extends ConceptData {
  runs: ConceptRun[]
}

// ── Stage-based Pipeline (creative.json / director.json) ─────────

export type ConceptStage = "intake" | "creative" | "characters" | "director" | "production" | "review" | "done"

// Creative schema (story document)

export interface CreativeCharacter {
  name: string
  who: string
  age: string
  ethnicity: string
  hair: string
  wardrobe: string
  voice: string
}

export interface CreativeBeat {
  name: string
  role: string
  type: PlanShotType
  duration: number
  emotion: string
  action_summary: string
  dialogue: string
  voiceover: string
  text_overlay: string
}

export interface CreativeAudio {
  music_direction: string
  voice_direction: string
  audio_strategy: PlanAudioStrategy
}

export interface Creative {
  version: number
  title: string
  angle: string
  arc: string[]
  character: CreativeCharacter
  beats: CreativeBeat[]
  audio: CreativeAudio
  hook_variations: string[]
  compliance_notes: string
  target_duration: number
  target_platform: string
  status: "draft" | "approved"
}

// Director schema (production document)

export interface DirectorCharacterRef {
  name: string
  physical_description: string
  wardrobe: string
  accessories: string
  reference_photos: string[]
}

export interface DirectorAudioPlan {
  strategy: PlanAudioStrategy
  dialogue: string
  dialogue_delivery: string
  voiceover: string
  voiceover_delivery: string
  ambient: string
}

export interface DirectorFramePlan {
  strategy: PlanFrameSource
  reference_query: string
  edit_from_shot: string | null
  chain_from_shot: string | null
  anchor_group: string | null
  image_prompt: Record<string, unknown> | null
  generated_frame: string | null
}

export interface DirectorShot {
  shot_id: string
  beat_name: string
  beat_role: string
  type: PlanShotType
  duration: number
  visual_vo_relationship?: string
  setting: string
  camera: string
  lighting: string
  color_grade: string
  action: string
  imperfection: string
  character: DirectorCharacterRef
  audio: DirectorAudioPlan
  frame: DirectorFramePlan
  avoid: string[]
  content_hash: string
  status: PlanShotStatus
}

export interface Director {
  version: number
  creative_version: number
  format?: string
  aspect_ratio: string
  profile: string
  shots: DirectorShot[]
  music_prompt: string
  voice_design_prompt: string
  voice_id: string | null
  status: "draft" | "framed" | "prompted" | "ready"
}

// Character generation

export interface CharacterOption {
  name: string
  url: string
}

export interface CharacterGenState {
  name: string
  options: CharacterOption[]
  selected_url: string | null
}

// Per-shot versions

export interface ShotVersionDetail {
  version: number
  frame_url?: string
  clip_url?: string
  clip_upscaled_url?: string
  prompt?: string
  meta?: Record<string, unknown>
  created_at: number
}

export interface ShotProgress {
  name: string
  shot_id: string
  stage: "pending" | "frame" | "video" | "upscale" | "complete" | "failed"
  progress_pct: number
  thumbnail_url: string | null
  cost: number
  error?: string
}

// Concept status

export interface ConceptStatus {
  stage: ConceptStage
  shots?: ShotProgress[]
  total_cost?: number
  elapsed_s?: number
}

// Prompt diff

export interface DiffLine {
  type: "add" | "remove" | "same"
  text: string
}

export interface PromptDiff {
  v1_prompt: string
  v2_prompt: string
  diff_lines: DiffLine[]
}

// ── Structured Plan (plan.json) — legacy, preserved for compat ───

export type PlanShotType = "TALKING_HEAD" | "B-ROLL" | "PRODUCT" | "MONTAGE"
export type PlanAudioStrategy = "native" | "voiceover_plus_music" | "music_only" | "silent"
export type PlanFrameSource = "pinterest" | "reference_photo" | "text-to-image" | "edit_from" | "chain_from" | "existing"
export type PlanShotStatus = "draft" | "prompted" | "framed" | "ready" | "generating" | "done" | "failed"
export type PlanStatus = "draft" | "review" | "approved" | "framing" | "framed" | "producing" | "done" | "failed"

export interface PlanCharacter {
  name: string
  age: string
  ethnicity: string
  hair: string
  wardrobe: string
  face: string
  build: string
  accessories: string
  description: string
}

export interface PlanShotPrompts {
  kling_v3: string | null
  veo_v3: string | null
  sora_v2: string | null
  kling_v2: string | null
  seedance_v1_5: string | null
  hailuo_02: string | null
}

export interface PlanShot {
  name: string
  type: PlanShotType
  duration: number
  direction: string
  setting: string
  camera: string
  lighting: string
  dialogue: string
  voiceover: string
  text_overlay: string
  audio: PlanAudioStrategy
  frame_source: PlanFrameSource
  frame_source_ref: string
  selected_model: string
  prompts: PlanShotPrompts
  image_prompt: Record<string, unknown> | null
  start_frame: string | null
  status: PlanShotStatus
}

export interface PlanAudio {
  music_mood: string
  music_prompt: string
  voice_tone: string
  voice_prompt: string
}

export interface Plan {
  title: string
  angle: string
  arc: string[]
  character: PlanCharacter
  shots: PlanShot[]
  audio: PlanAudio
  profile: string
  aspect_ratio: string
  status: PlanStatus
  slug: string
  hook_variations: string[]
  compliance_notes: string
}
