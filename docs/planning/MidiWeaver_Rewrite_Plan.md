# MidiWeaver 2 Rewrite Plan

## Goal

Rebuild MidiWeaver from scratch as a lightweight, open-source desktop app for AI-assisted MIDI analysis, editing, merging, intro/outro generation, and transition building.

The app should not expect the AI model to directly edit MIDI files. Instead, the app will expose a controlled command protocol that allows the AI to inspect MIDI structure, request additional analysis, and return precise edit instructions. The local MIDI engine will validate and execute those instructions.

---

# Recommended Architecture

## Frontend

Use:

- Tauri
- TypeScript
- React or Svelte
- Canvas/WebGL-based piano roll rendering

The frontend should handle:

- MIDI timeline display
- Track list
- Mini piano roll per track
- Main piano roll view
- Pan and zoom
- Solo/mute controls
- Track name display
- Playback controls
- AI chat/instruction panel
- Before/after preview workflow

## Backend / Engine

Use a Python sidecar engine.

Python should handle:

- MIDI parsing
- MIDI analysis
- MIDI editing
- MIDI validation
- MIDI export
- AI command execution
- Preview rendering support

Suggested Python libraries:

- mido
- pretty_midi
- music21
- jsonschema or pydantic
- fluidsynth integration for playback/rendering

---

# Core Concept: AI Command Protocol

The AI should communicate with MidiWeaver through a structured command protocol.

The AI should not receive raw MIDI files directly unless explicitly supported later. Instead, the Python engine should summarize the MIDI into compact, musical data that the AI can understand.

The AI can then request more information or propose edits.

## Two Command Layers

### Inquiry Commands

- inspect_tracks
- inspect_bars
- find_repeating_patterns
- analyze_drum_groove
- analyze_velocity_profile
- analyze_phrase_boundaries
- analyze_tempo_map
- compare_sections

### Edit Commands

- insert_notes
- delete_notes
- copy_pattern
- copy_pattern_transform
- thin_pattern
- scale_velocity
- humanize_timing
- create_tempo_ramp
- merge_midis
- trim_silence
- derive_intro_from_pattern
- derive_outro_from_pattern
- build_transition

---

# Important Design Rule

Do not make the AI guess generic styles.

The AI should derive new material from patterns already present in the MIDI.

---

# Agent Loop

User prompt
→ App creates MIDI summary
→ App sends summary + command protocol to AI
→ AI requests more analysis or proposes edits
→ Python engine executes commands
→ App renders preview
→ User accepts/rejects
→ Final MIDI exported

---

# First Milestone

1. Open MIDI file
2. Parse with Python
3. Generate MIDI summary
4. Display tracks in UI
5. Add piano roll
6. Add AI chat panel
7. Validate commands
8. Execute safe edits
9. Export edited MIDI
