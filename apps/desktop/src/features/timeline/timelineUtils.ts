import type { TimelineData, TransitionConfig } from "@/lib/api";
import { barToTicks, ticksToBar } from "@/lib/utils";

export interface TickRange {
  startTick: number;
  endTick: number;
}

export const MIN_PX_PER_TICK = 0.02;
export const MAX_PX_PER_TICK = 0.5;
export const DEFAULT_PX_PER_TICK = 0.08;
export const MIN_OVERVIEW_ZOOM = 1;
export const MAX_OVERVIEW_ZOOM = 32;
export const HANDLE_WIDTH_PX = 8;

/** Authoritative project length in ticks (guards bad/missing total_ticks). */
export function projectTotalTicks(timeline: TimelineData | null, ppq = 480): number {
  if (!timeline) return ppq * 4;
  let maxTick = timeline.total_ticks ?? 0;
  for (const seg of timeline.segments) {
    maxTick = Math.max(maxTick, seg.master_end_tick);
    if (!seg.analysis) continue;
    const offset = seg.master_start_tick - seg.analysis.trim_start_tick;
    for (const track of seg.analysis.tracks) {
      for (const note of track.notes) {
        maxTick = Math.max(maxTick, offset + note.start_tick + note.duration_ticks);
      }
    }
  }
  return Math.max(maxTick, ppq * 4);
}

export function fitPxPerTick(viewportWidthPx: number, totalTicks: number): number {
  if (totalTicks <= 0 || viewportWidthPx <= 0) return DEFAULT_PX_PER_TICK;
  return Math.min(MAX_PX_PER_TICK, Math.max(MIN_PX_PER_TICK, viewportWidthPx / totalTicks));
}

export function fitOverviewPxPerTick(viewportWidthPx: number, totalTicks: number): number {
  if (totalTicks <= 0 || viewportWidthPx <= 0) return 0.05;
  return viewportWidthPx / totalTicks;
}

export function clampTick(tick: number, totalTicks: number): number {
  return Math.max(0, Math.min(totalTicks, tick));
}

export function clampRange(range: TickRange, totalTicks: number, minSpanTicks = 1): TickRange {
  let start = clampTick(Math.min(range.startTick, range.endTick), totalTicks);
  let end = clampTick(Math.max(range.startTick, range.endTick), totalTicks);
  if (end - start < minSpanTicks) {
    end = Math.min(totalTicks, start + minSpanTicks);
  }
  return { startTick: start, endTick: end };
}

export function tickRangeToBarRange(range: TickRange, ppq: number): [number, number] {
  return [ticksToBar(range.startTick, ppq), ticksToBar(range.endTick, ppq)];
}

export function barRangeToTickRange(startBar: number, endBar: number, ppq: number): TickRange {
  return {
    startTick: barToTicks(Math.min(startBar, endBar), ppq),
    endTick: barToTicks(Math.max(startBar, endBar), ppq),
  };
}

export function getTransitionTickRange(
  timeline: TimelineData,
  trans: TransitionConfig,
): TickRange | null {
  const ppq = timeline.master_ppq;
  const fromSeg = timeline.segments.find((s) => s.id === trans.from_song_id);
  const toSeg = timeline.segments.find((s) => s.id === trans.to_song_id);
  if (!fromSeg || !toSeg) return null;
  return {
    startTick: fromSeg.master_end_tick - trans.mix_out_bars * ppq * 4,
    endTick: toSeg.master_start_tick + trans.mix_in_bars * ppq * 4,
  };
}

export function mixOutBarsFromTick(
  timeline: TimelineData,
  trans: TransitionConfig,
  startTick: number,
): number {
  const ppq = timeline.master_ppq;
  const fromSeg = timeline.segments.find((s) => s.id === trans.from_song_id);
  if (!fromSeg) return trans.mix_out_bars;
  const segLen = fromSeg.master_end_tick - fromSeg.master_start_tick;
  const bars = (fromSeg.master_end_tick - startTick) / (ppq * 4);
  const maxBars = segLen / (ppq * 4);
  return Math.max(0.25, Math.min(maxBars, bars));
}

export function mixInBarsFromTick(
  timeline: TimelineData,
  trans: TransitionConfig,
  endTick: number,
): number {
  const ppq = timeline.master_ppq;
  const toSeg = timeline.segments.find((s) => s.id === trans.to_song_id);
  if (!toSeg) return trans.mix_in_bars;
  const segLen = toSeg.master_end_tick - toSeg.master_start_tick;
  const bars = (endTick - toSeg.master_start_tick) / (ppq * 4);
  const maxBars = segLen / (ppq * 4);
  return Math.max(0.25, Math.min(maxBars, bars));
}

export function paddingTicks(ppq: number, bars = 1): number {
  return bars * ppq * 4;
}
