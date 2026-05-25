import { useCallback, useEffect, useRef, useState } from "react";
import type { TimelineData } from "@/lib/api";
import { snapTick, ticksToBar } from "@/lib/utils";
import {
  getTransitionTickRange,
  HANDLE_WIDTH_PX,
  MAX_OVERVIEW_ZOOM,
  mixInBarsFromTick,
  mixOutBarsFromTick,
  projectTotalTicks,
  type TickRange,
} from "./timelineUtils";

type DragTarget =
  | "playhead"
  | "view-start"
  | "view-end"
  | "view-pan"
  | "edit-start"
  | "edit-end"
  | "edit-pan"
  | "trans-start"
  | "trans-end"
  | "trans-pan"
  | null;

type TimelineRow = "songs" | "view" | "trans" | "edit";

interface MasterTimelineProps {
  timeline: TimelineData | null;
  playheadTick: number;
  viewRange: TickRange;
  editRange: TickRange;
  selectedTransitionId: string | null;
  transitionRange: TickRange | null;
  snap: string;
  onSeek: (tick: number) => void;
  onSelectTransition: (id: string | null) => void;
  onViewRangeChange: (range: TickRange) => void;
  onEditRangeChange: (range: TickRange) => void;
  onTransitionMarkersCommit: (mixOutBars: number, mixInBars: number) => void;
}

const LABEL_WIDTH = 80;
const ROW_GAP = 4;
const ROW_SEGMENTS = 32;
const ROW_VIEW = 16;
const ROW_TRANS = 16;
const ROW_EDIT = 16;
const CONTENT_HEIGHT = ROW_SEGMENTS + ROW_VIEW + ROW_TRANS + ROW_EDIT + ROW_GAP * 3;
const TOTAL_HEIGHT = CONTENT_HEIGHT + 8;
const SCROLLBAR_GUTTER = 12;
const PANEL_HEIGHT = TOTAL_HEIGHT + SCROLLBAR_GUTTER;

const ROW_LAYOUT: { id: TimelineRow; top: number; height: number; label: string; hint: string }[] = [
  { id: "songs", top: 4, height: ROW_SEGMENTS, label: "Songs", hint: "Click to move playhead" },
  {
    id: "view",
    top: 4 + ROW_SEGMENTS + ROW_GAP,
    height: ROW_VIEW,
    label: "View",
    hint: "Detail window in piano roll",
  },
  {
    id: "trans",
    top: 4 + ROW_SEGMENTS + ROW_GAP + ROW_VIEW + ROW_GAP,
    height: ROW_TRANS,
    label: "Transition",
    hint: "AI reference scope",
  },
  {
    id: "edit",
    top: 4 + ROW_SEGMENTS + ROW_GAP + ROW_VIEW + ROW_GAP + ROW_TRANS + ROW_GAP,
    height: ROW_EDIT,
    label: "Edit",
    hint: "AI can modify here",
  },
];

function rangeWidthPx(tickToContentX: (tick: number) => number, range: TickRange): number {
  return Math.max(HANDLE_WIDTH_PX * 2 + 4, tickToContentX(range.endTick - range.startTick));
}

interface RangeBarProps {
  range: TickRange;
  top: number;
  height: number;
  width: number;
  tickToContentX: (tick: number) => number;
  active: boolean;
  variant: "view" | "trans" | "edit";
  title: string;
  dashed?: boolean;
  dimmed?: boolean;
  onResizeStart: (edge: "start" | "end", e: React.PointerEvent) => void;
  onPanStart: (e: React.PointerEvent) => void;
  onSelect?: (e: React.PointerEvent) => void;
  onPointerMove?: (e: React.PointerEvent) => void;
  onPointerUp?: (e: React.PointerEvent) => void;
  onPointerCancel?: (e: React.PointerEvent) => void;
}

