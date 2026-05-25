"""MidiWeaver engine — MIDI analysis, editing, AI planning, and audio preview."""

from __future__ import annotations

import sys
import types

# Optional FluidSynth may be absent or broken on Windows dev machines.
if "fluidsynth" not in sys.modules:
    try:
        import fluidsynth  # noqa: F401
    except Exception:
        _stub = types.ModuleType("fluidsynth")

        class _Synth:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

            def sfload(self, *args, **kwargs):
                return 0

            def program_select(self, *args, **kwargs):
                pass

            def delete(self):
                pass

        _stub.Synth = _Synth
        sys.modules["fluidsynth"] = _stub

__version__ = "0.1.0"
