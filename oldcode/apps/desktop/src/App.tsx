import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Download,
  FolderOpen,
  Maximize2,
  Music,
  Plus,
  Redo2,
  Settings,
  Undo2,
  Upload,
  ZoomIn,
} from "lucide-react";
import {
  api,
  type Revision,
  type RevisionDiff,
  type TimelineData,
  type TrackMappingEntry,
} from "@/lib/api";
import { mixerTrackId } from "@/lib/utils";
import { Button, Badge } from "@/components/ui/button";
import { MasterTimeline } from "@/features/timeline/MasterTimeline";
import { PianoRoll, type TrackScopeMode } from "@/features/timeline/PianoRoll";
import { projectTotalTicks, tickRangeToBarRange } from "@/features/timeline/timelineUtils";
import { useTimelineViewport } from "@/features/timeline/useTimelineViewport";
import { TransportBar } from "@/features/transport/TransportBar";
import { AIPanel } from "@/features/ai-planner/AIPanel";
import { TrackMappingPanel } from "@/features/mapping/TrackMappingPanel";
import { SettingsPanel } from "@/features/settings/SettingsPanel";
import {
  pickExportPath,
  pickNewProjectPath,
  pickProjectFolder,
  projectNameFromPath,
} from "@/lib/projectDialogs";

