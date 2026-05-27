import { getEngineUrl } from "@/lib/engineUrl";

export class EngineError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EngineError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const baseUrl = await getEngineUrl();
  let res: Response;
  try {
    res = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Network error";
    throw new EngineError(
      msg === "Failed to fetch"
        ? "Could not reach the MidiWeaver engine. Check that it is running."
        : msg,
    );
  }
  if (!res.ok) {
    const text = await res.text();
    let detail = text || res.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: string | string[] };
      if (parsed.detail) {
        detail = Array.isArray(parsed.detail) ? parsed.detail.join("; ") : String(parsed.detail);
      }
    } catch {
      /* use raw text */
    }
    throw new EngineError(detail);
  }
  return res.json() as Promise<T>;
}

export interface TimelineData {
  master_ppq: number;
  segments: SongSegment[];
  transitions: TransitionConfig[];
  tempo_events: { tick: number; bpm: number }[];
  total_ticks: number;
  total_bars: number;
}

export interface SongSegment {
  id: string;
  display_name: string;
  source_filename: string;
  master_start_tick: number;
  master_end_tick: number;
  analysis?: AnalysisSnapshot;
}

export interface AnalysisSnapshot {
  song_id: string;
  ppq: number;
  bar_count: number;
  estimated_bpm: number;
  bpm_range: [number, number];
  time_sig: [number, number];
  key?: string;
  track_summaries: TrackSummary[];
  tracks: TrackData[];
  trim_start_tick: number;
  trim_end_tick?: number;
}

export interface TrackSummary {
  track_id: string;
  name: string;
  is_drum: boolean;
  note_count: number;
}

export interface TrackData {
  track_id: string;
  name: string;
  channel?: number;
  program?: number;
  is_drum: boolean;
  notes: NoteEvent[];
  master_track_id?: string;
  mute?: boolean;
  solo?: boolean;
  volume?: number;
  snap_override?: string;
  quantize_enabled?: boolean;
  quantize_strength?: number;
}

export interface NoteEvent {
  pitch: number;
  start_tick: number;
  duration_ticks: number;
  velocity: number;
  channel?: number;
}

export interface TransitionConfig {
  id: string;
  from_song_id: string;
  to_song_id: string;
  duration_bars: number;
  mix_out_bars: number;
  mix_in_bars: number;
  master_start_bar: number;
  master_end_bar: number;
  template_id?: string;
}

export interface Operation {
  op_type: string;
  params: Record<string, unknown>;
  enabled?: boolean;
  description?: string;
}

export interface TempoOption {
  label: string;
  policy: string;
  duration_bars: number;
  start_bpm: number;
  end_bpm: number;
}

export interface PlanStep {
  id: string;
  description: string;
  intent?: string;
  suggested_tool?: string | null;
  suggested_params?: Record<string, unknown>;
  verify?: Record<string, unknown> | null;
}

export interface ArrangementPlan {
  plan_summary: string;
  steps: PlanStep[];
  tempo_options: TempoOption[];
  selected_tempo_option_index?: number;
  constraints_applied?: Record<string, unknown>;
  legacy_ops?: Operation[];
}

export interface AgentStepLog {
  step_index: number;
  tool_name: string;
  tool_args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  revision_id?: number | null;
  error?: string | null;
}

export interface OperationPlan {
  plan_summary: string;
  tempo_options: TempoOption[];
  selected_tempo_option_index?: number;
  ops: Operation[];
}

export interface Revision {
  id: number;
  label: string;
  ops: Operation[];
  diff?: RevisionDiff;
}

export interface RevisionDiff {
  added_notes: Record<string, unknown>[];
  removed_notes: Record<string, unknown>[];
  moved_notes: Record<string, unknown>[];
  tempo_changes: Record<string, unknown>[];
}

export interface ExportReport {
  output_path: string;
  format: string;
  track_count: number;
  tempo_ramps_applied: number;
  warnings: string[];
  unmapped_tracks: string[];
  key_clashes: string[];
}

export interface TrackMappingEntry {
  master_track_id: string;
  role: string;
  song_track_ids: Record<string, string>;
}

export interface EngineSettings {
  ai_base_url?: string;
  ai_model?: string;
  ai_api_key_configured?: boolean;
  ollama_base_url?: string;
  ollama_enabled?: boolean;
  audio_backend?: string;
  soundfont_path?: string;
  midi_device?: string;
}

export interface AiTestConnectionResult {
  ok: boolean;
  model?: string;
  message?: string;
  error?: string;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  getSettings: () => request<EngineSettings>("/api/settings"),
  updateSettings: (body: Record<string, unknown>) =>
    request<EngineSettings>("/api/settings", { method: "POST", body: JSON.stringify(body) }),

  testAiConnection: () =>
    request<AiTestConnectionResult>("/api/ai/test-connection", { method: "POST" }),

  createProject: (path: string, name: string) =>
    request<{ path: string }>("/api/projects/create", {
      method: "POST",
      body: JSON.stringify({ path, name, master_ppq: 480 }),
    }),

  openProject: (path: string) =>
    request<{ timeline: TimelineData; meta: Record<string, unknown> }>("/api/projects/open", {
      method: "POST",
      body: JSON.stringify({ path, name: "" }),
    }),

  getTimeline: (projectPath: string) =>
    request<TimelineData>(`/api/projects/${encodeURIComponent(projectPath)}/timeline`),

