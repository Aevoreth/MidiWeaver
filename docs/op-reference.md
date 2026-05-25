# Operation reference

All edits are non-destructive **operations** stored as revisions in SQLite.

## Core ops

| op_type | Purpose |
|---------|---------|
| `trim_silence` | Trim leading/trailing silence per song |
| `set_transition_markers` | Mix in/out bars, transition duration |
| `tempo_ramp` | Master tempo ramp (`linear_ramp`, `exponential_ramp`, `step_at_boundary`, `hold_song1_then_ramp`) |
| `extend_drums` | Repeat last drum phrase (`repeat_last_phrase`, `repeat_with_fill`) |
| `insert_master_gap` | Insert positive space on master timeline before the next song |
| `loop_region` | Copy a bar range forward (repeat_count or target_total_bars) |
| `delete_notes_in_region` | Remove notes in a master tick window (optional pitch/drum filters) |
| `copy_notes` | Copy note region to dest tick |
| `echo_notes` | Delayed copy |
| `manual_edit_note` | Piano roll move/resize/delete/draw/velocity |
| `transpose_region` | Semitone shift in bar range |
| `quantize_region` | Grid quantize (per-track opt-in by default) |
| `mute_track` | Mixer mute |
| `insert_song` | Reserved |
| `set_velocity_curve` | Reserved |

## AI output

AI supports three modes:

- **Ask** — read-only inspect tools; answers questions about the project
- **Plan** — returns an **ArrangementPlan** (`plan_summary`, `steps[]`, `tempo_options`)
- **Agent** — tool-calling loop; each `apply_op` commits one revision

Legacy **OperationPlan** JSON (ops array) remains available for validate/apply-plan endpoints.

ArrangementPlan fields:

- `plan_summary`
- `steps[]` with `description`, `intent`, `suggested_tool`, `suggested_params`, `verify`
- `tempo_options` (2–3 choices)

AI never writes MIDI directly.

## Export

- **Merged MIDI**: SMF Type 1 (one track per master track)
- **Export report**: tempo ramps, unmapped tracks, key clashes
- **Audio**: WAV (always), OGG (requires ffmpeg/pydub)

## Defaults (open decisions)

- Quantize **off** globally; per-track opt-in
- Piano roll: move, resize, delete, draw, velocity
- Revision review: op-by-op toggles within a plan
