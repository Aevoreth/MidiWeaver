import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button, Input, Label, Panel } from "@/components/ui/button";

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o-mini");
  const [backend, setBackend] = useState("system_midi");
  const [soundfont, setSoundfont] = useState("");
  const [ollamaStatus, setOllamaStatus] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setBaseUrl(String(s.ai_base_url ?? baseUrl));
      setModel(String(s.ai_model ?? model));
      setBackend(String(s.audio_backend ?? backend));
      setSoundfont(String(s.soundfont_path ?? ""));
    });
    api.ollamaStatus().then((s) => setOllamaStatus(s.message));
  }, []);

  const save = async () => {
    await api.updateSettings({
      ai_base_url: baseUrl,
      ai_api_key: apiKey || undefined,
      ai_model: model,
      audio_backend: backend,
      soundfont_path: soundfont || undefined,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <Panel className="w-full max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">Settings</h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        <div className="space-y-2">
          <Label>AI base URL (OpenAI-compatible)</Label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          <Label>API key</Label>
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          <Label>Model</Label>
          <Input value={model} onChange={(e) => setModel(e.target.value)} />
          <p className="text-xs text-muted">Ollama: {ollamaStatus}</p>
        </div>

        <div className="space-y-2">
          <Label>Audio backend</Label>
          <select
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
            value={backend}
            onChange={(e) => setBackend(e.target.value)}
          >
            <option value="system_midi">System MIDI (default)</option>
            <option value="fluidsynth">FluidSynth (SF2/SF3)</option>
          </select>
          <Label>Soundfont path</Label>
          <Input value={soundfont} onChange={(e) => setSoundfont(e.target.value)} placeholder="C:\SoundFonts\font.sf2" />
        </div>

        <Button className="w-full" onClick={save}>
          {saved ? "Saved!" : "Save settings"}
        </Button>
      </Panel>
    </div>
  );
}
