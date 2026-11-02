import { staticFile } from "remotion";

/**
 * projects/<name>/out/motion.json — the approved motion plan. Times are anchored to WORDS
 * ({ w: <source word index>, pad?: seconds }) so graphics stay put when the cut changes.
 * A plain number means seconds on the cut timeline.
 */
export type TimeRef = number | { w: number; pad?: number; end?: boolean };

/** a sound effect from projects/_assets/sfx (name = file name without extension); hit: land the sound's peak on `at` */
export type SfxRef = { name: string; at: TimeRef; vol?: number; hit?: boolean };

type Base = {
  id: string;
  from: TimeRef;
  to: TimeRef;
  side?: "left" | "right" | "center";
  /** switch the layout to full-screen talking head for this item (extra full-screen moment) */
  fullscreen?: boolean;
  /** full-frame scene that keeps the face card on the right (the scene draws in the left ~72%) */
  card?: boolean;
  sfx?: SfxRef[];
  note?: string;
};

/**
 * One graphic on the timeline. `type` picks the component in motion/graphics/index.ts; every other field is that
 * graphic's own data (any TimeRef inside it is resolved to seconds before the component sees it).
 * Types starting with "scene-" are full-frame scenes: the talking head goes full screen and is blurred underneath.
 */
export type MotionItem = Base & { type: string; [field: string]: unknown };

export const isScene = (it: { type: string }) => it.type.startsWith("scene-");

export type Chapter = { at: TimeRef; number: number; title: string; sub?: string };

export type MotionPlan = {
  items: MotionItem[];
  chapters?: Chapter[];
  chapterSeconds?: number;
  /** chapter card style: a key of CHAPTER_CARDS in motion/chapters.tsx */
  chapterStyle?: string;
  /** sound effect played on every chapter card (from 0.6 s into the sound), e.g. "whoosh" */
  chapterSfx?: string;
  music?: { file: string; lufs: number; gainDb?: number; label?: string };
  voiceGain?: number;
  sfxVolume?: number;
};

export type CutWord = { w: string; start: number; end: number; src_i: number };

/** Resolve every TimeRef in the plan to seconds on the cut timeline. */
export const resolvePlan = (plan: MotionPlan, words: CutWord[]): MotionPlan => {
  const bySrc = new Map(words.map((w) => [w.src_i, w]));
  const nearest = (src: number) => {
    if (bySrc.has(src)) return bySrc.get(src)!;
    // word was cut: use the next kept word
    const after = words.find((w) => w.src_i > src);
    return after ?? words[words.length - 1];
  };
  const t = (r: TimeRef): number => {
    if (typeof r === "number") return r;
    const w = nearest(r.w);
    return (r.end ? w.end : w.start) + (r.pad ?? 0);
  };
  const walk = (v: unknown): unknown => {
    // a box {x, y, w, h} also has a numeric `w`: it is not a word anchor
    if (v && typeof v === "object" && !Array.isArray(v) && "w" in (v as object) && typeof (v as { w: unknown }).w === "number" && !("h" in (v as object)))
      return t(v as TimeRef);
    if (Array.isArray(v)) return v.map((x) => walk(x));
    if (v && typeof v === "object") {
      const o: Record<string, unknown> = {};
      for (const [k, x] of Object.entries(v)) o[k] = walk(x);
      return o;
    }
    return v;
  };
  return walk(plan) as MotionPlan;
};

export const sfxUrl = (name: string) => staticFile(`_assets/sfx/${name}.wav`);