  importMidi: async (projectPath: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ segment: SongSegment; timeline: TimelineData }>(
      `/api/projects/import?project_path=${encodeURIComponent(projectPath)}`,
      { method: "POST", body: form },
    );
  },

  applyOps: (projectPath: string, ops: Operation[], label?: string) =>
    request<{ revision: Revision; timeline: TimelineData }>("/api/projects/apply-ops", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, ops, label }),
    }),

  undo: (projectPath: string) =>
    request<{ revision: Revision | null; timeline: TimelineData }>(
      `/api/projects/undo?project_path=${encodeURIComponent(projectPath)}`,
      { method: "POST" },
    ),

  redo: (projectPath: string) =>
    request<{ revision: Revision | null; timeline: TimelineData }>(
      `/api/projects/redo?project_path=${encodeURIComponent(projectPath)}`,
      { method: "POST" },
    ),

  getHistoryState: (projectPath: string) =>
    request<{ undo_pointer: number; max_revision: number }>(
      `/api/projects/${encodeURIComponent(projectPath)}/history`,
    ),

  compareRevisions: (projectPath: string, revA: number, revB: number) =>
    request<RevisionDiff>(
      `/api/projects/${encodeURIComponent(projectPath)}/diff?rev_a=${revA}&rev_b=${revB}`,
    ),

  updateTrackMapping: (projectPath: string, mapping: TrackMappingEntry[]) =>
    request<{ status: string }>("/api/projects/track-mapping", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, mapping }),
    }),

  reorderSongs: (projectPath: string, songIds: string[]) =>
    request<{ timeline: TimelineData }>("/api/projects/reorder-songs", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, song_ids: songIds }),
    }),

  aiPlan: (body: {
    project_path: string;
    user_prompt: string;
    selection: Record<string, unknown>;
    constraints?: Record<string, unknown>;
    mock?: boolean;
  }) =>
    request<{
      plan: ArrangementPlan;
      plan_id: string;
      payload: Record<string, unknown>;
      mode: "live" | "mock";
    }>("/api/ai/plan", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  aiAsk: (body: {
    project_path: string;
    messages: { role: string; content: string }[];
    selection?: Record<string, unknown>;
    mock?: boolean;
  }) =>
    request<{ message: string; tool_calls?: unknown[]; mode: string }>("/api/ai/ask", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  agentRun: (body: {
    project_path: string;
    prompt: string;
    selection?: Record<string, unknown>;
    session_id?: string;
    plan_id?: string;
    mock?: boolean;
  }) =>
    request<{
      session_id: string;
      status: string;
      summary?: string;
      steps: AgentStepLog[];
      timeline?: TimelineData;
      mode?: string;
    }>("/api/ai/agent/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  agentCancel: (sessionId: string) =>
    request<{ status: string }>("/api/ai/agent/cancel", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),

  agentSession: (sessionId: string) =>
    request<Record<string, unknown>>(`/api/ai/agent/session/${encodeURIComponent(sessionId)}`),

  dryRunOps: (projectPath: string, ops: Operation[]) =>
    request<RevisionDiff>("/api/projects/dry-run-ops", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, ops }),
    }),

  queryTimeline: (projectPath: string) =>
    request<Record<string, unknown>>(
      `/api/projects/${encodeURIComponent(projectPath)}/query/timeline`,
    ),

  applyPlan: (
    projectPath: string,
    plan: OperationPlan,
    enabledOpIndices?: number[],
    transitionId?: string,
  ) =>
    request<{ revision: Revision; timeline: TimelineData }>("/api/ai/apply-plan", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        plan,
        enabled_op_indices: enabledOpIndices,
        transition_id: transitionId,
      }),
    }),

  saveTemplate: (projectPath: string, name: string, transitionId: string, constraints: Record<string, unknown>) =>
    request<{ template_id: string }>("/api/templates/save", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        name,
        transition_id: transitionId,
        constraints,
      }),
    }),

  listTemplates: (projectPath: string) =>
    request<{ id: string; name: string }[]>(`/api/templates/${encodeURIComponent(projectPath)}`),

  applyTemplate: (projectPath: string, templateId: string, fromSongId: string, toSongId: string) =>
    request<{ timeline: TimelineData }>("/api/templates/apply", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        template_id: templateId,
        from_song_id: fromSongId,
        to_song_id: toSongId,
      }),
    }),

  exportMidi: (projectPath: string, outputPath: string) =>
    request<ExportReport>("/api/export/midi", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, output_path: outputPath }),
    }),

  renderAudio: (projectPath: string, outputPath: string, format: "wav" | "ogg") =>
    request<{ wav?: string; ogg?: string }>("/api/audio/render", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, output_path: outputPath, format }),
    }),

  transport: (action: string, tick = 0, projectPath?: string) =>
    request<{ playing: boolean; position_tick: number; error?: string | null }>("/api/audio/transport", {
      method: "POST",
      body: JSON.stringify({ action, tick, project_path: projectPath }),
    }),

  getTransport: () =>
    request<{ playing: boolean; position_tick: number; error?: string | null }>("/api/audio/transport"),

  updateMixer: (trackId: string, patch: { mute?: boolean; solo?: boolean; volume?: number }) =>
    request<Record<string, unknown>>("/api/audio/mixer", {
      method: "POST",
      body: JSON.stringify({ track_id: trackId, ...patch }),
    }),

  listDevices: () => request<{ midi_outputs: string[] }>("/api/audio/devices"),

  ollamaStatus: () => request<{ status: string; message: string }>("/api/ollama/status"),
};
