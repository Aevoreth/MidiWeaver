import { useCallback, useEffect, useMemo, useState } from "react";
import { barToTicks } from "@/lib/utils";
import {
  clampRange,
  clampTick,
  DEFAULT_PX_PER_TICK,
  fitPxPerTick,
  MAX_PX_PER_TICK,
  MIN_PX_PER_TICK,
  paddingTicks,
  type TickRange,
} from "./timelineUtils";

export function useTimelineViewport(totalTicks: number, ppq: number) {
  const defaultEditEnd = barToTicks(8, ppq);

  const [scrollStartTick, setScrollStartTick] = useState(0);
  const [pxPerTick, setPxPerTick] = useState(DEFAULT_PX_PER_TICK);
  const [viewportWidthPx, setViewportWidthPx] = useState(800);
  const [editStartTick, setEditStartTick] = useState(0);
  const [editEndTick, setEditEndTick] = useState(defaultEditEnd);

  useEffect(() => {
    setEditEndTick((prev) => Math.min(Math.max(prev, barToTicks(1, ppq)), totalTicks || defaultEditEnd));
  }, [totalTicks, ppq, defaultEditEnd]);

  useEffect(() => {
    setScrollStartTick((prev) => {
      const span = viewportWidthPx / pxPerTick;
      return Math.max(0, Math.min(prev, Math.max(0, totalTicks - span)));
    });
  }, [totalTicks, viewportWidthPx, pxPerTick]);

  const viewEndTick = useMemo(() => {
    const span = Math.max(ppq, viewportWidthPx / pxPerTick);
    return Math.min(totalTicks || span, scrollStartTick + span);
  }, [scrollStartTick, pxPerTick, viewportWidthPx, totalTicks, ppq]);

  const viewRange: TickRange = useMemo(
    () => ({ startTick: scrollStartTick, endTick: viewEndTick }),
    [scrollStartTick, viewEndTick],
  );

  const editRange: TickRange = useMemo(
    () => clampRange({ startTick: editStartTick, endTick: editEndTick }, totalTicks || editEndTick, ppq),
    [editStartTick, editEndTick, totalTicks, ppq],
  );

  const setViewRange = useCallback(
    (range: TickRange) => {
      const clamped = clampRange(range, totalTicks, ppq);
      setScrollStartTick(clamped.startTick);
      const span = clamped.endTick - clamped.startTick;
      if (span > 0 && viewportWidthPx > 0) {
        setPxPerTick(fitPxPerTick(viewportWidthPx, span));
      }
    },
    [totalTicks, ppq, viewportWidthPx],
  );

  const setEditRange = useCallback(
    (range: TickRange) => {
      const clamped = clampRange(range, totalTicks, ppq);
      setEditStartTick(clamped.startTick);
      setEditEndTick(clamped.endTick);
    },
    [totalTicks, ppq],
  );

  const zoomAt = useCallback(
    (cursorTick: number, factor: number) => {
      const nextPx = Math.min(MAX_PX_PER_TICK, Math.max(MIN_PX_PER_TICK, pxPerTick * factor));
      const span = viewportWidthPx / nextPx;
      const center = cursorTick;
      let start = center - span / 2;
      if (start < 0) start = 0;
      if (start + span > totalTicks) start = Math.max(0, totalTicks - span);
      setPxPerTick(nextPx);
      setScrollStartTick(start);
    },
    [pxPerTick, viewportWidthPx, totalTicks],
  );

  const zoomToRange = useCallback(
    (range: TickRange, padBars = 1) => {
      const pad = paddingTicks(ppq, padBars);
      const start = clampTick(range.startTick - pad, totalTicks);
      const end = clampTick(range.endTick + pad, totalTicks);
      setViewRange({ startTick: start, endTick: Math.max(start + ppq, end) });
    },
    [ppq, totalTicks, setViewRange],
  );

  const zoomToEditRange = useCallback(() => {
    zoomToRange(editRange);
  }, [editRange, zoomToRange]);

  const zoomFitAll = useCallback(() => {
    if (totalTicks <= 0) return;
    setScrollStartTick(0);
    setPxPerTick(fitPxPerTick(viewportWidthPx, totalTicks));
  }, [totalTicks, viewportWidthPx]);

  const panView = useCallback(
    (deltaTicks: number) => {
      const span = viewEndTick - scrollStartTick;
      let start = scrollStartTick + deltaTicks;
      start = Math.max(0, Math.min(Math.max(0, totalTicks - span), start));
      setScrollStartTick(start);
    },
    [scrollStartTick, viewEndTick, totalTicks],
  );

  return {
    scrollStartTick,
    viewEndTick,
    viewRange,
    editStartTick: editRange.startTick,
    editEndTick: editRange.endTick,
    editRange,
    pxPerTick,
    viewportWidthPx,
    setViewportWidthPx,
    setScrollStartTick,
    setViewRange,
    setEditRange,
    setPxPerTick,
    zoomAt,
    zoomToEditRange,
    zoomFitAll,
    panView,
  };
}
