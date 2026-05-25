import { useCallback, useEffect, useState } from "react";
import {
  Download,
  FolderOpen,
  Music,
  Plus,
  Settings,
  Upload,
} from "lucide-react";
import {
  api,
  type RevisionDiff,
  type TimelineData,
  type TrackMappingEntry,
} from "@/lib/api";
import { barToTicks, MASTER_ROLES, mixerTrackId } from "@/lib/utils";
import { Button, Badge } from "@/components/ui/button";
import { TimelineView } from "@/features/timeline/TimelineView";
import { PianoRoll } from "@/features/timeline/PianoRoll";
import { TransportBar } from "@/features/transport/TransportBar";
import { AIPlannerPanel } from "@/features/ai-planner/AIPlannerPanel";
import { SettingsPanel } from "@/features/settings/SettingsPanel";

export default function App() {
  const [engineOk, setEngineOk] = useState(false);
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [playheadTick, setPlayheadTick] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [snap, setSnap] = useState("bar");
  const [selectedTransitionId, setSelectedTransitionId] = useState<string | null>(null);
  const [selectionRange, setSelectionRange] = useState<[number, number]>([0, 8]);
  const [showSettings, setShowSettings] = useState(false);
  const [status, setStatus] = useState("");
  const [lastDiff, setLastDiff] = useState<RevisionDiff | null>(null);
  const [trackMapping, setTrackMapping] = useState<TrackMappingEntry[]>([]);
  const [sidebarTab, setSidebarTab] = useState<"songs" | "mapping" | "ai">("ai");
  const [transportError, setTransportError] = useState<string | null>(null);

  const ppq = timeline?.master_ppq ?? 480;

  const refreshTimeline = useCallback(async (path: string) => {
    const tl = await api.getTimeline(path);
    setTimeline(tl);
    return tl;
  }, []);

  useEffect(() => {
    api.health().then(() => setEngineOk(true)).catch(() => setEngineOk(false));
    const id = window.setInterval(() => {
      api.health().then(() => setEngineOk(true)).catch(() => setEngineOk(false));
    }, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!playing || !projectPath) return;
    const id = window.setInterval(async () => {
      const t = await api.getTransport();
      setPlayheadTick(t.position_tick);
      if (!t.playing) setPlaying(false);
    }, 150);
    return () => clearInterval(id);
  }, [playing, projectPath]);

  const newProject = async () => {
    const name = prompt("Project name", "My Setlist");
    if (!name) return;
    const path = prompt("Project folder", `C:\\MidiWeaverProjects\\${name}.midiweaver`);
    if (!path) return;
    await api.createProject(path, name);
    setProjectPath(path);
    await refreshTimeline(path);
    setStatus(`Created ${name}`);
  };

  const openProject = async () => {
    const path = prompt("Open .midiweaver folder");
    if (!path) return;
    const data = await api.openProject(path);
    setProjectPath(path);
    setTimeline(data.timeline);
    setStatus(`Opened ${path}`);
  };

  const importMidi = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !projectPath) return;
    const data = await api.importMidi(projectPath, file);
    setTimeline(data.timeline);
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
    setTimeline(result.timeline);
    setLastDiff(result.revision.diff ?? null);
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

  const visibleStart = barToTicks(selectionRange[0], ppq);
  const visibleEnd = barToTicks(selectionRange[1], ppq);

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex items-center gap-2 border-b border-border bg-panel px-4 py-2">
        <Music className="h-5 w-5 text-accent" />
        <span className="font-semibold">MidiWeaver</span>
        <Badge className={engineOk ? "text-accent" : "text-error"}>
          {engineOk ? "Engine OK" : "Engine offline"}
        </Badge>
        <div className="flex-1" />
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
            const out = prompt("Export path", "C:\\MidiWeaverProjects\\export.mid");
            if (!out) return;
            const report = await api.exportMidi(projectPath, out);
            setStatus(`Exported ${report.track_count} tracks`);
          }}
        >
          <Download className="h-4 w-4" /> Export
        </Button>
        <Button variant="ghost" size="icon" onClick={() => setShowSettings(true)}>
          <Settings className="h-4 w-4" />
        </Button>
      </header>

      {status && (
        <div className="border-b border-border bg-surface px-4 py-1 text-xs text-muted">{status}</div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="w-56 shrink-0 border-r border-border bg-panel p-2">
          <div className="mb-2 flex gap-1 text-xs">
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

          {sidebarTab === "songs" && (
            <div className="space-y-2 overflow-auto text-xs">
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
            <div className="space-y-2 text-xs overflow-auto">
              {MASTER_ROLES.map((role) => {
                const entry = trackMapping.find((m) => m.role === role);
                return (
                  <div key={role} className="rounded border border-border p-2">
                    <div className="font-medium mb-1">{role}</div>
                    {timeline?.segments.map((seg) => (
                      <label key={seg.id} className="flex flex-col gap-0.5 mb-1">
                        <span className="text-muted">{seg.display_name}</span>
                        <select
                          className="rounded border border-border bg-surface px-1 py-0.5"
                          value={entry?.song_track_ids[seg.id] ?? ""}
                          onChange={(e) => {
                            const next = [...trackMapping];
                            let row = next.find((m) => m.role === role);
                            if (!row) {
                              row = {
                                master_track_id: role.toLowerCase(),
                                role,
                                song_track_ids: {},
                              };
                              next.push(row);
                            }
                            if (e.target.value) row.song_track_ids[seg.id] = e.target.value;
                            else delete row.song_track_ids[seg.id];
                            setTrackMapping(next);
                          }}
                        >
                          <option value="">—</option>
                          {seg.analysis?.tracks.map((t) => (
                            <option key={t.track_id} value={t.track_id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                );
              })}
              <Button
                size="sm"
                className="w-full"
                disabled={!projectPath}
                onClick={async () => {
                  if (!projectPath) return;
                  await api.updateTrackMapping(projectPath, trackMapping);
                  setStatus("Track mapping saved");
                }}
              >
                Save mapping
              </Button>
            </div>
          )}

          {sidebarTab === "ai" && projectPath && (
            <AIPlannerPanel
              diff={lastDiff}
              onGenerate={async (prompt, constraints) => {
                const trans = timeline?.transitions.find((t) => t.id === selectedTransitionId);
                const result = await api.aiPlan({
                  project_path: projectPath,
                  user_prompt: prompt,
                  selection: {
                    scope: "transition",
                    master_bar_range: selectionRange,
                    transition_id: trans?.id,
                  },
                  constraints,
                  mock: true,
                });
                return result.plan;
              }}
              onApply={async (plan, enabledIndices, tempoIndex) => {
                const planWithTempo = {
                  ...plan,
                  selected_tempo_option_index: tempoIndex,
                };
                const result = await api.applyPlan(projectPath, planWithTempo, enabledIndices);
                setTimeline(result.timeline);
                setLastDiff(result.revision.diff ?? null);
                setStatus("Applied AI plan");
              }}
            />
          )}
        </aside>

        <main className="flex min-w-0 flex-1 flex-col gap-2 p-2">
          <div className="flex items-center gap-2 text-xs">
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
            <label className="text-muted ml-2">Selection bars</label>
            <input
              type="number"
              className="w-14 rounded border border-border bg-surface px-1"
              value={selectionRange[0]}
              onChange={(e) => setSelectionRange([Number(e.target.value), selectionRange[1]])}
            />
            <span className="text-muted">–</span>
            <input
              type="number"
              className="w-14 rounded border border-border bg-surface px-1"
              value={selectionRange[1]}
              onChange={(e) => setSelectionRange([selectionRange[0], Number(e.target.value)])}
            />
          </div>

          <div className="h-28 shrink-0">
            <TimelineView
              timeline={timeline}
              playheadTick={playheadTick}
              selectedTransitionId={selectedTransitionId}
              onSelectTransition={setSelectedTransitionId}
              onSeek={setPlayheadTick}
              snap={snap}
            />
          </div>

          <div className="min-h-0 flex-1">
            <PianoRoll
              timeline={timeline}
              playheadTick={playheadTick}
              snap={snap}
              visibleStartTick={visibleStart}
              visibleEndTick={visibleEnd}
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
        playing={playing}
        playheadTick={playheadTick}
        ppq={ppq}
        error={transportError}
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
        onSeekStart={() => setPlayheadTick(0)}
      />

      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </div>
  );
}
