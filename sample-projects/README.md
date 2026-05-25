Sample MIDI fixtures for MidiWeaver. Generate with:

```powershell
cd apps\engine
python -c "from tests.conftest import write_simple_midi; from pathlib import Path; p=Path('../../sample-projects/fixtures'); write_simple_midi(p/'song_a.mid',120); write_simple_midi(p/'song_b.mid',140); write_simple_midi(p/'song_c.mid',100)"
```

Import these via the UI to build a 2–3 song chain demo.
