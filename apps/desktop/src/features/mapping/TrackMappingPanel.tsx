import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { TimelineData, TrackMappingEntry } from "@/lib/api";

interface TrackMappingPanelProps {
  timeline: TimelineData | null;
  trackMapping: TrackMappingEntry[];
  onChange: (mapping: TrackMappingEntry[]) => void;
  onSave: () => Promise<void>;
  disabled?: boolean;
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function newLinkGroup(index: number): TrackMappingEntry {
  const role = `Link ${index}`;
  return {
    master_track_id: slugify(role) || `link_${index}`,
    role,
    song_track_ids: {},
  };
}

export function TrackMappingPanel({
  timeline,
  trackMapping,
  onChange,
  onSave,
  disabled,
}: TrackMappingPanelProps) {
  const updateEntry = (index: number, patch: Partial<TrackMappingEntry>) => {
    const next = [...trackMapping];
    next[index] = { ...next[index], ...patch };
    onChange(next);
  };

  const updateRole = (index: number, role: string) => {
    updateEntry(index, {
      role,
      master_track_id: slugify(role) || trackMapping[index].master_track_id,
    });
  };

  const updateSongTrack = (index: number, songId: string, trackId: string) => {
    const entry = trackMapping[index];
    const song_track_ids = { ...entry.song_track_ids };
    if (trackId) song_track_ids[songId] = trackId;
    else delete song_track_ids[songId];
    updateEntry(index, { song_track_ids });
  };

  const removeEntry = (index: number) => {
    onChange(trackMapping.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2 text-xs overflow-auto">
      <p className="text-muted leading-relaxed">
        Link tracks that should merge on export. Unlinked tracks stay separate per song.
      </p>

      {trackMapping.map((entry, index) => (
        <div key={`${entry.master_track_id}-${index}`} className="rounded border border-border p-2">
          <div className="mb-1 flex items-center gap-1">
            <input
              className="min-w-0 flex-1 rounded border border-border bg-surface px-1 py-0.5 font-medium"
              value={entry.role}
              placeholder="Link name (e.g. Nylon Guitar)"
              onChange={(e) => updateRole(index, e.target.value)}
            />
            <button
              type="button"
              className="shrink-0 rounded p-1 text-muted hover:bg-surface hover:text-red-400"
              title="Remove link group"
              onClick={() => removeEntry(index)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
          {timeline?.segments.map((seg) => (
            <label key={seg.id} className="mb-1 flex flex-col gap-0.5">
              <span className="text-muted">{seg.display_name}</span>
              <select
                className="rounded border border-border bg-surface px-1 py-0.5"
                value={entry.song_track_ids[seg.id] ?? ""}
                onChange={(e) => updateSongTrack(index, seg.id, e.target.value)}
              >
                <option value="">— not linked —</option>
                {seg.analysis?.tracks.map((t) => (
                  <option key={t.track_id} value={t.track_id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      ))}

      <Button
        variant="ghost"
        size="sm"
        className="w-full"
        onClick={() => onChange([...trackMapping, newLinkGroup(trackMapping.length + 1)])}
      >
        <Plus className="mr-1 h-3.5 w-3.5" />
        Add link group
      </Button>

      <Button size="sm" className="w-full" disabled={disabled} onClick={() => void onSave()}>
        Save mapping
      </Button>
    </div>
  );
}
