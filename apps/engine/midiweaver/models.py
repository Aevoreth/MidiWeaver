from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TrackSummary(BaseModel):
    track_id: str
    name: str
    channel: int | None = None
    program: int | None = None
    is_drum: bool = False
    note_min: int | None = None
    note_max: int | None = None
    note_count: int = 0
    density_per_bar: float = 0.0
    quantize_enabled: bool = False
    quantize_strength: float = 0.0
    snap_override: str = "follow_global"


class TempoEvent(BaseModel):
    tick: int
    bpm: float


class TimeSignatureEvent(BaseModel):
    tick: int
    numerator: int
    denominator: int


class NoteEvent(BaseModel):
    pitch: int
    start_tick: int
    duration_ticks: int
    velocity: int = 64
    channel: int = 0


class TrackData(BaseModel):
    track_id: str
    name: str
    channel: int | None = None
    program: int | None = None
    is_drum: bool = False
    notes: list[NoteEvent] = Field(default_factory=list)
    mute: bool = False
    solo: bool = False
    volume: float = 1.0
    master_track_id: str | None = None
    snap_override: str = "follow_global"
    quantize_enabled: bool = False
    quantize_strength: float = 0.0


class AnalysisSnapshot(BaseModel):
    song_id: str
    source_filename: str
    ppq: int
    bar_count: float
    estimated_bpm: float
    bpm_range: tuple[float, float]
    time_sig: tuple[int, int]
    key: str | None = None
    tempo_events: list[TempoEvent] = Field(default_factory=list)
    time_sig_events: list[TimeSignatureEvent] = Field(default_factory=list)
    track_summaries: list[TrackSummary] = Field(default_factory=list)
    tracks: list[TrackData] = Field(default_factory=list)
    trim_start_tick: int = 0
    trim_end_tick: int | None = None
    loop_boundaries: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SongSegment(BaseModel):
    id: str
    display_name: str
    source_filename: str
    source_path: str = ""
    master_start_tick: int = 0
    master_end_tick: int = 0
    analysis: AnalysisSnapshot | None = None
    trim_start_ticks: int = 0
    trim_end_ticks: int | None = None


class TransitionConfig(BaseModel):
    id: str
    from_song_id: str
    to_song_id: str
    duration_bars: float = 4.0
    mix_out_bars: float = 2.0
    mix_in_bars: float = 2.0
    master_start_bar: float = 0.0
    master_end_bar: float = 0.0
    template_id: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)


class MasterTimeline(BaseModel):
    master_ppq: int = 480
    segments: list[SongSegment] = Field(default_factory=list)
    transitions: list[TransitionConfig] = Field(default_factory=list)
    tempo_events: list[TempoEvent] = Field(default_factory=list)
    total_ticks: int = 0
    total_bars: float = 0.0


class TrackMappingEntry(BaseModel):
    master_track_id: str
    role: str
    song_track_ids: dict[str, str] = Field(default_factory=dict)


class ProjectMetadata(BaseModel):
    version: str = "1.0"
    name: str = "Untitled Set"
    master_ppq: int = 480
    songs: list[dict[str, Any]] = Field(default_factory=list)
    track_mapping: list[TrackMappingEntry] = Field(default_factory=list)
    transitions: list[TransitionConfig] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class TempoOption(BaseModel):
    label: str
    policy: str
    duration_bars: float
    start_bpm: float
    end_bpm: float


class Operation(BaseModel):
    op_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    description: str = ""


class OperationPlan(BaseModel):
    plan_summary: str
    tempo_options: list[TempoOption] = Field(default_factory=list)
    selected_tempo_option_index: int = 0
    ops: list[Operation] = Field(default_factory=list)


class RevisionDiff(BaseModel):
    added_notes: list[dict[str, Any]] = Field(default_factory=list)
    removed_notes: list[dict[str, Any]] = Field(default_factory=list)
    moved_notes: list[dict[str, Any]] = Field(default_factory=list)
    tempo_changes: list[dict[str, Any]] = Field(default_factory=list)


class Revision(BaseModel):
    id: int
    label: str
    ops: list[Operation]
    diff: RevisionDiff | None = None
    created_at: str = ""


class ExportReport(BaseModel):
    output_path: str
    format: str
    track_count: int
    tempo_ramps_applied: int
    warnings: list[str] = Field(default_factory=list)
    unmapped_tracks: list[str] = Field(default_factory=list)
    key_clashes: list[str] = Field(default_factory=list)
