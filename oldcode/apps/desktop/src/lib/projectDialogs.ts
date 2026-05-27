import { isTauri } from "@tauri-apps/api/core";

export const PROJECTS_FOLDER_NAME = "MidiWeaver";
export const PROJECT_EXTENSION = ".midiweaver";

export async function getDefaultProjectsDir(): Promise<string> {
  if (!isTauri()) return PROJECTS_FOLDER_NAME;
  const { documentDir, join } = await import("@tauri-apps/api/path");
  return join(await documentDir(), PROJECTS_FOLDER_NAME);
}

export function projectNameFromPath(path: string): string {
  const base = path.replace(/[/\\]+$/, "").split(/[/\\]/).pop() ?? "Untitled";
  return base.endsWith(PROJECT_EXTENSION) ? base.slice(0, -PROJECT_EXTENSION.length) : base;
}

export async function pickProjectFolder(): Promise<string | null> {
  if (!isTauri()) {
    const path = prompt("Open .midiweaver project folder");
    return path?.trim() || null;
  }

  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    title: "Open Project",
    directory: true,
    multiple: false,
    defaultPath: await getDefaultProjectsDir(),
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickNewProjectPath(defaultName = "My Setlist"): Promise<string | null> {
  if (!isTauri()) {
    const name = prompt("Project name", defaultName);
    if (!name?.trim()) return null;
    const path = prompt("Project folder", `${name.trim()}${PROJECT_EXTENSION}`);
    return path?.trim() || null;
  }

  const { save } = await import("@tauri-apps/plugin-dialog");
  const { join } = await import("@tauri-apps/api/path");
  const defaultPath = await join(
    await getDefaultProjectsDir(),
    `${defaultName}${PROJECT_EXTENSION}`,
  );
  const selected = await save({
    title: "Create Project",
    defaultPath,
    filters: [{ name: "MidiWeaver Project", extensions: ["midiweaver"] }],
  });
  return selected || null;
}

export async function pickExportPath(defaultName = "export.mid"): Promise<string | null> {
  if (!isTauri()) {
    const path = prompt("Export path", defaultName);
    return path?.trim() || null;
  }

  const { save } = await import("@tauri-apps/plugin-dialog");
  const { join } = await import("@tauri-apps/api/path");
  const defaultPath = await join(await getDefaultProjectsDir(), defaultName);
  return (
    (await save({
      title: "Export MIDI",
      defaultPath,
      filters: [{ name: "MIDI File", extensions: ["mid", "midi"] }],
    })) || null
  );
}
