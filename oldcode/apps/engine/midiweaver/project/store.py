from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from midiweaver.analysis.analyzer import analyze_midi
from midiweaver.models import (
    MasterTimeline,
    Operation,
    OperationPlan,
    ProjectMetadata,
    Revision,
    RevisionDiff,
    SongSegment,
    TrackMappingEntry,
    TransitionConfig,
)
from midiweaver.normalize.timeline import build_master_timeline, create_transition_config
from midiweaver.ops.executor import OpContext, OpExecutor


class ProjectStore:
    """Manages .midiweaver/ bundle with SQLite revision history."""

    def __init__(self, bundle_path: Path | str):
        self.bundle_path = Path(bundle_path)
        self.db_path = self.bundle_path / "project.db"
        self.project_json = self.bundle_path / "project.json"
        self.sources_dir = self.bundle_path / "sources"
        self.exports_dir = self.bundle_path / "exports"
        self.previews_dir = self.bundle_path / "previews"
        self._conn: sqlite3.Connection | None = None
        self._timeline: MasterTimeline | None = None
        self._undo_pointer: int = 0
        self._max_revision: int = 0

    def create(self, name: str, master_ppq: int = 480) -> ProjectMetadata:
        self.bundle_path.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(exist_ok=True)
        self.exports_dir.mkdir(exist_ok=True)
        self.previews_dir.mkdir(exist_ok=True)
        meta = ProjectMetadata(name=name, master_ppq=master_ppq)
        self._write_meta(meta)
        self._init_db()
        self._timeline = MasterTimeline(master_ppq=master_ppq)
        return meta

    def load(self) -> ProjectMetadata:
        if not self.project_json.exists():
            raise FileNotFoundError(f"Project not found: {self.bundle_path}")
        meta = ProjectMetadata(**json.loads(self.project_json.read_text(encoding="utf-8")))
        self._init_db()
        self._rebuild_timeline(meta)
        if self._undo_pointer > 0:
            self._replay_to_pointer()
        return meta

    def save(self, meta: ProjectMetadata) -> None:
        self._write_meta(meta)

    def _write_meta(self, meta: ProjectMetadata) -> None:
        self.project_json.write_text(
            meta.model_dump_json(indent=2), encoding="utf-8"
        )

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                ops_json TEXT NOT NULL,
                diff_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS undo_stack (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                pointer INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transition_id TEXT,
                prompt TEXT,
                plan_json TEXT,
                status TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analysis_cache (
                song_id TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL
            );
            INSERT OR IGNORE INTO undo_stack (id, pointer) VALUES (1, 0);
            """
        )
        row = self._conn.execute("SELECT pointer FROM undo_stack WHERE id=1").fetchone()
        self._undo_pointer = row["pointer"] if row else 0
        row = self._conn.execute("SELECT MAX(id) as m FROM revisions").fetchone()
        self._max_revision = row["m"] or 0

    def _rebuild_timeline(self, meta: ProjectMetadata) -> None:
        segments: list[SongSegment] = []
        for song in meta.songs:
            song_id = song["id"]
            source_path = self.sources_dir / song["source_filename"]
            analysis = None
            if source_path.exists():
                analysis = analyze_midi(source_path, song_id)
                self._cache_analysis(song_id, analysis)
            else:
                cached = self._conn.execute(
                    "SELECT snapshot_json FROM analysis_cache WHERE song_id=?",
                    (song_id,),
                ).fetchone()
                if cached:
                    from midiweaver.models import AnalysisSnapshot

                    analysis = AnalysisSnapshot(**json.loads(cached["snapshot_json"]))

            segments.append(
                SongSegment(
                    id=song_id,
                    display_name=song.get("display_name", song_id),
                    source_filename=song["source_filename"],
                    source_path=str(source_path),
                    analysis=analysis,
                    trim_start_ticks=song.get("trim_start_ticks", 0),
                    trim_end_ticks=song.get("trim_end_ticks"),
                )
            )

        transitions = meta.transitions or []
        if not transitions and len(segments) > 1:
            transitions = [
                create_transition_config(segments[i].id, segments[i + 1].id)
                for i in range(len(segments) - 1)
            ]

        self._timeline = build_master_timeline(segments, meta.master_ppq, transitions)
        from midiweaver.normalize.notes import ensure_timeline_note_ids

        ensure_timeline_note_ids(self._timeline)

    def _persist_timeline_analysis(self) -> None:
        """Write current in-memory analysis snapshots back to the cache."""
        if not self._conn or not self._timeline:
            return
        for seg in self._timeline.segments:
            if seg.analysis:
                self._cache_analysis(seg.id, seg.analysis)

    def _cache_analysis(self, song_id: str, analysis: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO analysis_cache (song_id, snapshot_json) VALUES (?, ?)",
            (song_id, analysis.model_dump_json()),
        )
        self._conn.commit()

    def import_midi(self, source: Path | str, display_name: str | None = None) -> SongSegment:
        source = Path(source)
        song_id = f"song_{uuid.uuid4().hex[:8]}"
        dest = self.sources_dir / f"{song_id}{source.suffix}"
        shutil.copy2(source, dest)
        analysis = analyze_midi(dest, song_id)
        self._cache_analysis(song_id, analysis)

        segment = SongSegment(
            id=song_id,
            display_name=display_name or source.stem,
            source_filename=dest.name,
            source_path=str(dest),
            analysis=analysis,
            trim_start_ticks=analysis.trim_start_tick,
            trim_end_ticks=analysis.trim_end_tick,
        )

        meta = ProjectMetadata(**json.loads(self.project_json.read_text(encoding="utf-8")))
        meta.songs.append(
            {
                "id": song_id,
                "source_filename": dest.name,
                "display_name": segment.display_name,
                "trim_start_ticks": analysis.trim_start_tick,
                "trim_end_ticks": analysis.trim_end_tick,
            }
        )
        if len(meta.songs) > 1:
            meta.transitions.append(
                create_transition_config(meta.songs[-2]["id"], song_id)
            )
        self.save(meta)
        self._rebuild_timeline(meta)
        return segment

    @property
    def timeline(self) -> MasterTimeline:
        if self._timeline is None:
            raise RuntimeError("Project not loaded")
        return self._timeline

    def get_context(self) -> OpContext:
        return OpContext(self.timeline)

    def apply_ops(self, ops: list[Operation], label: str = "Apply ops") -> Revision:
        executor = OpExecutor()
        ctx = self.get_context()
        new_ctx, diff = executor.apply(ctx, ops)

        # Truncate redo branch
        if self._undo_pointer < self._max_revision:
            self._conn.execute(
                "DELETE FROM revisions WHERE id > ?", (self._undo_pointer,)
            )

        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO revisions (label, ops_json, diff_json, created_at) VALUES (?, ?, ?, ?)",
            (label, json.dumps([o.model_dump() for o in ops]), diff.model_dump_json(), now),
        )
        rev_id = cur.lastrowid
        self._max_revision = rev_id
        self._undo_pointer = rev_id
        self._conn.execute("UPDATE undo_stack SET pointer=? WHERE id=1", (rev_id,))
        self._conn.commit()

        self._timeline = new_ctx.timeline
        self._persist_timeline_analysis()
        return Revision(id=rev_id, label=label, ops=ops, diff=diff, created_at=now)

    def undo(self) -> Revision | None:
        if self._undo_pointer <= 0:
            return None
        self._undo_pointer -= 1
        self._conn.execute("UPDATE undo_stack SET pointer=? WHERE id=1", (self._undo_pointer,))
        self._conn.commit()
        self._replay_to_pointer()
        if self._undo_pointer == 0:
            return Revision(id=0, label="Base state", ops=[], diff=None, created_at="")
        return self.get_revision(self._undo_pointer)

    def redo(self) -> Revision | None:
        if self._undo_pointer >= self._max_revision:
            return None
        self._undo_pointer += 1
        self._conn.execute("UPDATE undo_stack SET pointer=? WHERE id=1", (self._undo_pointer,))
        self._conn.commit()
        self._replay_to_pointer()
        return self.get_revision(self._undo_pointer)

    def _replay_to_pointer(self) -> None:
        meta = ProjectMetadata(**json.loads(self.project_json.read_text(encoding="utf-8")))
        self._rebuild_timeline(meta)
        rows = self._conn.execute(
            "SELECT ops_json FROM revisions WHERE id <= ? ORDER BY id",
            (self._undo_pointer,),
        ).fetchall()
        executor = OpExecutor()
        ctx = self.get_context()
        for row in rows:
            ops = [Operation(**o) for o in json.loads(row["ops_json"])]
            ctx, _ = executor.apply(ctx, ops)
        self._timeline = ctx.timeline
        self._persist_timeline_analysis()

    def get_revision(self, rev_id: int) -> Revision | None:
        row = self._conn.execute(
            "SELECT * FROM revisions WHERE id=?", (rev_id,)
        ).fetchone()
        if not row:
            return None
        diff = RevisionDiff(**json.loads(row["diff_json"])) if row["diff_json"] else None
        return Revision(
            id=row["id"],
            label=row["label"],
            ops=[Operation(**o) for o in json.loads(row["ops_json"])],
            diff=diff,
            created_at=row["created_at"],
        )

    def history_state(self) -> dict[str, int]:
        return {"undo_pointer": self._undo_pointer, "max_revision": self._max_revision}

    def list_revisions(self) -> list[Revision]:
        rows = self._conn.execute("SELECT id FROM revisions ORDER BY id").fetchall()
        return [self.get_revision(r["id"]) for r in rows if self.get_revision(r["id"])]

    def compare_revisions(self, rev_a: int, rev_b: int) -> RevisionDiff:
        """Compare note state at two revision pointers."""
        meta = ProjectMetadata(**json.loads(self.project_json.read_text(encoding="utf-8")))
        self._rebuild_timeline(meta)
        executor = OpExecutor()

        def notes_at(pointer: int) -> list[dict]:
            ctx = self.get_context()
            rows = self._conn.execute(
                "SELECT ops_json FROM revisions WHERE id <= ? ORDER BY id", (pointer,)
            ).fetchall()
            for row in rows:
                ops = [Operation(**o) for o in json.loads(row["ops_json"])]
                ctx, _ = executor.apply(ctx, ops)
            from midiweaver.normalize.timeline import collect_master_notes

            return collect_master_notes(ctx.timeline)

        before = notes_at(rev_a)
        after = notes_at(rev_b)
        return executor._compute_diff(before, after)

    def save_template(self, name: str, transition: TransitionConfig, constraints: dict) -> str:
        tid = str(uuid.uuid4())
        data = {"transition": transition.model_dump(), "constraints": constraints}
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO templates (id, name, data_json, created_at) VALUES (?, ?, ?, ?)",
            (tid, name, json.dumps(data), now),
        )
        self._conn.commit()
        return tid

    def list_templates(self) -> list[dict]:
        rows = self._conn.execute("SELECT id, name, data_json, created_at FROM templates").fetchall()
        return [
            {"id": r["id"], "name": r["name"], "data": json.loads(r["data_json"]), "created_at": r["created_at"]}
            for r in rows
        ]

    def apply_template(self, template_id: str, from_song_id: str, to_song_id: str) -> TransitionConfig:
        row = self._conn.execute(
            "SELECT data_json FROM templates WHERE id=?", (template_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Template not found: {template_id}")
        data = json.loads(row["data_json"])
        trans = TransitionConfig(**data["transition"])
        trans.id = str(uuid.uuid4())
        trans.from_song_id = from_song_id
        trans.to_song_id = to_song_id
        return trans

    def update_track_mapping(self, mapping: list[TrackMappingEntry]) -> None:
        meta = ProjectMetadata(**json.loads(self.project_json.read_text(encoding="utf-8")))
        meta.track_mapping = mapping
        self.save(meta)

    def reorder_songs(self, song_ids: list[str]) -> None:
        meta = ProjectMetadata(**json.loads(self.project_json.read_text(encoding="utf-8")))
        by_id = {s["id"]: s for s in meta.songs}
        meta.songs = [by_id[sid] for sid in song_ids if sid in by_id]
        meta.transitions = [
            create_transition_config(meta.songs[i]["id"], meta.songs[i + 1]["id"])
            for i in range(len(meta.songs) - 1)
        ]
        self.save(meta)
        self._rebuild_timeline(meta)


# Active project registry for API
_active_projects: dict[str, ProjectStore] = {}


def open_project(bundle_path: Path | str) -> ProjectStore:
    store = ProjectStore(bundle_path)
    store.load()
    _active_projects[str(bundle_path)] = store
    return store


def create_project(bundle_path: Path | str, name: str, master_ppq: int = 480) -> ProjectStore:
    store = ProjectStore(bundle_path)
    store.create(name, master_ppq)
    _active_projects[str(bundle_path)] = store
    return store


def get_project(bundle_path: str) -> ProjectStore:
    if bundle_path not in _active_projects:
        return open_project(bundle_path)
    return _active_projects[bundle_path]
