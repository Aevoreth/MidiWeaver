# MidiWeaver

Windows-first desktop app for chaining MIDI songs, planning transitions with AI, and exporting merged sets — all **non-destructively** via `.midiweaver/` project bundles.

## Stack

| Layer | Tech |
|-------|------|
| UI | Tauri 2 + React + TypeScript + Tailwind (dark theme) |
| Engine | Python 3.12+ FastAPI sidecar |
| MIDI | mido, pretty_midi, music21 |
| State | SQLite revisions + immutable source copies |

## Quick start

```powershell
# Engine
cd apps\engine
python -m pip install -e ".[dev]"
python -m uvicorn midiweaver.main:app --reload --port 8765

# UI (new terminal)
cd apps\desktop
npm install
npm run dev
```

See [docs/dev-setup.md](docs/dev-setup.md) for full prerequisites (Rust, VS Build Tools, SoundFont path).

## Features (MVP)

- Import & chain multiple MIDI songs on a **master timeline**
- Auto **analysis** (BPM, key, trim points, track summaries)
- **Track mapping** across songs (Drums/Bass/Keys/Melody/Other)
- **Transition regions** with mix in/out markers
- **Piano roll** editing: move, resize, delete, draw, velocity
- Flexible **snap** (bar/beat/subdivision/off)
- **AI planner** (mock offline; OpenAI-compatible when configured)
- Tempo option picker + **op-by-op** plan review
- **Undo/redo** with before/after diff
- **Templates** for transition configs
- Preview transport with **mute/solo/volume**
- Export merged **Type 1 MIDI** + WAV/OGG render

## Tests

```powershell
cd apps\engine && python -m pytest tests -v
```

## Sample projects

Generate fixtures:

```powershell
cd apps\engine
python -c "from tests.conftest import write_simple_midi; from pathlib import Path; p=Path('../../sample-projects/fixtures'); write_simple_midi(p/'song_a.mid',120); write_simple_midi(p/'song_b.mid',140)"
```

Create a project in the UI (New → import `sample-projects/fixtures/song_a.mid` and `song_b.mid`).

## Known limitations

- **Rust not required** for web dev mode; Tauri desktop build needs Rust + VS Build Tools
- **Ollama** is settings stub only in v1
- **FluidSynth** optional; broken pip `fluidsynth` wheels are stubbed automatically
- **OGG export** needs ffmpeg if pydub is installed
- Sidecar PyInstaller binary not bundled in repo — run engine via uvicorn in dev
- Piano roll virtualizes visible range only; very large sets may need performance tuning

## License

MIT (placeholder — adjust as needed)
