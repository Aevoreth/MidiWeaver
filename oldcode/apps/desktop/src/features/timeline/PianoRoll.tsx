import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { NoteEvent, TimelineData, TrackData } from "@/lib/api";
import { instrumentLabel, mixerTrackId, snapTick, trackNumberFromId } from "@/lib/utils";
import type { TickRange } from "./timelineUtils";

type EditMode = "select" | "draw" | "erase";
export type TrackScopeMode = "all" | "selected";

interface PianoRollProps {
  timeline: TimelineData | null;
  totalTicks: number;
  playheadTick: number;
  playing: boolean;
  followPlayhead: boolean;
  snap: string;
  pxPerTick: number;
  scrollStartTick: number;
  editRange: TickRange;
  selectedTrackIds: Set<string>;
  trackScopeMode: TrackScopeMode;
  onToggleTrack: (trackId: string) => void;
  onTrackScopeModeChange: (mode: TrackScopeMode) => void;
  onViewportWidthChange: (width: number) => void;
  onScrollStartChange: (tick: number) => void;
  onZoomAt: (cursorTick: number, factor: number) => void;
  onSeek: (tick: number) => void;
  onEdit: (action: string, payload: Record<string, unknown>) => void;
  onMixerChange: (trackId: string, patch: { mute?: boolean; solo?: boolean; volume?: number }) => void;
}

const LANE_HEIGHT = 60;
const NOTE_HIT_HEIGHT = 6;
const NOTE_LINE_WIDTH = 2;
const LABEL_WIDTH = 280;
const CONTEXT_RULER_HEIGHT = 20;

interface TrackLane {
  songId: string;
  track: TrackData;
  offset: number;
  pitchMin: number;
  pitchMax: number;
  mixerId: string;
}

function lanePitchY(pitch: number, lane: TrackLane): number {
  const range = Math.max(1, lane.pitchMax - lane.pitchMin);
  const norm = (lane.pitchMax - pitch) / range;
  return norm * (LANE_HEIGHT - NOTE_HIT_HEIGHT - 8) + 4;
}

function yToPitch(y: number, lane: TrackLane): number {
  const inner = Math.max(0, Math.min(LANE_HEIGHT - NOTE_HIT_HEIGHT - 8, y - 4));
  const range = Math.max(1, lane.pitchMax - lane.pitchMin);
  const norm = inner / (LANE_HEIGHT - NOTE_HIT_HEIGHT - 8);
  return Math.round(lane.pitchMax - norm * range);
}

function drawRangeFill(
  ctx: CanvasRenderingContext2D,
  startTick: number,
  endTick: number,
  drawStartTick: number,
  viewportWidth: number,
  lanesTop: number,
  height: number,
  pxPerTick: number,
  fill: string,
) {
  const startX = (startTick - drawStartTick) * pxPerTick;
  const endX = (endTick - drawStartTick) * pxPerTick;
  if (endX <= 0 || startX >= viewportWidth) return;

  const left = Math.max(0, startX);
  const right = Math.min(viewportWidth, endX);
  const width = right - left;
  if (width <= 0) return;

  ctx.fillStyle = fill;
  ctx.fillRect(left, lanesTop, width, height - lanesTop);
}

function drawRangeBoundary(
  ctx: CanvasRenderingContext2D,
  tick: number,
  drawStartTick: number,
  viewportWidth: number,
  height: number,
  pxPerTick: number,
  color: string,
  label: string,
  dashed: boolean,
  align: "start" | "end",
) {
  const x = (tick - drawStartTick) * pxPerTick;
  const inView = x >= -1 && x <= viewportWidth + 1;

  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  ctx.setLineDash(dashed ? [5, 4] : []);
  ctx.font = "10px Segoe UI, system-ui, sans-serif";

  if (inView) {
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, height);
    ctx.stroke();

    ctx.fillRect(x - (align === "start" ? 0 : 2), 0, 2, CONTEXT_RULER_HEIGHT);

    const textW = ctx.measureText(label).width;
    const textX = align === "start" ? Math.min(x + 4, viewportWidth - textW - 2) : Math.max(x - textW - 4, 2);
    ctx.fillStyle = color;
    ctx.fillText(label, textX, 13);
  } else {
    const onLeft = x < 0;
    const edgeX = onLeft ? 6 : viewportWidth - 6;
    ctx.beginPath();
    ctx.moveTo(edgeX, CONTEXT_RULER_HEIGHT / 2);
    ctx.lineTo(edgeX + (onLeft ? 6 : -6), CONTEXT_RULER_HEIGHT / 2 - 5);
    ctx.lineTo(edgeX + (onLeft ? 6 : -6), CONTEXT_RULER_HEIGHT / 2 + 5);
    ctx.closePath();
    ctx.fill();

    const shortLabel = align === "start" ? "◂ " : "";
    const shortLabelEnd = align === "end" ? " ▸" : "";
    const text = `${shortLabel}${label}${shortLabelEnd}`;
    const textW = ctx.measureText(text).width;
    const textX = onLeft ? 14 : viewportWidth - textW - 14;
    ctx.fillText(text, textX, 13);
  }

  ctx.setLineDash([]);
}

