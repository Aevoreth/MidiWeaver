let engineUrlPromise: Promise<string> | null = null;

/** Resolve engine base URL: Vite env, Tauri sidecar command, or dev default. */
export async function getEngineUrl(): Promise<string> {
  if (engineUrlPromise) {
    return engineUrlPromise;
  }

  engineUrlPromise = (async () => {
    const fromEnv = import.meta.env.VITE_ENGINE_URL;
    if (fromEnv) {
      return fromEnv.replace(/\/$/, "");
    }

    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const url = await invoke<string>("get_engine_url");
      return url.replace(/\/$/, "");
    } catch {
      return "http://127.0.0.1:8765";
    }
  })();

  return engineUrlPromise;
}

/** Reset cached URL (tests only). */
export function resetEngineUrlCache(): void {
  engineUrlPromise = null;
}
