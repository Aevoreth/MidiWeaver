# Operation reference

All edits are non-destructive **operations** stored as revisions in SQLite.

## Core ops

| op_type | Purpose |
|---------|---------|
| `trim_silence` | Trim leading/trailing silence per song |
| `set_transition_markers` | Mix in/out bars, transition duration |
| `tempo_ramp` | Master tempo ramp (`linear_ramp`, `exponential_ramp`, `step_at_boundary`, `hold_song1_then_ramp`) |
| `extend_drums` | Repeat last drum phrase (`repeat_last_phrase`, `repeat_with_fill`) |
| `copy_notes` | Copy note region to dest tick |
| `echo_notes` | Delayed copy |
| `manual_edit_note` | Piano roll move/resize/delete/draw/velocity |
| `transpose_region` | Semitone shift in bar range |
| `quantize_region` | Grid quantize (per-track opt-in by default) |
| `mute_track` | Mixer mute |
| `insert_song` | Reserved |
| `set_velocity_curve` | Reserved |

## AI output

AI returns an **OperationPlan** JSON (validated by Pydantic):

- `plan_summary`
- `tempo_options` (2–3 choices; user picks one)
- `ops[]` with per-op `enabled` toggles

AI never writes MIDI directly.

## Export

- **Merged MIDI**: SMF Type 1 (one track per master track)
- **Export report**: tempo ramps, unmapped tracks, key clashes
- **Audio**: WAV (always), OGG (requires ffmpeg/pydub)

## Defaults (open decisions)

- Quantize **off** globally; per-track opt-in
- Piano roll: move, resize, delete, draw, velocity
- Revision review: op-by-op toggles within a plan
