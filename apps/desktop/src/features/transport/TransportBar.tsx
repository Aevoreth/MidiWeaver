import { Focus, Pause, Play, SkipBack, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface TransportBarProps {
  className?: string;
  playing: boolean;
  playheadTick: number;
  ppq: number;
  followPlayhead: boolean;
  error?: string | null;
  onPlay: () => void;
  onPause: () => void;
  onStop: () => void;
  onSeekStart: () => void;
  onFollowPlayheadChange: (enabled: boolean) => void;
}

export function TransportBar({
  className,
  playing,
  playheadTick,
  ppq,
  followPlayhead,
  error,
  onPlay,
  onPause,
  onStop,
  onSeekStart,
  onFollowPlayheadChange,
}: TransportBarProps) {
  const bar = Math.max(0, playheadTick / (ppq * 4)).toFixed(2);

  return (
    <div className={cn("flex items-center gap-3 border-t border-border bg-panel px-3 py-2", className)}>
      <div className="flex items-center gap-1">
        <Button size="icon" variant="secondary" onClick={onSeekStart} aria-label="Seek to start">
          <SkipBack className="h-4 w-4" />
        </Button>
        {playing ? (
          <Button size="icon" onClick={onPause} aria-label="Pause">
            <Pause className="h-4 w-4" />
          </Button>
        ) : (
          <Button size="icon" onClick={onPlay} aria-label="Play">
            <Play className="h-4 w-4" />
          </Button>
        )}
        <Button size="icon" variant="secondary" onClick={onStop} aria-label="Stop">
          <Square className="h-4 w-4" />
        </Button>
      </div>

      <div className="font-mono text-xs text-muted">
        Bar {bar} · tick {Math.max(0, playheadTick)}
      </div>

      <Button
        size="sm"
        variant={followPlayhead ? "default" : "secondary"}
        className="h-8 gap-1.5 text-xs"
        onClick={() => onFollowPlayheadChange(!followPlayhead)}
        aria-pressed={followPlayhead}
        title="Scroll piano roll to follow playhead during playback"
      >
        <Focus className="h-3.5 w-3.5" />
        Follow
      </Button>

      {error && (
        <div className="min-w-0 flex-1 truncate text-xs text-error" title={error}>
          {error}
        </div>
      )}
    </div>
  );
}