function RangeBar({
  range,
  top,
  height,
  width,
  tickToContentX,
  active,
  variant,
  title,
  dashed,
  dimmed,
  onResizeStart,
  onPanStart,
  onSelect,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
}: RangeBarProps) {
  const styles = {
    view: {
      bar: "border-2 border-accent/80 bg-accent/10",
      handle: "bg-accent hover:bg-accent/90",
      glow: "var(--color-accent)",
    },
    trans: {
      bar: dashed
        ? "border-2 border-dashed border-playhead/80 bg-playhead/12"
        : "border-2 border-playhead/60 bg-playhead/8",
      handle: "bg-playhead hover:bg-playhead/90",
      glow: "var(--color-playhead)",
    },
    edit: {
      bar: "border-2 border-edit-range/70 bg-edit-range/30",
      handle: "bg-edit-range hover:bg-edit-range/90",
      glow: "var(--color-edit-range)",
    },
  }[variant];

  const left = tickToContentX(range.startTick);
  const barWidth = rangeWidthPx(tickToContentX, range);
  const handleH = Math.min(height + 6, 22);

  const begin = (e: React.PointerEvent, fn: (e: React.PointerEvent) => void) => {
    e.preventDefault();
    e.stopPropagation();
    fn(e);
  };

  const dragProps = { onPointerMove, onPointerUp, onPointerCancel };

  return (
    <div className="absolute left-0" style={{ top, height, width, pointerEvents: "none" }}>
      <div
        className={`absolute touch-none ${dimmed ? "opacity-45" : "opacity-100"}`}
        style={{ left, width: barWidth, height, pointerEvents: "auto" }}
        title={title}
      >
        <div
          className={`absolute rounded-md ${styles.bar}`}
          style={{
            inset: 0,
            boxShadow: active ? `0 0 0 2px ${styles.glow}` : undefined,
          }}
        >
          <div
            className={`absolute top-1/2 z-20 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full ring-1 ring-black/30 ${styles.handle}`}
            style={{ left: 0, width: HANDLE_WIDTH_PX, height: handleH }}
            onPointerDown={(e) => begin(e, (ev) => onResizeStart("start", ev))}
            {...dragProps}
          />
          <div
            className={`absolute top-1/2 z-20 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full ring-1 ring-black/30 ${styles.handle}`}
            style={{ left: "100%", width: HANDLE_WIDTH_PX, height: handleH }}
            onPointerDown={(e) => begin(e, (ev) => onResizeStart("end", ev))}
            {...dragProps}
          />
          <div
            className="absolute z-10 cursor-grab active:cursor-grabbing"
            style={{
              top: 0,
              bottom: 0,
              left: HANDLE_WIDTH_PX / 2,
              right: HANDLE_WIDTH_PX / 2,
            }}
            onPointerDown={(e) => begin(e, onPanStart)}
            {...dragProps}
          />
        </div>
        {onSelect && dimmed && (
          <button
            type="button"
            className="absolute inset-0 z-0 cursor-pointer"
            aria-label={title}
            onPointerDown={(e) => begin(e, onSelect)}
            {...dragProps}
          />
        )}
      </div>
    </div>
  );
}