export default function App() {
  const [engineOk, setEngineOk] = useState(false);
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [playheadTick, setPlayheadTick] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [followPlayhead, setFollowPlayhead] = useState(false);
  const [snap, setSnap] = useState("bar");
  const [showSettings, setShowSettings] = useState(false);
  const [status, setStatus] = useState("");
  const [lastDiff, setLastDiff] = useState<RevisionDiff | null>(null);
  const [trackMapping, setTrackMapping] = useState<TrackMappingEntry[]>([]);
  const [sidebarTab, setSidebarTab] = useState<"songs" | "mapping" | "ai">("ai");
  const [transportError, setTransportError] = useState<string | null>(null);
  const [selectedTrackIds, setSelectedTrackIds] = useState<Set<string>>(new Set());
  const [trackScopeMode, setTrackScopeMode] = useState<TrackScopeMode>("all");
  const [aiKeyConfigured, setAiKeyConfigured] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  const forceMockAi = import.meta.env.VITE_AI_MOCK === "true";
  const aiMode: "live" | "mock" = forceMockAi || !aiKeyConfigured ? "mock" : "live";

  const ppq = timeline?.master_ppq ?? 480;
  const totalTicks = projectTotalTicks(timeline, ppq);

  const viewport = useTimelineViewport(totalTicks, ppq);

  const {
    scrollStartTick,
    viewRange,
    editRange,
    pxPerTick,
    setViewportWidthPx,
    setScrollStartTick,
    setViewRange,
    setEditRange,
    zoomAt,
    zoomToEditRange,
    zoomFitAll,
  } = viewport;

  useEffect(() => {
    if (timeline && totalTicks > 0) {
      zoomFitAll();
    }
    // Only refit when project timeline identity changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeline?.total_ticks, timeline?.segments.length]);

  const refreshTimeline = useCallback(async (path: string) => {
    const tl = await api.getTimeline(path);
    setTimeline(tl);
    return tl;
  }, []);

  const refreshHistoryState = useCallback(async (path: string) => {
    try {
      const h = await api.getHistoryState(path);
      setCanUndo(h.undo_pointer > 0);
      setCanRedo(h.undo_pointer < h.max_revision);
    } catch {
      setCanUndo(false);
      setCanRedo(false);
    }
  }, []);

  const applyRevisionResult = useCallback(
    (result: { revision: Revision | null; timeline: TimelineData }) => {
      setTimeline(result.timeline);
      setLastDiff(result.revision?.diff ?? null);
    },
    [],
  );

  const performUndo = useCallback(async () => {
    if (!projectPath || !canUndo) return;
    try {
      const result = await api.undo(projectPath);
      applyRevisionResult(result);
      await refreshHistoryState(projectPath);
      if (result.revision) {
        setStatus(`Undo: ${result.revision.label}`);
      }
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Undo failed");
    }
  }, [projectPath, canUndo, applyRevisionResult, refreshHistoryState]);

  const performRedo = useCallback(async () => {
    if (!projectPath || !canRedo) return;
    try {
      const result = await api.redo(projectPath);
      applyRevisionResult(result);
      await refreshHistoryState(projectPath);
      if (result.revision) {
        setStatus(`Redo: ${result.revision.label}`);
      }
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Redo failed");
    }
  }, [projectPath, canRedo, applyRevisionResult, refreshHistoryState]);

  useEffect(() => {
    api.health().then(() => setEngineOk(true)).catch(() => setEngineOk(false));
    api.getSettings().then((s) => setAiKeyConfigured(Boolean(s.ai_api_key_configured)));
    const id = window.setInterval(() => {
      api.health().then(() => setEngineOk(true)).catch(() => setEngineOk(false));
    }, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!projectPath) return;
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      if (e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        void performUndo();
      } else if (e.key === "y" || (e.key === "z" && e.shiftKey)) {
        e.preventDefault();
        void performRedo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [projectPath, performUndo, performRedo]);

  useEffect(() => {
    if (!playing || !projectPath) return;
    const id = window.setInterval(async () => {
      const t = await api.getTransport();
      setPlayheadTick(t.position_tick);
      if (!t.playing) setPlaying(false);
    }, 150);
    return () => clearInterval(id);
  }, [playing, projectPath]);

  const seekTo = useCallback(
    async (tick: number) => {
      const clamped = Math.max(0, Math.min(totalTicks, tick));
      setPlayheadTick(clamped);
      if (!projectPath) return;
      try {
        await api.transport("seek", clamped, projectPath);
      } catch {
        /* engine may be offline */
      }
    },
    [projectPath, totalTicks],
  );

  const toggleTrack = useCallback((trackId: string) => {
    setSelectedTrackIds((prev) => {
      const next = new Set(prev);
      if (next.has(trackId)) next.delete(trackId);
      else next.add(trackId);
      return next;
    });
  }, []);

  const newProject = async () => {
    const path = await pickNewProjectPath();
    if (!path) return;
    try {
      const name = projectNameFromPath(path);
      await api.createProject(path, name);
      setProjectPath(path);
      await refreshTimeline(path);
      await refreshHistoryState(path);
      setStatus(`Created ${name}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed to create project");
    }
  };

  const openProject = async () => {
    const path = await pickProjectFolder();
    if (!path) return;
    try {
      const data = await api.openProject(path);
      setProjectPath(path);
      setTimeline(data.timeline);
      await refreshHistoryState(path);
      const mapping = (data.meta.track_mapping as TrackMappingEntry[] | undefined) ?? [];
      setTrackMapping(mapping);
      setStatus(`Opened ${projectNameFromPath(path)}`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed to open project");
    }
  };

  const importMidi = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !projectPath) return;
    const data = await api.importMidi(projectPath, file);
    setTimeline(data.timeline);
    if (projectPath) await refreshHistoryState(projectPath);
    setStatus(`Imported ${file.name}`);
    e.target.value = "";
  };

  const applyManualEdit = async (action: string, payload: Record<string, unknown>) => {
    if (!projectPath) return;
    const result = await api.applyOps(
      projectPath,
      [{ op_type: action, params: payload, enabled: true }],
      "Manual edit",
    );
    applyRevisionResult(result);
    await refreshHistoryState(projectPath);
  };

  const handleMixerChange = useCallback(
    async (trackId: string, patch: { mute?: boolean; solo?: boolean; volume?: number }) => {
      await api.updateMixer(trackId, patch);
      setTimeline((prev) => {
        if (!prev) return prev;
        const [songId, rawTrackId] = trackId.includes(":") ? trackId.split(":", 2) : [null, trackId];
        return {
          ...prev,
          segments: prev.segments.map((seg) => {
            if (songId && seg.id !== songId) return seg;
            if (!seg.analysis) return seg;
            return {
              ...seg,
              analysis: {
                ...seg.analysis,
                tracks: seg.analysis.tracks.map((track) => {
                  const id = mixerTrackId(seg.id, track.track_id);
                  if (id !== trackId && track.track_id !== rawTrackId) return track;
                  return { ...track, ...patch };
                }),
              },
            };
          }),
        };
      });
    },
    [],
  );

  const editBarRange = tickRangeToBarRange(editRange, ppq);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-2 border-b border-border bg-panel px-4 py-2">
        <Music className="h-5 w-5 text-accent" />
        <span className="font-semibold">MidiWeaver</span>
        <Badge className={engineOk ? "text-accent" : "text-error"}>
          {engineOk ? "Engine OK" : "Engine offline"}
        </Badge>
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          disabled={!projectPath || !canUndo}
          onClick={() => void performUndo()}
          title="Undo (Ctrl+Z)"
        >
          <Undo2 className="h-4 w-4" /> Undo
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={!projectPath || !canRedo}
          onClick={() => void performRedo()}
          title="Redo (Ctrl+Y)"
        >
          <Redo2 className="h-4 w-4" /> Redo
        </Button>
        <Button variant="ghost" size="sm" onClick={newProject}>
          <Plus className="h-4 w-4" /> New
        </Button>
        <Button variant="ghost" size="sm" onClick={openProject}>
          <FolderOpen className="h-4 w-4" /> Open
        </Button>
        <label className="cursor-pointer">
          <Button variant="ghost" size="sm" asChild>
            <span>
              <Upload className="h-4 w-4" /> Import
            </span>
          </Button>
          <input type="file" accept=".mid,.midi" className="hidden" onChange={importMidi} disabled={!projectPath} />
        </label>
        <Button
          variant="ghost"
          size="sm"
          disabled={!projectPath}
          onClick={async () => {
            if (!projectPath) return;
            const out = await pickExportPath();
            if (!out) return;
            try {
              const report = await api.exportMidi(projectPath, out);
              setStatus(`Exported ${report.track_count} tracks`);
            } catch (err) {
              setStatus(err instanceof Error ? err.message : "Export failed");
            }
          }}
        >
          <Download className="h-4 w-4" /> Export
        </Button>
        <Button variant="ghost" size="icon" onClick={() => setShowSettings(true)}>
          <Settings className="h-4 w-4" />
        </Button>
      </header>

      {status && (
        <div className="shrink-0 border-b border-border bg-surface px-4 py-1 text-xs text-muted">{status}</div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="flex w-56 shrink-0 flex-col overflow-hidden border-r border-border bg-panel p-2">
          <div className="mb-2 flex shrink-0 gap-1 text-xs">
            {(["songs", "mapping", "ai"] as const).map((t) => (
              <button
                key={t}
                type="button"
                className={`flex-1 rounded px-1 py-1 capitalize ${sidebarTab === t ? "bg-accent/20 text-accent" : "text-muted"}`}
                onClick={() => setSidebarTab(t)}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
          {sidebarTab === "songs" && (
            <div className="space-y-2 text-xs">
              {timeline?.segments.map((s, i) => (
                <div key={s.id} className="rounded border border-border bg-surface p-2">
                  <div className="font-medium">
                    {i + 1}. {s.display_name}
                  </div>
                  {s.analysis && (
                    <div className="text-muted">
                      {s.analysis.bar_count.toFixed(1)} bars · {s.analysis.estimated_bpm.toFixed(0)} BPM
                    </div>
                  )}
                </div>
              )) || <p className="text-muted">No songs</p>}
            </div>
          )}

          {sidebarTab === "mapping" && (
            <TrackMappingPanel
              timeline={timeline}
              trackMapping={trackMapping}
              onChange={setTrackMapping}
              disabled={!projectPath}
              onSave={async () => {
                if (!projectPath) return;
                await api.updateTrackMapping(projectPath, trackMapping);
                setStatus("Track mapping saved");
              }}
            />
          )}

          {sidebarTab === "ai" && projectPath && (
            <AIPanel
              aiMode={aiMode}
              diff={lastDiff}
              onAsk={async (messages) => {
                return api.aiAsk({
                  project_path: projectPath,
                  messages,
                  selection: {
                    scope: "edit",
                    master_bar_range: editBarRange,
                    track_ids:
                      trackScopeMode === "selected" && selectedTrackIds.size > 0
                        ? [...selectedTrackIds]
                        : undefined,
                  },
                  mock: forceMockAi,
                });
              }}
              onPlan={async (prompt, constraints) => {
                const result = await api.aiPlan({
                  project_path: projectPath,
                  user_prompt: prompt,
                  selection: {
                    scope: "edit",
                    master_bar_range: editBarRange,
                    track_ids:
                      trackScopeMode === "selected" && selectedTrackIds.size > 0
                        ? [...selectedTrackIds]
                        : undefined,
                  },
                  constraints,
                  mock: forceMockAi,
                });
                return { plan: result.plan, planId: result.plan_id, mode: result.mode };
              }}
              onAgentRun={async (prompt, planId) => {
                const result = await api.agentRun({
                  project_path: projectPath,
                  prompt,
                  plan_id: planId,
                  selection: {
                    scope: "edit",
                    master_bar_range: editBarRange,
                    track_ids:
                      trackScopeMode === "selected" && selectedTrackIds.size > 0
                        ? [...selectedTrackIds]
                        : undefined,
                  },
                  mock: forceMockAi,
                });
                const tl = result.timeline ?? (await refreshTimeline(projectPath));
                if (tl) {
                  setTimeline(tl);
                  await refreshHistoryState(projectPath);
                  const applySteps = result.steps.filter(
                    (s) => s.tool_name === "apply_op" && s.revision_id != null,
                  );
                  const lastApply = applySteps[applySteps.length - 1];
                  const diff = lastApply?.result?.diff as RevisionDiff | undefined;
                  if (
                    diff &&
                    (diff.added_notes.length > 0 ||
                      diff.removed_notes.length > 0 ||
                      diff.moved_notes.length > 0)
                  ) {
                    setLastDiff(diff);
                  }
                  zoomToEditRange();
                }
                setStatus(`Agent ${result.status}`);
                return result;
              }}
              onAgentCancel={async (sessionId) => {
                await api.agentCancel(sessionId);
              }}
              onTimelineRefresh={async () => {
                if (!projectPath) return;
                await refreshTimeline(projectPath);
              }}
            />
          )}
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-hidden p-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="text-muted">Snap</label>
            <select
              value={snap}
              onChange={(e) => setSnap(e.target.value)}
              className="rounded border border-border bg-surface px-2 py-1"
            >
              <option value="bar">Bar</option>
              <option value="beat">Beat</option>
              <option value="eighth">1/8</option>
              <option value="sixteenth">1/16</option>
              <option value="none">Off</option>
            </select>

            <span className="ml-2 text-muted">
              Edit range: {editBarRange[0].toFixed(1)}–{editBarRange[1].toFixed(1)} bars
            </span>

            <div className="ml-auto flex items-center gap-1">
              <Button variant="secondary" size="sm" onClick={zoomFitAll} title="Fit entire set">
                <Maximize2 className="h-3.5 w-3.5" /> Fit all
              </Button>
              <Button variant="secondary" size="sm" onClick={zoomToEditRange} title="Zoom detail to edit range">
                <ZoomIn className="h-3.5 w-3.5" /> Zoom edit
              </Button>
            </div>
          </div>

          <div className="h-48 shrink-0">
            <MasterTimeline
              timeline={timeline}
              playheadTick={playheadTick}
              viewRange={viewRange}
              editRange={editRange}
              snap={snap}
              onSeek={seekTo}
              onViewRangeChange={setViewRange}
              onEditRangeChange={setEditRange}
            />
          </div>

          <div className="min-h-0 flex-1">
            <PianoRoll
              timeline={timeline}
              totalTicks={totalTicks}
              playheadTick={playheadTick}
              playing={playing}
              followPlayhead={followPlayhead}
              snap={snap}
              pxPerTick={pxPerTick}
              scrollStartTick={scrollStartTick}
              editRange={editRange}
              selectedTrackIds={selectedTrackIds}
              trackScopeMode={trackScopeMode}
              onToggleTrack={toggleTrack}
              onTrackScopeModeChange={setTrackScopeMode}
              onViewportWidthChange={setViewportWidthPx}
              onScrollStartChange={setScrollStartTick}
              onZoomAt={zoomAt}
              onSeek={seekTo}
              onEdit={applyManualEdit}
              onMixerChange={handleMixerChange}
            />
          </div>

          {lastDiff && (
            <div className="shrink-0 rounded border border-border bg-panel px-2 py-1 font-mono text-xs text-muted">
              Diff: +{lastDiff.added_notes.length} / −{lastDiff.removed_notes.length} notes
            </div>
          )}
        </main>
      </div>

      <TransportBar
        className="shrink-0"
        playing={playing}
        playheadTick={playheadTick}
        ppq={ppq}
        followPlayhead={followPlayhead}
        error={transportError}
        onFollowPlayheadChange={setFollowPlayhead}
        onPlay={async () => {
          if (!projectPath) {
            setTransportError("Create or open a project before playing.");
            return;
          }
          const hasNotes = timeline?.segments.some((seg) =>
            seg.analysis?.tracks.some((track) => track.notes.length > 0),
          );
          if (!hasNotes) {
            setTransportError("Import MIDI files before playing.");
            return;
          }
          try {
            setTransportError(null);
            const t = await api.transport("play", playheadTick, projectPath);
            if (t.error) {
              setTransportError(t.error);
              setPlaying(false);
              return;
            }
            setPlaying(t.playing);
            setPlayheadTick(Math.max(0, t.position_tick));
          } catch (err) {
            setTransportError(err instanceof Error ? err.message : "Playback failed");
            setPlaying(false);
          }
        }}
        onPause={async () => {
          try {
            const t = await api.transport("pause");
            setPlaying(t.playing);
            setPlayheadTick(Math.max(0, t.position_tick));
          } catch (err) {
            setTransportError(err instanceof Error ? err.message : "Pause failed");
          }
        }}
        onStop={async () => {
          try {
            const t = await api.transport("stop");
            setPlaying(t.playing);
            setPlayheadTick(Math.max(0, t.position_tick));
          } catch (err) {
            setTransportError(err instanceof Error ? err.message : "Stop failed");
          }
        }}
        onSeekStart={() => seekTo(0)}
      />

      {showSettings && (
        <SettingsPanel
          onClose={async () => {
            setShowSettings(false);
            try {
              const s = await api.getSettings();
              setAiKeyConfigured(Boolean(s.ai_api_key_configured));
            } catch {
              /* engine may be offline */
            }
          }}
        />
      )}
    </div>
  );
}
