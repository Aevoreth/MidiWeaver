import type { TimelineData } from "@/lib/api";
import { ticksToBar } from "@/lib/utils";

interface TimelineProps {
  timeline: TimelineData | null;
  playheadTick: number;
  selectedTransitionId: string | null;
  onSelectTransition: (id: string | null) => void;
  onSeek: (tick: number) => void;
  snap: string;
}

export function TimelineView({
  timeline,
  playheadTick,
  selectedTransitionId,
  onSelectTransition,
  onSeek,
  snap,
}: TimelineProps) {
  const ppq = timeline?.master_ppq ?? 480;
  const totalTicks = timeline?.total_ticks ?? ppq * 16;
  const pxPerTick = 0.05;

  if (!timeline) {
    return (
      <div className="flex h-full items-center justify-center text-muted">
        Import MIDI files to begin building your set.
      </div>
    );
  }

  const width = totalTicks * pxPerTick;

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center justify-between text-xs text-muted">
        <span>Master timeline · snap: {snap}</span>
        <span>
          Bar {ticksToBar(playheadTick, ppq).toFixed(2)} / {timeline.total_bars.toFixed(1)}
        </span>
      </div>
      <div className="relative flex-1 overflow-auto rounded-md border border-border bg-surface">
        <div className="relative h-24 min-w-full" style={{ width }}>
          <div className="sticky top-0 z-20 h-6 border-b border-border bg-panel">
            {Array.from({ length: Math.ceil(ticksToBar(totalTicks, ppq)) + 1 }).map((_, bar) => (
              <div
                key={bar}
                className="absolute top-0 h-full border-l border-roll-grid text-[10px] text-muted pl-1"
                style={{ left: bar * ppq * 4 * pxPerTick }}
              >
                {bar + 1}
              </div>
            ))}
          </div>

          <div className="relative h-16 mt-1">
            {timeline.segments.map((seg, idx) => (
              <button
                key={seg.id}
                type="button"
                className="absolute top-1 h-12 rounded border border-border px-2 text-left text-xs hover:brightness-110"
                style={{
                  left: seg.master_start_tick * pxPerTick,
                  width: (seg.master_end_tick - seg.master_start_tick) * pxPerTick,
                  background: idx % 2 === 0 ? "var(--color-segment-a)" : "var(--color-segment-b)",
                }}
                onClick={() => onSeek(seg.master_start_tick)}
              >
                <div className="font-medium truncate">{seg.display_name}</div>
                <div className="text-muted">
                  {seg.analysis?.estimated_bpm.toFixed(0)} BPM · {seg.analysis?.bar_count.toFixed(1)} bars
                </div>
              </button>
            ))}

            {timeline.transitions.map((trans) => {
              const fromSeg = timeline.segments.find((s) => s.id === trans.from_song_id);
              const toSeg = timeline.segments.find((s) => s.id === trans.to_song_id);
              if (!fromSeg || !toSeg) return null;
              const start = fromSeg.master_end_tick - trans.mix_out_bars * ppq * 4;
              const end = toSeg.master_start_tick + trans.mix_in_bars * ppq * 4;
              const selected = selectedTransitionId === trans.id;
              return (
                <button
                  key={trans.id}
                  type="button"
                  className="absolute top-0 h-14 rounded border border-dashed"
                  style={{
                    left: start * pxPerTick,
                    width: Math.max(8, (end - start) * pxPerTick),
                    background: "var(--color-transition)",
                    borderColor: selected ? "var(--color-accent)" : "var(--color-playhead)",
                    boxShadow: selected ? "0 0 0 1px var(--color-accent)" : undefined,
                  }}
                  onClick={() => onSelectTransition(trans.id)}
                  title={`Transition ${trans.from_song_id} → ${trans.to_song_id}`}
                />
              );
            })}

            <div
              className="absolute top-0 z-30 h-full w-0.5 bg-playhead pointer-events-none"
              style={{ left: playheadTick * pxPerTick }}
            />
          </div>
        </div>

        <button
          type="button"
          aria-label="Seek timeline"
          className="absolute inset-0 top-6 opacity-0"
          onClick={(e) => {
            const rect = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
            const x = e.clientX - rect.left + (e.currentTarget.parentElement?.scrollLeft ?? 0);
            onSeek(Math.max(0, Math.round(x / pxPerTick)));
          }}
        />
      </div>
    </div>
  );
}