export function MasterTimeline({
  timeline,
  playheadTick,
  viewRange,
  editRange,
  selectedTransitionId,
  transitionRange,
  snap,
  onSeek,
  onSelectTransition,
  onViewRangeChange,
  onEditRangeChange,
  onTransitionMarkersCommit,
}: MasterTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const overviewZoomRef = useRef(1);
  const metricsRef = useRef({ minPxPerTick: 0, totalTicks: 0 });
  const lastTotalTicksRef = useRef(0);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [overviewZoom, setOverviewZoom] = useState(1);
  const [playheadPreview, setPlayheadPreview] = useState<number | null>(null);
  const dragRef = useRef<{
    target: DragTarget;
    startX: number;
    origView: TickRange;
    origEdit: TickRange;
    origTrans: TickRange | null;
    origPlayhead: number;
    transitionId?: string;
    pendingMixOut?: number;
    pendingMixIn?: number;
  } | null>(null);
  const [activeLayer, setActiveLayer] = useState<"view" | "edit" | "trans" | null>(null);
  const [activeDragTarget, setActiveDragTarget] = useState<DragTarget>(null);
  const [transPreview, setTransPreview] = useState<TickRange | null>(null);

  const ppq = timeline?.master_ppq ?? 480;
  const totalTicks = projectTotalTicks(timeline, ppq);
  const displayTransitionRange = transPreview ?? transitionRange;
  const displayPlayheadTick = playheadPreview ?? playheadTick;

  const minPxPerTick = viewportWidth > 0 && totalTicks > 0 ? viewportWidth / totalTicks : 0;
  const overviewPxPerTick = minPxPerTick > 0 ? minPxPerTick * overviewZoom : 0;
  const contentWidth = totalTicks * overviewPxPerTick;

  overviewZoomRef.current = overviewZoom;
  metricsRef.current = { minPxPerTick, totalTicks };

  useEffect(() => {
    if (!dragRef.current) setPlayheadPreview(null);
  }, [playheadTick]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setViewportWidth(el.clientWidth);
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, [timeline]);

  useEffect(() => {
    if (lastTotalTicksRef.current === totalTicks) return;
    lastTotalTicksRef.current = totalTicks;
    setOverviewZoom(1);
    if (scrollRef.current) scrollRef.current.scrollLeft = 0;
  }, [totalTicks]);

  const snapTickLocal = useCallback(
    (tick: number) => snapTick(Math.round(tick), ppq, snap),
    [ppq, snap],
  );

  const clampTickLocal = useCallback(
    (tick: number) => Math.max(0, Math.min(totalTicks, tick)),
    [totalTicks],
  );

  const clientXToContentX = useCallback((clientX: number) => {
    const el = scrollRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    return clientX - rect.left + el.scrollLeft;
  }, []);

  const clientXToTick = useCallback(
    (clientX: number) => {
      if (overviewPxPerTick <= 0) return 0;
      return clampTickLocal(clientXToContentX(clientX) / overviewPxPerTick);
    },
    [overviewPxPerTick, clampTickLocal, clientXToContentX],
  );

  const tickToContentX = useCallback(
    (tick: number) => tick * overviewPxPerTick,
    [overviewPxPerTick],
  );

  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;

    const onWheel = (e: WheelEvent) => {
      const el = scrollRef.current;
      if (!el) return;
      const { minPxPerTick: minPx, totalTicks: ticks } = metricsRef.current;
      if (minPx <= 0 || ticks <= 0) return;

      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        e.stopPropagation();
        const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
        const rect = el.getBoundingClientRect();
        const cursorContentX = el.scrollLeft + (e.clientX - rect.left);
        const currentPx = minPx * overviewZoomRef.current;
        const cursorTick = cursorContentX / currentPx;
        const nextZoom = Math.min(MAX_OVERVIEW_ZOOM, Math.max(1, overviewZoomRef.current * factor));
        const nextPx = minPx * nextZoom;
        const maxScroll = Math.max(0, ticks * nextPx - el.clientWidth);
        const nextScroll = Math.max(
          0,
          Math.min(maxScroll, cursorTick * nextPx - (e.clientX - rect.left)),
        );
        setOverviewZoom(nextZoom);
        el.scrollLeft = nextScroll;
        return;
      }

      e.preventDefault();
      e.stopPropagation();
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (delta === 0) return;
      el.scrollLeft = Math.max(0, Math.min(el.scrollWidth - el.clientWidth, el.scrollLeft + delta));
    };

    root.addEventListener("wheel", onWheel, { passive: false, capture: true });
    return () => root.removeEventListener("wheel", onWheel, { capture: true });
  }, [timeline]);

  const commitTransitionRange = useCallback(
    (nextRange: TickRange, transitionId?: string) => {
      const transId = transitionId ?? dragRef.current?.transitionId ?? selectedTransitionId;
      if (!timeline || !transId) return;
      const trans = timeline.transitions.find((t) => t.id === transId);
      if (!trans) return;
      const mixOut = mixOutBarsFromTick(timeline, trans, nextRange.startTick);
      const mixIn = mixInBarsFromTick(timeline, trans, nextRange.endTick);
      if (dragRef.current) {
        dragRef.current.pendingMixOut = mixOut;
        dragRef.current.pendingMixIn = mixIn;
      }
      setTransPreview(nextRange);
    },
    [timeline, selectedTransitionId],
  );

  const beginDrag = useCallback(
    (target: Exclude<DragTarget, null>, e: React.PointerEvent) => {
      if (!timeline || overviewPxPerTick <= 0) return;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      dragRef.current = {
        target,
        startX: e.clientX,
        origView: { ...viewRange },
        origEdit: { ...editRange },
        origTrans: displayTransitionRange ? { ...displayTransitionRange } : null,
        origPlayhead: displayPlayheadTick,
      };
      setActiveDragTarget(target);
      if (target.startsWith("view")) setActiveLayer("view");
      else if (target.startsWith("edit")) setActiveLayer("edit");
      else if (target.startsWith("trans")) setActiveLayer("trans");
    },
    [timeline, overviewPxPerTick, viewRange, editRange, displayTransitionRange, displayPlayheadTick],
  );

  const beginTransitionDrag = useCallback(
    (target: "trans-start" | "trans-end" | "trans-pan", transId: string, e: React.PointerEvent) => {
      if (!timeline) return;
      const trans = timeline.transitions.find((t) => t.id === transId);
      if (!trans) return;
      const range = getTransitionTickRange(timeline, trans);
      if (!range) return;
      if (selectedTransitionId !== transId) {
        onSelectTransition(transId);
      }
      if (!overviewPxPerTick) return;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      dragRef.current = {
        target,
        startX: e.clientX,
        origView: { ...viewRange },
        origEdit: { ...editRange },
        origTrans: { ...range },
        origPlayhead: displayPlayheadTick,
        transitionId: transId,
      };
      setActiveDragTarget(target);
      setActiveLayer("trans");
    },
    [
      timeline,
      selectedTransitionId,
      onSelectTransition,
      overviewPxPerTick,
      viewRange,
      editRange,
      displayPlayheadTick,
    ],
  );

  const onDragMove = useCallback(
    (e: React.PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || !timeline || overviewPxPerTick <= 0) return;
      e.preventDefault();
      const deltaTick = (e.clientX - drag.startX) / overviewPxPerTick;

      switch (drag.target) {
        case "playhead":
          setPlayheadPreview(snapTickLocal(drag.origPlayhead + deltaTick));
          break;
        case "view-start":
          onViewRangeChange({
            startTick: snapTickLocal(drag.origView.startTick + deltaTick),
            endTick: drag.origView.endTick,
          });
          break;
        case "view-end":
          onViewRangeChange({
            startTick: drag.origView.startTick,
            endTick: snapTickLocal(drag.origView.endTick + deltaTick),
          });
          break;
        case "view-pan": {
          const span = drag.origView.endTick - drag.origView.startTick;
          onViewRangeChange({
            startTick: snapTickLocal(drag.origView.startTick + deltaTick),
            endTick: snapTickLocal(drag.origView.startTick + deltaTick) + span,
          });
          break;
        }
        case "edit-start":
          onEditRangeChange({
            startTick: snapTickLocal(drag.origEdit.startTick + deltaTick),
            endTick: drag.origEdit.endTick,
          });
          break;
        case "edit-end":
          onEditRangeChange({
            startTick: drag.origEdit.startTick,
            endTick: snapTickLocal(drag.origEdit.endTick + deltaTick),
          });
          break;
        case "edit-pan": {
          const span = drag.origEdit.endTick - drag.origEdit.startTick;
          onEditRangeChange({
            startTick: snapTickLocal(drag.origEdit.startTick + deltaTick),
            endTick: snapTickLocal(drag.origEdit.startTick + deltaTick) + span,
          });
          break;
        }
        case "trans-start":
        case "trans-end": {
          if (!drag.origTrans) break;
          const nextRange =
            drag.target === "trans-start"
              ? {
                  startTick: snapTickLocal(drag.origTrans.startTick + deltaTick),
                  endTick: drag.origTrans.endTick,
                }
              : {
                  startTick: drag.origTrans.startTick,
                  endTick: snapTickLocal(drag.origTrans.endTick + deltaTick),
                };
          commitTransitionRange(nextRange, drag.transitionId);
          break;
        }
        case "trans-pan": {
          if (!drag.origTrans) break;
          commitTransitionRange(
            {
              startTick: snapTickLocal(drag.origTrans.startTick + deltaTick),
              endTick: snapTickLocal(drag.origTrans.endTick + deltaTick),
            },
            drag.transitionId,
          );
          break;
        }
        default:
          break;
      }
    },
    [
      timeline,
      overviewPxPerTick,
      snapTickLocal,
      onViewRangeChange,
      onEditRangeChange,
      selectedTransitionId,
      commitTransitionRange,
    ],
  );

  const endDrag = useCallback(
    (e: React.PointerEvent) => {
      const drag = dragRef.current;
      if (drag?.target === "playhead" && overviewPxPerTick > 0) {
        const deltaTick = (e.clientX - drag.startX) / overviewPxPerTick;
        onSeek(snapTickLocal(drag.origPlayhead + deltaTick));
      }
      if (
        drag &&
        (drag.target === "trans-start" ||
          drag.target === "trans-end" ||
          drag.target === "trans-pan") &&
        drag.pendingMixOut != null &&
        drag.pendingMixIn != null
      ) {
        onTransitionMarkersCommit(drag.pendingMixOut, drag.pendingMixIn);
      }
      setPlayheadPreview(null);
      setTransPreview(null);
      dragRef.current = null;
      setActiveLayer(null);
      setActiveDragTarget(null);
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
    },
    [overviewPxPerTick, onSeek, snapTickLocal, onTransitionMarkersCommit],
  );

  const onSongsPointerDown = (e: React.PointerEvent) => {
    if (!timeline || overviewPxPerTick <= 0 || dragRef.current) return;
    const x = clientXToContentX(e.clientX);
    const playheadX = tickToContentX(displayPlayheadTick);
    if (Math.abs(x - playheadX) <= HANDLE_WIDTH_PX / 2 + 4) {
      e.preventDefault();
      beginDrag("playhead", e);
      return;
    }

    const tick = snapTickLocal(clientXToTick(e.clientX));
    const clickedTransition = timeline.transitions.find((trans) => {
      const range = getTransitionTickRange(timeline, trans);
      return range && tick >= range.startTick && tick <= range.endTick;
    });
    if (clickedTransition) {
      onSelectTransition(clickedTransition.id);
      return;
    }

    setPlayheadPreview(null);
    onSeek(tick);
  };

  if (!timeline) {
    return (
      <div className="flex h-full items-center justify-center rounded-md border border-border bg-surface text-sm text-muted">
        Import MIDI files to begin building your set.
      </div>
    );
  }

  const barStep = ppq * 4;
  const pxPerBar = barStep * overviewPxPerTick;
  const barStride = pxPerBar < 6 ? Math.max(1, Math.ceil(6 / pxPerBar)) : 1;
  const barCount = Math.ceil(totalTicks / barStep) + 1;
  const playheadX = tickToContentX(displayPlayheadTick);
  const ready = viewportWidth > 0 && overviewPxPerTick > 0;
  const dragCursor =
    activeDragTarget === "view-pan" || activeDragTarget === "edit-pan" || activeDragTarget === "trans-pan"
      ? "cursor-grabbing"
      : activeDragTarget
        ? "cursor-ew-resize"
        : "";

  return (
    <div ref={containerRef} className="flex h-full min-h-0 flex-col gap-1">
      <div className="flex shrink-0 items-center justify-between text-[10px] text-muted">
        <span className="flex flex-wrap items-center gap-3">
          <span>Drag handles or bar bodies to adjust ranges</span>
          <span>Wheel pan · Ctrl+wheel zoom</span>
          {overviewZoom > 1 && (
            <button
              type="button"
              className="rounded border border-border px-1.5 py-0.5 hover:bg-panel"
              onClick={() => {
                setOverviewZoom(1);
                if (scrollRef.current) scrollRef.current.scrollLeft = 0;
              }}
            >
              Fit project
            </button>
          )}
        </span>
        <span>
          Bar {ticksToBar(displayPlayheadTick, ppq).toFixed(2)} / {ticksToBar(totalTicks, ppq).toFixed(1)}
          {overviewZoom > 1 ? ` · ${overviewZoom.toFixed(1)}×` : ""}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-surface">
        <div
          className="flex shrink-0 flex-col border-r border-border/60 bg-panel/40 py-1 pl-2 pr-1.5 text-[10px] text-muted"
          style={{ width: LABEL_WIDTH, height: PANEL_HEIGHT }}
        >
          {ROW_LAYOUT.map((row) => (
            <div
              key={row.id}
              className="flex flex-col justify-center leading-tight"
              style={{
                height: row.height,
                marginBottom: row.id === "edit" ? 0 : ROW_GAP,
                marginTop: row.id === "songs" ? 4 : 0,
              }}
              title={row.hint}
            >
              <span className="font-medium text-foreground/80">{row.label}</span>
              <span className="truncate text-[9px] opacity-70">{row.hint}</span>
            </div>
          ))}
        </div>

        <div
          ref={scrollRef}
          className="min-h-0 min-w-0 flex-1 overflow-x-auto overflow-y-hidden"
          style={{ height: PANEL_HEIGHT }}
        >
          <div
            ref={contentRef}
            className={`relative select-none ${dragCursor}`}
            style={{
              width: ready ? contentWidth : viewportWidth || "100%",
              height: TOTAL_HEIGHT,
            }}
          >
            {ready &&
              Array.from({ length: barCount }).map((_, bar) => {
                if (bar % barStride !== 0 && bar !== barCount - 1) return null;
                return (
                  <div
                    key={bar}
                    className="pointer-events-none absolute top-0 border-l border-roll-grid/50"
                    style={{
                      left: tickToContentX(bar * barStep),
                      height: TOTAL_HEIGHT,
                    }}
                  />
                );
              })}

            {ready && (
              <div
                className="pointer-events-none absolute top-0 border-r-2 border-roll-grid/80"
                style={{ left: tickToContentX(totalTicks), height: TOTAL_HEIGHT }}
              />
            )}

            <div
              className="absolute left-0 cursor-pointer"
              style={{
                top: ROW_LAYOUT[0].top,
                height: ROW_SEGMENTS,
                width: ready ? contentWidth : "100%",
              }}
              onPointerDown={onSongsPointerDown}
              onPointerMove={onDragMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
            >
              {timeline.segments.map((seg, idx) => (
                <div
                  key={seg.id}
                  className="pointer-events-none absolute rounded border border-border/80 px-1 text-[9px] leading-tight"
                  style={{
                    left: tickToContentX(seg.master_start_tick),
                    width: Math.max(2, tickToContentX(seg.master_end_tick - seg.master_start_tick)),
                    height: ROW_SEGMENTS - 4,
                    top: 2,
                    background: idx % 2 === 0 ? "var(--color-segment-a)" : "var(--color-segment-b)",
                  }}
                  title={seg.display_name}
                >
                  <div className="truncate font-medium">{seg.display_name}</div>
                </div>
              ))}
            </div>

            {ready && (
              <>
                <RangeBar
                  range={viewRange}
                  top={ROW_LAYOUT[1].top}
                  height={ROW_VIEW}
                  width={contentWidth}
                  tickToContentX={tickToContentX}
                  active={activeLayer === "view"}
                  variant="view"
                  title="View range — drag edges or body to pan detail"
                  onResizeStart={(edge, e) => beginDrag(edge === "start" ? "view-start" : "view-end", e)}
                  onPanStart={(e) => beginDrag("view-pan", e)}
                  onPointerMove={onDragMove}
                  onPointerUp={endDrag}
                  onPointerCancel={endDrag}
                />

                {timeline.transitions.length === 0 ? (
                  <div
                    className="pointer-events-none absolute left-0 flex items-center px-2 text-[9px] italic text-muted/60"
                    style={{
                      top: ROW_LAYOUT[2].top,
                      height: ROW_TRANS,
                      width: contentWidth,
                    }}
                  >
                    No transitions yet
                  </div>
                ) : (
                  timeline.transitions.map((trans) => {
                    const range = getTransitionTickRange(timeline, trans);
                    if (!range) return null;
                    const selected = selectedTransitionId === trans.id;
                    const displayRange =
                      selected && displayTransitionRange ? displayTransitionRange : range;
                    return (
                      <RangeBar
                        key={trans.id}
                        range={displayRange}
                        top={ROW_LAYOUT[2].top}
                        height={ROW_TRANS}
                        width={contentWidth}
                        tickToContentX={tickToContentX}
                        active={selected && activeLayer === "trans"}
                        variant="trans"
                        dashed={selected}
                        dimmed={!selected}
                        title={
                          selected
                            ? "Transition scope — drag to adjust AI reference range"
                            : "Click to select this transition"
                        }
                        onSelect={(e) => {
                          e.preventDefault();
                          onSelectTransition(trans.id);
                        }}
                        onResizeStart={(edge, e) =>
                          beginTransitionDrag(edge === "start" ? "trans-start" : "trans-end", trans.id, e)
                        }
                        onPanStart={(e) => beginTransitionDrag("trans-pan", trans.id, e)}
                        onPointerMove={onDragMove}
                        onPointerUp={endDrag}
                        onPointerCancel={endDrag}
                      />
                    );
                  })
                )}

                <RangeBar
                  range={editRange}
                  top={ROW_LAYOUT[3].top}
                  height={ROW_EDIT}
                  width={contentWidth}
                  tickToContentX={tickToContentX}
                  active={activeLayer === "edit"}
                  variant="edit"
                  title="Edit range — drag edges or body to move AI edit window"
                  onResizeStart={(edge, e) => beginDrag(edge === "start" ? "edit-start" : "edit-end", e)}
                  onPanStart={(e) => beginDrag("edit-pan", e)}
                  onPointerMove={onDragMove}
                  onPointerUp={endDrag}
                  onPointerCancel={endDrag}
                />

                <div
                  className="pointer-events-none absolute top-0 z-30 w-0.5 bg-playhead"
                  style={{ transform: `translateX(${playheadX}px)`, height: TOTAL_HEIGHT }}
                />
                <div
                  className="absolute z-40 -translate-x-1/2 cursor-ew-resize rounded-full bg-playhead ring-2 ring-background"
                  style={{
                    transform: `translateX(${playheadX}px)`,
                    top: ROW_LAYOUT[0].top + ROW_SEGMENTS / 2 - 8,
                    width: 16,
                    height: 16,
                    pointerEvents: "none",
                  }}
                  title="Playhead"
                />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
