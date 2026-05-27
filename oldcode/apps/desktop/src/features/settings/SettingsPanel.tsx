import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button, Input, Label, Panel } from "@/components/ui/button";

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [apiKey, setApiKey] = useState("");
  const [apiKeyConfigured, setApiKeyConfigured] = useState(false);
  const [model, setModel] = useState("gpt-4o-mini");
  const [backend, setBackend] = useState("system_midi");
  const [soundfont, setSoundfont] = useState("");
  const [ollamaStatus, setOllamaStatus] = useState("");
  const [saved, setSaved] = useState(false);
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setBaseUrl(String(s.ai_base_url ?? baseUrl));
      setModel(String(s.ai_model ?? model));
      setBackend(String(s.audio_backend ?? backend));
      setSoundfont(String(s.soundfont_path ?? ""));
      setApiKeyConfigured(Boolean(s.ai_api_key_configured));
    });
    api.ollamaStatus().then((s) => setOllamaStatus(s.message));
  }, []);

  const save = async () => {
    const body: Record<string, unknown> = {
      ai_base_url: baseUrl,
      ai_model: model,
      audio_backend: backend,
      soundfont_path: soundfont || undefined,
    };
    if (apiKey.trim()) {
      body.ai_api_key = apiKey.trim();
    }
    const updated = await api.updateSettings(body);
    setApiKeyConfigured(Boolean(updated.ai_api_key_configured));
    setApiKey("");
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const clearKey = async () => {
    const updated = await api.updateSettings({ clear_ai_api_key: true });
    setApiKeyConfigured(Boolean(updated.ai_api_key_configured));
    setApiKey("");
    setTestStatus(null);
  };

  const testConnection = async () => {
    setTesting(true);
    setTestStatus(null);
    try {
      if (apiKey.trim()) {
        await api.updateSettings({ ai_api_key: apiKey.trim(), ai_base_url: baseUrl, ai_model: model });
      }
      const result = await api.testAiConnection();
      if (result.ok) {
        setApiKeyConfigured(true);
        setApiKey("");
        setTestStatus(result.message ?? "Connection successful");
      } else {
        setTestStatus(result.error ?? "Connection failed");
      }
    } catch (e) {
      setTestStatus(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setTesting(false);
    }
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
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted">AI mode</span>
            <span className={apiKeyConfigured ? "text-accent" : "text-muted"}>
              {apiKeyConfigured ? "Live (API key configured)" : "Mock (no API key)"}
            </span>
          </div>
          <Label>AI base URL (OpenAI-compatible)</Label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          <Label>API key</Label>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={apiKeyConfigured ? "Key configured — enter new key to replace" : "sk-…"}
          />
          {apiKeyConfigured && (
            <Button variant="ghost" size="sm" onClick={clearKey}>
              Clear API key
            </Button>
          )}
          <Label>Model</Label>
          <Input value={model} onChange={(e) => setModel(e.target.value)} />
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={testConnection} disabled={testing}>
              {testing ? "Testing…" : "Test connection"}
            </Button>
          </div>
          {testStatus && (
            <p className={`text-xs ${testStatus.includes("successful") ? "text-accent" : "text-error"}`}>
              {testStatus}
            </p>
          )}
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
