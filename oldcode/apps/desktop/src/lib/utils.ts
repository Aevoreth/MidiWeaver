import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function ticksToBar(tick: number, ppq: number, beatsPerBar = 4): number {
  return tick / (ppq * beatsPerBar);
}

export function barToTicks(bar: number, ppq: number, beatsPerBar = 4): number {
  return Math.round(bar * ppq * beatsPerBar);
}

export function snapTick(tick: number, ppq: number, snap: string): number {
  const grids: Record<string, number> = {
    bar: ppq * 4,
    beat: ppq,
    half: ppq / 2,
    quarter: ppq / 4,
    eighth: ppq / 8,
    sixteenth: ppq / 16,
    none: 1,
  };
  const grid = grids[snap] ?? ppq;
  if (grid <= 1) return tick;
  return Math.round(tick / grid) * grid;
}

export const MASTER_ROLES = ["Drums", "Bass", "Keys", "Melody", "Other"] as const;

const GM_INSTRUMENTS = [
  "Acoustic Grand", "Bright Grand", "Electric Grand", "Honky-tonk", "Electric Piano 1", "Electric Piano 2",
  "Harpsichord", "Clavinet", "Celesta", "Glockenspiel", "Music Box", "Vibraphone", "Marimba", "Xylophone",
  "Tubular Bells", "Dulcimer", "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ", "Reed Organ",
  "Accordion", "Harmonica", "Tango Accordion", "Nylon Guitar", "Steel Guitar", "Jazz Guitar", "Clean Guitar",
  "Muted Guitar", "Overdrive Guitar", "Distortion Guitar", "Guitar Harmonics", "Acoustic Bass", "Electric Bass (finger)",
  "Electric Bass (pick)", "Fretless Bass", "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2", "Violin",
  "Viola", "Cello", "Contrabass", "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
  "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2", "Choir Aahs", "Voice Oohs",
  "Synth Voice", "Orchestra Hit", "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn", "Brass Section",
  "Synth Brass 1", "Synth Brass 2", "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax", "Oboe", "English Horn",
  "Bassoon", "Clarinet", "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle", "Shakuhachi", "Whistle",
  "Ocarina", "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)", "Lead 4 (chiff)", "Lead 5 (charang)",
  "Lead 6 (voice)", "Lead 7 (fifths)", "Lead 8 (bass + lead)", "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)",
  "Pad 4 (choir)", "Pad 5 (bowed)", "Pad 6 (metallic)", "Pad 7 (halo)", "Pad 8 (sweep)", "FX 1 (rain)", "FX 2 (soundtrack)",
  "FX 3 (crystal)", "FX 4 (atmosphere)", "FX 5 (brightness)", "FX 6 (goblins)", "FX 7 (echoes)", "FX 8 (sci-fi)",
  "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bagpipe", "Fiddle", "Shanai", "Tinkle Bell", "Agogo", "Steel Drums",
  "Woodblock", "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal", "Guitar Fret Noise", "Breath Noise",
  "Seashore", "Bird Tweet", "Telephone Ring", "Helicopter", "Applause", "Gunshot",
] as const;

export function trackNumberFromId(trackId: string): number {
  const match = trackId.match(/track_(\d+)/i);
  return match ? Number.parseInt(match[1], 10) + 1 : 0;
}

export function mixerTrackId(songId: string, trackId: string): string {
  return `${songId}:${trackId}`;
}

export function instrumentLabel(track: {
  is_drum: boolean;
  program?: number;
  channel?: number;
}): string {
  if (track.is_drum) return "Drums";
  if (track.program != null && track.program >= 0 && track.program < GM_INSTRUMENTS.length) {
    return GM_INSTRUMENTS[track.program];
  }
  if (track.program != null) return `Program ${track.program}`;
  if (track.channel != null) return `Ch ${track.channel + 1}`;
  return "Unknown";
}
