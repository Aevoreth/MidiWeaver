# Advanced Note Handling and MIDI Snippet Protocol

## Goal

Support advanced note-aware AI interactions using compact musical snippets instead of generic style prompts.

The AI should receive targeted musical excerpts and return precise musical transformations.

---

# Summary vs Snippet Context

Summary context answers:

"What is this song like?"

Snippet context answers:

"What exactly is happening in these bars?"

Edit commands answer:

"What should MidiWeaver do to the MIDI?"

---

# Snippet Protocol

## Snippet Types

- drum groove snippet
- melody snippet
- bassline snippet
- chord/pad snippet
- transition snippet
- intro/outro candidate snippet
- user-selected region snippet

## Example Snippet

```json
{
  "snippet_id": "track_drums_bars_17_24",
  "bars": [17, 24],
  "timebase": {
    "ticks_per_beat": 480,
    "time_signature": "4/4",
    "bpm": 128
  },
  "tracks": [
    {
      "track_id": "track_drums",
      "track_name": "Drums",
      "channel": 10,
      "is_drum": true,
      "events": [
        {
          "event_id": "e001",
          "bar": 17,
          "beat": 1.0,
          "pitch": 36,
          "pitch_name": "Kick",
          "velocity": 92,
          "duration_beats": 0.125
        }
      ]
    }
  ]
}
```

---

# AI Inquiry Example

```json
{
  "command": "get_note_snippet",
  "args": {
    "track_id": "track_drums",
    "bars": [17, 24],
    "detail": "full_notes"
  }
}
```

---

# AI Edit Example

```json
{
  "command": "transform_snippet_to_region",
  "args": {
    "source_snippet_id": "track_drums_bars_17_24",
    "destination_bars": [1, 8],
    "transform_steps": [
      {
        "bars": [1, 2],
        "keep_pitches": [36, 38],
        "velocity_scale": 0.65,
        "density_scale": 0.35
      }
    ]
  }
}
```

---

# Design Principles

- AI should receive meaningful musical excerpts.
- AI should avoid vague style descriptions.
- AI should derive intros/outros/transitions from existing material.
- The engine validates all edits before applying them.
- Edits should be reversible and previewable.

---

# Supported Future Features

- motif preservation
- groove adaptation
- density ramps
- intelligent fills
- bassline continuation
- chord extension
- melodic phrase reuse
- transition generation
- cross-song motif blending
