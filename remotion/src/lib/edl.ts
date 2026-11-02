import { staticFile } from "remotion";

// Mirrors pipeline/vcut/edl.py output (projects/<name>/out/edl.json)
export type Join = {
  kind: string; // head | tail | pause | mid_sentence | retake | restart | backtrack | stutter | filler | marker | manual
  out_frame: number;
  out_s: number;
  removed_s: number;
  mid_sentence?: boolean;
  tight?: boolean;
  cut_text?: string;
  text_before?: string;
  text_after?: string;
};

export type Edl = {
  fps: string;
  fps_float: number;
  out_frames: number;
  out_s: number;
  source_s: number;
  segments: { src_start: number; src_end: number; out_start: number }[];
  joins: Join[];
};

export type CutWord = { w: string; start: number; end: number; src_i: number };

export const projectFile = (project: string, path: string) => staticFile(`${project}/${path}`);

export const loadEdl = async (project: string): Promise<Edl> => {
  const res = await fetch(projectFile(project, "out/edl.json"));
  if (!res.ok) throw new Error(`No edl.json for project "${project}". Run the /cut pipeline first.`);
  return res.json();
};

export const loadWords = async (project: string): Promise<CutWord[]> => {
  const res = await fetch(projectFile(project, "out/transcript_cut.json"));
  if (!res.ok) return [];
  return (await res.json()).words;
};