export function PianoRoll({
  timeline,
  totalTicks,
  playheadTick,
  playing,
  followPlayhead,
  snap,
  pxPerTick,
  scrollStartTick,
  editRange,
  selectedTrackIds,
  trackScopeMode,
  onToggleTrack,
  onTrackScopeModeChange,
  onViewportWidthChange,
  onScrollStartChange,
  onZoomAt,
  onSeek,
  onEdit,
  onMixerChange,
}: PianoRollProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const labelsScrollRef = useRef<HTMLDivElement>(null);
  const notesScrollRef = useRef<HTMLDivElement>(null);
  const syncingScrollRef = useRef(false);
  const [viewportWidth, setViewportWidth] = useState(800);
  const [mode, setMode] = useState<EditMode>("select");
  const [selected, setSelected] = useState<{ songId: string; trackId: string; index: number } | null>(null);
  const dragRef = useRef<{ kind: "move" | "resize"; startX: number; origStart: number; origDur: number } | null>(null);
  const drawRef = useRef<() => void>(() => {});

  const ppq = timeline?.master_ppq ?? 480;
  const scrollContentWidth = Math.max(viewportWidth, totalTicks * pxPerTick);

  const lanes = useMemo((): TrackLane[] => {
    const result: TrackLane[] = [];
    timeline?.segments.forEach((seg) => {
      if (!seg.analysis) return;
      const offset = seg.master_start_tick - seg.analysis.trim_start_tick;
      seg.analysis.tracks.forEach((track) => {
        const pitches = track.notes.map((n) => n.pitch);
        const pitchMin = pitches.length ? Math.min(...pitches) : 60;
        const pitchMax = pitches.length ? Math.max(...pitches) : 72;
        result.push({
          songId: seg.id,
          track,
          offset,
          pitchMin: Math.min(pitchMin, pitchMax - 1),
          pitchMax: Math.max(pitchMax, pitchMin + 1),
          mixerId: mixerTrackId(seg.id, track.track_id),
        });
      });
    });
    return result;
  }, [timeline]);

  useEffect(() => {
    const el = notesScrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? el.clientWidth;
      setViewportWidth(w);
      onViewportWidthChange(w);
    });
    ro.observe(el);
    const w = el.clientWidth;
    setViewportWidth(w);
    onViewportWidthChange(w);
    return () => ro.disconnect();
  }, [onViewportWidthChange]);

  useEffect(() => {
    const el = notesScrollRef.current;
    if (!el || syncingScrollRef.current) return;
    const targetScroll = scrollStartTick * pxPerTick;
    if (Math.abs(el.scrollLeft - targetScroll) > 2) {
      syncingScrollRef.current = true;
      el.scrollLeft = targetScroll;
      requestAnimationFrame(() => {
        drawRef.current();
        syncingScrollRef.current = false;
      });
    }
  }, [scrollStartTick, pxPerTick]);

  useEffect(() => {
    if (!playing || !followPlayhead) return;
    const el = notesScrollRef.current;
    if (!el) return;
    const playheadPx = playheadTick * pxPerTick;
    const margin = el.clientWidth * 0.12;
    let nextScroll = el.scrollLeft;
    if (playheadPx < el.scrollLeft + margin) {
      nextScroll = Math.max(0, playheadPx - margin);
    } else if (playheadPx > el.scrollLeft + el.clientWidth - margin) {
      nextScroll = playheadPx - el.clientWidth + margin;
    }
    const maxScroll = Math.max(0, scrollContentWidth - el.clientWidth);
    nextScroll = Math.min(maxScroll, nextScroll);
    if (Math.abs(nextScroll - el.scrollLeft) > 1) {
      syncingScrollRef.current = true;
      el.scrollLeft = nextScroll;
      onScrollStartChange(nextScroll / pxPerTick);
      requestAnimationFrame(() => {
        drawRef.current();
        syncingScrollRef.current = false;
      });
    }
  }, [playheadTick, playing, followPlayhead, pxPerTick, scrollContentWidth, onScrollStartChange]);

  const handleWheel = useCallback(
    (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const el = notesScrollRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const cursorTick = (el.scrollLeft + (e.clientX - rect.left)) / pxPerTick;
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      onZoomAt(cursorTick, factor);
    },
    [pxPerTick, onZoomAt],
  );

  useEffect(() => {
    const el = notesScrollRef.current;
    if (!el) return;
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  const syncVerticalScroll = useCallback((source: "labels" | "notes") => {
    if (syncingScrollRef.current) return;
    const labelsEl = labelsScrollRef.current;
    const notesEl = notesScrollRef.current;
    if (!labelsEl || !notesEl) return;

    syncingScrollRef.current = true;
    if (source === "labels") {
      notesEl.scrollTop = labelsEl.scrollTop;
    } else {
      labelsEl.scrollTop = notesEl.scrollTop;
    }
    syncingScrollRef.current = false;
  }, []);

  const handleHorizontalScroll = useCallback(() => {
    syncVerticalScroll("notes");
    if (syncingScrollRef.current) return;
    const el = notesScrollRef.current;
    if (!el) return;
    onScrollStartChange(el.scrollLeft / pxPerTick);
    requestAnimationFrame(() => drawRef.current());
  }, [pxPerTick, onScrollStartChange, syncVerticalScroll]);

  const isLaneInScope = useCallback(
    (mixerId: string) => trackScopeMode === "all" || selectedTrackIds.has(mixerId),
    [trackScopeMode, selectedTrackIds],
  );

  const getScrollStartTick = useCallback(() => {
    const el = notesScrollRef.current;
    return el ? el.scrollLeft / pxPerTick : scrollStartTick;
  }, [pxPerTick, scrollStartTick]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !timeline) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const drawStartTick = getScrollStartTick();
    const drawEndTick = drawStartTick + viewportWidth / pxPerTick;
    const lanesHeight = Math.max(LANE_HEIGHT, lanes.length * LANE_HEIGHT);
    const lanesTop = CONTEXT_RULER_HEIGHT;
    const height = lanesTop + lanesHeight;
    canvas.width = viewportWidth;
    canvas.height = height;

    ctx.fillStyle = "#1e1f23";
    ctx.fillRect(0, 0, viewportWidth, height);

    ctx.fillStyle = "#25262b";
    ctx.fillRect(0, 0, viewportWidth, lanesTop);
    ctx.strokeStyle = "#373a40";
    ctx.beginPath();
    ctx.moveTo(0, lanesTop - 0.5);
    ctx.lineTo(viewportWidth, lanesTop - 0.5);
    ctx.stroke();

    const gridStep = snap === "bar" ? ppq * 4 : snap === "beat" ? ppq : ppq / 4;
    const firstGrid = Math.floor(drawStartTick / gridStep) * gridStep;
    ctx.strokeStyle = "#333438";
    ctx.lineWidth = 1;
    for (let tick = firstGrid; tick <= drawEndTick; tick += gridStep) {
      const x = (tick - drawStartTick) * pxPerTick;
      if (x < -1 || x > viewportWidth + 1) continue;
      ctx.beginPath();
      ctx.moveTo(x, lanesTop);
      ctx.lineTo(x, height);
      ctx.stroke();
    }

    lanes.forEach((lane, laneIndex) => {
      const laneTop = lanesTop + laneIndex * LANE_HEIGHT;
      const inScope = isLaneInScope(lane.mixerId);
      const trackSelected = selectedTrackIds.has(lane.mixerId);
      ctx.fillStyle =
        !inScope && trackScopeMode === "selected"
          ? "#1a1b1e"
          : trackSelected
            ? "#2a3532"
            : laneIndex % 2 === 0
              ? "#23252a"
              : "#1e1f23";
      ctx.fillRect(0, laneTop, viewportWidth, LANE_HEIGHT);

      ctx.strokeStyle = "#3a3c42";
      ctx.beginPath();
      ctx.moveTo(0, laneTop + LANE_HEIGHT - 0.5);
      ctx.lineTo(viewportWidth, laneTop + LANE_HEIGHT - 0.5);
      ctx.stroke();
    });

    drawRangeFill(
      ctx,
      editRange.startTick,
      editRange.endTick,
      drawStartTick,
      viewportWidth,
      lanesTop,
      height,
      pxPerTick,
      "rgba(77, 171, 154, 0.12)",
    );

    lanes.forEach((lane, laneIndex) => {
      const laneTop = lanesTop + laneIndex * LANE_HEIGHT;
      if (!isLaneInScope(lane.mixerId)) return;

      lane.track.notes.forEach((note, index) => {
        const absStart = note.start_tick + lane.offset;
        if (absStart + note.duration_ticks < drawStartTick || absStart > drawEndTick) return;
        const x = (absStart - drawStartTick) * pxPerTick;
        const w = Math.max(2, note.duration_ticks * pxPerTick);
        const y = laneTop + lanePitchY(note.pitch, lane);
        const centerY = y + NOTE_HIT_HEIGHT / 2;
        const isNoteSelected =
          selected?.songId === lane.songId &&
          selected.trackId === lane.track.track_id &&
          selected.index === index;

        ctx.strokeStyle = lane.track.is_drum
          ? "rgba(232, 168, 56, 0.9)"
          : isNoteSelected
            ? "rgba(77, 171, 154, 1)"
            : "rgba(77, 171, 154, 0.75)";
        ctx.lineWidth = isNoteSelected ? NOTE_LINE_WIDTH + 1 : NOTE_LINE_WIDTH;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(x, centerY);
        ctx.lineTo(x + w, centerY);
        ctx.stroke();
      });
    });

    drawRangeBoundary(
      ctx,
      editRange.startTick,
      drawStartTick,
      viewportWidth,
      height,
      pxPerTick,
      "#4dab9a",
      "Edit start",
      false,
      "start",
    );
    drawRangeBoundary(
      ctx,
      editRange.endTick,
      drawStartTick,
      viewportWidth,
      height,
      pxPerTick,
      "#4dab9a",
      "Edit end",
      false,
      "end",
    );

    // Re-draw boundary lines on top of fills for crisp edges.
    for (const tick of [editRange.startTick, editRange.endTick]) {
      const x = (tick - drawStartTick) * pxPerTick;
      if (x < -1 || x > viewportWidth + 1) continue;
      ctx.strokeStyle = "#4dab9a";
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(x + 0.5, lanesTop);
      ctx.lineTo(x + 0.5, height);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    const ph = (playheadTick - drawStartTick) * pxPerTick;
    if (ph >= -2 && ph <= viewportWidth + 2) {
      ctx.strokeStyle = "#e8a838";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(ph, 0);
      ctx.lineTo(ph, height);
      ctx.stroke();
      ctx.lineWidth = 1;
    }
  }, [
    timeline,
    lanes,
    scrollStartTick,
    getScrollStartTick,
    editRange,
    playheadTick,
    snap,
    ppq,
    selected,
    pxPerTick,
    viewportWidth,
    isLaneInScope,
    selectedTrackIds,
    trackScopeMode,
  ]);

  useEffect(() => {
    drawRef.current = draw;
    draw();
  }, [draw]);

  const laneAtY = (y: number) => {
    if (y < CONTEXT_RULER_HEIGHT) return null;
    const index = Math.floor((y - CONTEXT_RULER_HEIGHT) / LANE_HEIGHT);
    if (index < 0 || index >= lanes.length) return null;
    return { lane: lanes[index], laneIndex: index, localY: y - CONTEXT_RULER_HEIGHT - index * LANE_HEIGHT };
  };

  const hitTest = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const tick = getScrollStartTick() + x / pxPerTick;

    if (y < CONTEXT_RULER_HEIGHT) {
      return { tick, lane: null as TrackLane | null };
    }

    const hitLane = laneAtY(y);
    if (!hitLane) return null;

    const { lane, localY } = hitLane;
    if (!isLaneInScope(lane.mixerId)) return { tick, lane: null as TrackLane | null };

    for (let index = lane.track.notes.length - 1; index >= 0; index--) {
      const note = lane.track.notes[index];
      const absStart = note.start_tick + lane.offset;
      const nx = (absStart - getScrollStartTick()) * pxPerTick;
      const nw = note.duration_ticks * pxPerTick;
      const ny = lanePitchY(note.pitch, lane);
      if (x >= nx && x <= nx + nw && localY >= ny && localY <= ny + NOTE_HIT_HEIGHT) {
        return {
          songId: lane.songId,
          trackId: lane.track.track_id,
          index,
          note,
          absStart,
          lane,
          resize: x > nx + nw - 6,
        };
      }
    }

    return { tick, pitch: yToPitch(localY, lane), lane };
  };

  const segmentOffset = (songId: string) => {
    const seg = timeline?.segments.find((s) => s.id === songId);
    return (seg?.master_start_tick ?? 0) - (seg?.analysis?.trim_start_tick ?? 0);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    const hit = hitTest(e.clientX, e.clientY);
    if (!hit) return;

    if (mode === "select" && "tick" in hit && typeof hit.tick === "number" && !("index" in hit && hit.index !== undefined)) {
      onSeek(snapTick(Math.round(hit.tick), ppq, snap));
    }

    if (mode === "draw" && "tick" in hit && typeof hit.tick === "number" && hit.lane) {
      const start = snapTick(Math.round(hit.tick), ppq, snap);
      onEdit("add", {
        song_id: hit.lane.songId,
        track_id: hit.lane.track.track_id,
        start_tick: start - hit.lane.offset,
        pitch: hit.pitch,
        duration_ticks: ppq,
        velocity: 80,
      });
      return;
    }

    if (mode === "erase" && "index" in hit && hit.index !== undefined) {
      onEdit("delete", { song_id: hit.songId, track_id: hit.trackId, note_index: hit.index });
      return;
    }

    if ("index" in hit && hit.index !== undefined) {
      setSelected({ songId: hit.songId!, trackId: hit.trackId!, index: hit.index! });
      dragRef.current = {
        kind: hit.resize ? "resize" : "move",
        startX: e.clientX,
        origStart: hit.absStart!,
        origDur: hit.note!.duration_ticks,
      };
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current || !selected) return;
    const deltaTicks = Math.round((e.clientX - dragRef.current.startX) / pxPerTick);
    const snapped = snapTick(dragRef.current.origStart + deltaTicks, ppq, snap);
    if (dragRef.current.kind === "move") {
      onEdit("move", {
        song_id: selected.songId,
        track_id: selected.trackId,
        note_index: selected.index,
        start_tick: snapped - segmentOffset(selected.songId),
      });
    } else {
      const newDur = Math.max(ppq / 4, dragRef.current.origDur + deltaTicks);
      onEdit("resize", {
        song_id: selected.songId,
        track_id: selected.trackId,
        note_index: selected.index,
        duration_ticks: newDur,
      });
    }
  };

  const onPointerUp = () => {
    dragRef.current = null;
  };

  const selectedNote: NoteEvent | null =
    selected && timeline
      ? timeline.segments
          .find((s) => s.id === selected.songId)
          ?.analysis?.tracks.find((t) => t.track_id === selected.trackId)?.notes[selected.index] ?? null
      : null;

  const canvasHeight = CONTEXT_RULER_HEIGHT + Math.max(LANE_HEIGHT, lanes.length * LANE_HEIGHT);

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {(["select", "draw", "erase"] as EditMode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={`rounded px-2 py-1 capitalize ${mode === m ? "bg-accent text-background" : "bg-panel border border-border"}`}
            onClick={() => setMode(m)}
          >
            {m}
          </button>
        ))}
        <span className="text-muted">Ctrl+wheel to zoom · scroll to navigate</span>
        <div className="flex items-center gap-3 border-l border-border pl-2 text-muted">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm border border-edit-range/70 bg-edit-range/25" />
            Edit range
          </span>
        </div>
        <div className="flex items-center gap-1 border-l border-border pl-2">
          <span className="text-muted">Tracks:</span>
          {(["all", "selected"] as TrackScopeMode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={`rounded px-2 py-1 capitalize ${trackScopeMode === m ? "bg-accent/20 text-accent" : "bg-panel border border-border"}`}
              onClick={() => onTrackScopeModeChange(m)}
            >
              {m}
            </button>
          ))}
        </div>
        {selectedNote && (
          <label className="ml-auto flex items-center gap-2 text-muted">
            Velocity
            <input
              type="range"
              min={1}
              max={127}
              value={selectedNote.velocity}
              onChange={(e) =>
                onEdit("velocity", {
                  song_id: selected!.songId,
                  track_id: selected!.trackId,
                  note_index: selected!.index,
                  velocity: Number(e.target.value),
                })
              }
            />
            {selectedNote.velocity}
          </label>
        )}
      </div>
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-[#1e1f23]">
        <div
          ref={labelsScrollRef}
          className="shrink-0 overflow-y-auto overflow-x-hidden border-r border-border bg-panel text-xs"
          style={{ width: LABEL_WIDTH }}
          onScroll={() => syncVerticalScroll("labels")}
        >
          <div
            className="flex items-center border-b border-border px-2 text-[10px] text-muted"
            style={{ height: CONTEXT_RULER_HEIGHT }}
          >
            Context
          </div>
          {lanes.length === 0 ? (
            <div className="p-3 text-muted">No tracks</div>
          ) : (
            lanes.map((lane) => {
              const trackNum = trackNumberFromId(lane.track.track_id);
              const mute = lane.track.mute ?? false;
              const solo = lane.track.solo ?? false;
              const volume = lane.track.volume ?? 1;
              const trackSelected = selectedTrackIds.has(lane.mixerId);

              return (
                <div
                  key={`${lane.songId}-${lane.track.track_id}`}
                  className={`flex flex-col justify-center gap-1 border-b border-border px-2 py-1 ${trackSelected ? "bg-accent/10" : ""}`}
                  style={{ height: LANE_HEIGHT }}
                  title={`Track ${trackNum}: ${lane.track.name}`}
                >
                  <div className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={trackSelected}
                      onChange={() => onToggleTrack(lane.mixerId)}
                      aria-label={`Select track ${trackNum} for edits`}
                      className="shrink-0"
                    />
                    <span className="w-5 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted">
                      {trackNum || "—"}
                    </span>
                    <button
                      type="button"
                      className={`rounded px-1 py-0.5 text-[10px] leading-none ${mute ? "bg-error/30 text-error" : "bg-surface"}`}
                      onClick={() => onMixerChange(lane.mixerId, { mute: !mute })}
                      aria-label={`Mute track ${trackNum}`}
                    >
                      M
                    </button>
                    <button
                      type="button"
                      className={`rounded px-1 py-0.5 text-[10px] leading-none ${solo ? "bg-accent/30 text-accent" : "bg-surface"}`}
                      onClick={() => onMixerChange(lane.mixerId, { solo: !solo })}
                      aria-label={`Solo track ${trackNum}`}
                    >
                      S
                    </button>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={Math.round(volume * 100)}
                      className="min-w-0 flex-1"
                      onChange={(e) =>
                        onMixerChange(lane.mixerId, { volume: Number(e.target.value) / 100 })
                      }
                      aria-label={`Volume track ${trackNum}`}
                    />
                  </div>
                  <div className="truncate pl-6 font-medium text-foreground">{lane.track.name}</div>
                  <div className="truncate pl-6 text-[10px] text-muted">
                    {instrumentLabel(lane.track)}
                    {" · "}
                    {lane.track.notes.length} notes
                  </div>
                </div>
              );
            })
          )}
        </div>
        <div
          ref={notesScrollRef}
          className="min-w-0 flex-1 overflow-auto"
          onScroll={handleHorizontalScroll}
        >
          <div style={{ width: scrollContentWidth, height: canvasHeight, position: "relative" }}>
            <canvas
              ref={canvasRef}
              style={{
                position: "sticky",
                left: 0,
                top: 0,
                width: viewportWidth,
                height: canvasHeight,
                display: "block",
              }}
              className="cursor-crosshair"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={onPointerUp}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
