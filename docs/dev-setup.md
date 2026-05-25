# MidiWeaver dev setup

## Prerequisites (Windows)

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | 20+ | For React UI |
| Python | 3.12+ | Engine sidecar |
| Rust | stable | Tauri desktop shell |
| VS Build Tools | C++ workload | Required by Tauri |

Optional:

- **FluidSynth** on PATH for SF2 preview/render
- **ffmpeg** for OGG export via pydub

MIDI preview requires **python-rtmidi** (installed automatically with the engine). If Play shows a MIDI error, reinstall:

```powershell
cd apps\engine
python -m pip install -e ".[dev]"
```

## First-time setup

```powershell
cd C:\dev\MidiWeaver

# Install JS workspace deps
npm install

# Install Python engine (editable)
cd apps\engine
python -m pip install -e ".[dev]"
cd ..\..

# Generate sample MIDI fixtures
cd apps\engine
python -c "from tests.conftest import write_simple_midi; from pathlib import Path; p=Path('../../sample-projects/fixtures'); write_simple_midi(p/'song_a.mid',120); write_simple_midi(p/'song_b.mid',140); print('fixtures ok')"
```

## Daily dev loop

**Terminal A — engine**

```powershell
cd apps\engine
python -m uvicorn midiweaver.main:app --reload --port 8765
```

**Terminal B — UI**

```powershell
cd apps\desktop
npm run dev
```

Open http://localhost:1420 (browser) or, with Rust installed:

```powershell
npm run tauri dev
```

The UI talks to `http://127.0.0.1:8765` by default (`VITE_ENGINE_URL`).

## SoundFont setup (Q4 default)

MidiWeaver does **not** bundle large SF2 binaries. For FluidSynth preview:

1. Download a royalty-free font such as [GeneralUser GS](https://schristiancollins.com/generaluser.php)
2. Settings → Audio → set **SoundFont path** to your `.sf2` file
3. Switch backend to **FluidSynth**

System MIDI (Microsoft GS Wavetable) works without a soundfont.

## AI settings

MidiWeaver stores AI credentials in a local engine config file (not in `.midiweaver/` project bundles):

- **Windows:** `%APPDATA%\MidiWeaver\settings.json`
- **macOS/Linux:** XDG config dir via `platformdirs` (typically `~/.config/MidiWeaver/settings.json`)

### Configure live AI

1. Start the engine and UI (see Daily dev loop above).
2. Open **Settings** → set **AI base URL**, **API key**, and **model** (OpenAI-compatible API).
3. Click **Test connection** to verify credentials.
4. In the **AI** sidebar tab, click **Generate plan** — live plans run when a key is configured.

Without an API key, the planner uses deterministic mock plans (same offline behavior as tests).

### Dev overrides

| Variable | Purpose |
|----------|---------|
| `MIDIWEAVER_AI_API_KEY` | Set API key on engine startup (overrides saved key) |
| `VITE_AI_MOCK=true` | Force mock plans in the UI even when a key is configured |

- **Ollama**: stub only in v1 (`/api/ollama/status`).

## Tests

```powershell
cd apps\engine
python -m pytest tests -v
```

```powershell
cd apps\desktop
npm run lint
```

## Project bundle layout

```
MySet.midiweaver/
  project.json
  project.db
  sources/       # immutable imported MIDIs
  exports/
  previews/
```

## Sidecar lifecycle (production)

Tauri resolves the engine URL via the `get_engine_url` command:

- **Dev / debug builds:** UI connects to `http://127.0.0.1:8765` (start uvicorn separately, or use `npm run dev:engine` from repo root).
- **Release builds:** Tauri spawns `midiweaver-engine` from `src-tauri/binaries/` (PyInstaller build — see `binaries/README.md`), waits for the port, and exposes the URL to React.

Override anytime with `VITE_ENGINE_URL` when running the Vite dev server in a browser.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `fluidsynth` import error on Windows | Harmless in dev; engine stubs missing FluidSynth. Install FluidSynth or ignore if using system MIDI. |
| Engine offline in UI | Start uvicorn on port 8765 |
| Play does nothing / MIDI error | Reinstall engine deps: `pip install -e "./apps/engine[dev]"` (needs **python-rtmidi**) |
| White flash on load | `index.html` applies `dark` class before paint; Tauri window theme is Dark |
