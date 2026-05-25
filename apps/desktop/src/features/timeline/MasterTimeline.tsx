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
  | "trans-start"
  | "trans-end"
  | null;

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

const ROW_SEGMENTS = 22;
const ROW_VIEW = 10;
const ROW_EDIT = 10;
const ROW_TRANS = 10;
const TOTAL_HEIGHT = ROW_SEGMENTS + ROW_VIEW + ROW_EDIT + ROW_TRANS + 8;

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

  const hitTest = useCallback(
    (clientX: number): DragTarget => {
      if (!scrollRef.current || overviewPxPerTick <= 0) return null;
      const x = clientXToContentX(clientX);
      const tick = x / overviewPxPerTick;
      const playheadX = tickToContentX(displayPlayheadTick);
      if (Math.abs(x - playheadX) <= HANDLE_WIDTH_PX) return "playhead";

      if (selectedTransitionId && displayTransitionRange) {
        const ts = tickToContentX(displayTransitionRange.startTick);
        const te = tickToContentX(displayTransitionRange.endTick);
        if (Math.abs(x - ts) <= HANDLE_WIDTH_PX) return "trans-start";
        if (Math.abs(x - te) <= HANDLE_WIDTH_PX) return "trans-end";
      }

      const es = tickToContentX(editRange.startTick);
      const ee = tickToContentX(editRange.endTick);
      if (Math.abs(x - es) <= HANDLE_WIDTH_PX) return "edit-start";
      if (Math.abs(x - ee) <= HANDLE_WIDTH_PX) return "edit-end";

      const vs = tickToContentX(viewRange.startTick);
      const ve = tickToContentX(viewRange.endTick);
      if (Math.abs(x - vs) <= HANDLE_WIDTH_PX) return "view-start";
      if (Math.abs(x - ve) <= HANDLE_WIDTH_PX) return "view-end";
      if (tick >= viewRange.startTick && tick <= viewRange.endTick) return "view-pan";

      return null;
    },
    [
      overviewPxPerTick,
      clientXToContentX,
      tickToContentX,
      displayPlayheadTick,
      selectedTransitionId,
      displayTransitionRange,
      editRange,
      viewRange,
    ],
  );

  const onPointerDown = (e: React.PointerEvent) => {
    if (!timeline || overviewPxPerTick <= 0) return;
    const target = hitTest(e.clientX);
    if (target) {
      e.currentTarget.setPointerCapture(e.pointerId);
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

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || !timeline || overviewPxPerTick <= 0) return;
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
      case "trans-start":
      case "trans-end": {
        if (!drag.origTrans || !selectedTransitionId) break;
        const trans = timeline.transitions.find((t) => t.id === selectedTransitionId);
        if (!trans) break;
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
        const mixOut = mixOutBarsFromTick(timeline, trans, nextRange.startTick);
        const mixIn = mixInBarsFromTick(timeline, trans, nextRange.endTick);
        if (dragRef.current) {
          dragRef.current.pendingMixOut = mixOut;
          dragRef.current.pendingMixIn = mixIn;
        }
        setTransPreview(nextRange);
        break;
      }
      default:
        break;
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (drag?.target === "playhead" && overviewPxPerTick > 0) {
      const deltaTick = (e.clientX - drag.startX) / overviewPxPerTick;
      onSeek(snapTickLocal(drag.origPlayhead + deltaTick));
    }
    if (
      drag &&
      (drag.target === "trans-start" || drag.target === "trans-end") &&
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
  const viewTop = ROW_SEGMENTS + 2;
  const editTop = viewTop + ROW_VIEW + 2;
  const transTop = editTop + ROW_EDIT + 2;
  const playheadX = tickToContentX(displayPlayheadTick);
  const ready = viewportWidth > 0 && overviewPxPerTick > 0;
  const dragCursor =
    activeDragTarget === "view-pan"
      ? "cursor-grabbing"
      : activeDragTarget
        ? "cursor-ew-resize"
        : "cursor-crosshair";

  return (
    <div ref={containerRef} className="flex h-full min-h-0 flex-col gap-1">
      <div className="flex shrink-0 items-center justify-between text-[10px] text-muted">
        <span className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm border border-accent/60 bg-accent/10" />
            View
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm bg-edit-range/40" />
            Edit
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm border border-dashed border-playhead bg-transition" />
            Transition
          </span>
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
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden rounded-md border border-border bg-surface"
        style={{ minHeight: TOTAL_HEIGHT }}
      >
        <div
          className={`relative touch-none ${dragCursor}`}
          style={{
            width: ready ? contentWidth : viewportWidth || "100%",
            height: TOTAL_HEIGHT,
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
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

          <div className="absolute left-0" style={{ top: 2, height: ROW_SEGMENTS, width: ready ? contentWidth : "100%" }}>
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
            {timeline.transitions.map((trans) => {
              const range = getTransitionTickRange(timeline, trans);
              if (!range) return null;
              const selected = selectedTransitionId === trans.id;
              return (
                <div
                  key={trans.id}
                  className="pointer-events-none absolute rounded border border-dashed"
                  style={{
                    left: tickToContentX(range.startTick),
                    width: Math.max(4, tickToContentX(range.endTick - range.startTick)),
                    height: ROW_SEGMENTS - 4,
                    top: 2,
                    background: "var(--color-transition)",
                    borderColor: selected ? "var(--color-accent)" : "var(--color-playhead)",
                    opacity: selected ? 1 : 0.6,
                  }}
                />
              );
            })}
          </div>

          {ready && (
            <>
              <div className="absolute left-0" style={{ top: viewTop, height: ROW_VIEW, width: contentWidth }}>
                <div
                  className="absolute rounded-sm border-2 border-accent/70 bg-accent/5"
                  style={{
                    left: tickToContentX(viewRange.startTick),
                    width: Math.max(4, tickToContentX(viewRange.endTick - viewRange.startTick)),
                    height: ROW_VIEW,
                    boxShadow: activeLayer === "view" ? "0 0 0 1px var(--color-accent)" : undefined,
                  }}
                  title="View range — drag edges or center to pan detail"
                >
                  <div className="absolute left-0 top-0 h-full w-4 cursor-ew-resize bg-accent/40" />
                  <div className="absolute right-0 top-0 h-full w-4 cursor-ew-resize bg-accent/40" />
                </div>
              </div>

              <div className="absolute left-0" style={{ top: editTop, height: ROW_EDIT, width: contentWidth }}>
                <div
                  className="absolute rounded-sm border border-edit-range/50 bg-edit-range/35"
                  style={{
                    left: tickToContentX(editRange.startTick),
                    width: Math.max(4, tickToContentX(editRange.endTick - editRange.startTick)),
                    height: ROW_EDIT,
                    boxShadow: activeLayer === "edit" ? "0 0 0 1px var(--color-edit-range)" : undefined,
                  }}
                >
                  <div className="absolute left-0 top-0 h-full w-4 cursor-ew-resize bg-edit-range/60" />
                  <div className="absolute right-0 top-0 h-full w-4 cursor-ew-resize bg-edit-range/60" />
                </div>
              </div>

              {selectedTransitionId && displayTransitionRange && (
                <div className="absolute left-0" style={{ top: transTop, height: ROW_TRANS, width: contentWidth }}>
                  <div
                    className="absolute rounded-sm border border-dashed border-playhead bg-playhead/10"
                    style={{
                      left: tickToContentX(displayTransitionRange.startTick),
                      width: Math.max(
                        4,
                        tickToContentX(displayTransitionRange.endTick - displayTransitionRange.startTick),
                      ),
                      height: ROW_TRANS,
                      boxShadow: activeLayer === "trans" ? "0 0 0 1px var(--color-playhead)" : undefined,
                    }}
                  >
                    <div className="absolute left-0 top-0 h-full w-4 cursor-ew-resize bg-playhead/50" />
                    <div className="absolute right-0 top-0 h-full w-4 cursor-ew-resize bg-playhead/50" />
                  </div>
                </div>
              )}

              <div
                className="pointer-events-none absolute top-0 z-30 w-0.5 bg-playhead"
                style={{ transform: `translateX(${playheadX}px)`, height: TOTAL_HEIGHT }}
              />
              <div
                className="absolute z-40 h-3 w-3 -translate-x-1/2 cursor-ew-resize rounded-full bg-playhead ring-2 ring-background"
                style={{ transform: `translateX(${playheadX}px)`, top: 0 }}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
