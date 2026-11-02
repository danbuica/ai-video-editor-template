import React from "react";
import { AbsoluteFill, Audio, CalculateMetadataFunction, Sequence, Series, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { SfxLib } from "./motion/MotionLayer";
import { sfxUrl } from "./motion/types";
import { loadEdl, projectFile } from "./lib/edl";
import { ACCENT_GRAD, fontFamily } from "./motion/theme";
import { buildChunks, Chunk, Cropped, EndCard, segStarts, shortMusicGain, ShortProps } from "./Short";
import { SHORTS } from "./shorts";

/**
 * Vertical short, "fast" style:
 * the layout changes every 1-2 s between three framings instead of one fixed screen-over-face frame:
 *   "full"  the visual alone, full-screen (1080x1920)          — proof moments
 *   "split" visual on top, face below, 50/50 (1080x960 each)  — explaining
 *   "face"  a full-screen punch-in on the speaker              — punchlines, CTA
 * One text element at a time: 1-3 word captions in a black pill (on the seam in split, lower third otherwise).
 * The short's content (shorts/index.ts) gives the shot list (cut-time ranges -> layout) and the visual for any box
 * size; `shots` in the props overrides the content's shot list.
 */

type Seg = { from: number; to: number };
type Word = { w: string; start: number; end: number; src_i: number };
export type Layout = "full" | "split" | "face";
export type Shot = { from: number; to: number; layout: Layout };
export type VisualProps = { t: number; project: string; words: Word[]; box: { w: number; h: number }; layout: Layout; variant?: "yt" | "ig" };

export type ShortV2Props = {
  project: string;
  segments: Seg[];
  content: string;
  shots?: Shot[];
  faceSplit?: { x: number; y: number; w: number };
  faceFull?: { x: number; y: number; w: number };
  audioSrc?: string;
  faceSrc?: string;
  endCard?: string;
  endSeconds?: number;
  fixes?: Record<string, string>;
  variant?: "yt" | "ig";
  music?: { file: string; lufs: number; gainDb?: number };
  sfx?: { name: string; w?: number; at?: number; pad?: number; vol?: number; hit?: boolean }[];
  sfxVolume?: number;
  words?: Word[];
  sfxLib?: SfxLib;
};

const W = 1080, H = 1920, HALF = 960;
export const calculateShortV2Metadata: CalculateMetadataFunction<ShortV2Props> = async ({ props }) => {
  // the project's own frame rate (its edit list), 25 if there is none
  const fps = await loadEdl(props.project).then((e) => e.fps_float, () => 25);
  const total = props.segments.reduce((s, g) => s + Math.round((g.to - g.from) * fps), 0);
  const words: Word[] = (await (await fetch(projectFile(props.project, "out/transcript_cut.json"))).json()).words;
  let sfxLib: SfxLib = {};
  if (props.sfx?.length) {
    const lib = await fetch(projectFile("_assets", "sfx/library.json"));
    if (lib.ok) sfxLib = await lib.json();
  }
  return { fps, width: W, height: H, durationInFrames: Math.max(1, total), props: { ...props, words, sfxLib } };
};

/* ---------------------------------------------------------------- captions: black pill, 1-3 words, current word in the accent */
const PillCaptions: React.FC<{ chunks: Chunk[]; y: number }> = ({ chunks, y }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const c = chunks.find((k) => t >= k.s - 0.04 && t < k.e);
  if (!c) return null;
  const pop = spring({ frame: f - Math.round(c.s * fps), fps, config: { damping: 13, stiffness: 260, mass: 0.5 } });
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: y, display: "flex", justifyContent: "center", transform: `translateY(-50%) scale(${0.86 + 0.14 * pop})` }}>
      <div style={{ display: "flex", gap: 18, padding: "16px 30px", borderRadius: 22, background: "rgba(8,9,12,0.92)", boxShadow: "0 12px 34px rgba(0,0,0,0.45)" }}>
        {c.words.map((w, i) => {
          const on = t >= w.s - 0.03 && t < (c.words[i + 1]?.s ?? c.e);
          const txt = w.text.replace(/[.,!?]$/, "").toUpperCase();
          return (
            <span key={i} style={{ position: "relative", fontFamily, fontWeight: 900, fontSize: 66, letterSpacing: "-0.01em", lineHeight: 1.05, color: on ? "transparent" : "#fff",
              background: on ? ACCENT_GRAD : undefined, WebkitBackgroundClip: on ? "text" : undefined, backgroundClip: on ? "text" : undefined }}>{txt}</span>
          );
        })}
      </div>
    </div>
  );
};

export const ShortV2: React.FC<ShortV2Props> = (p) => {
  const { fps, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const starts = segStarts(p.segments, fps);
  let k = 0;
  while (k + 1 < starts.length && f >= starts[k + 1]) k++;
  const cutT = p.segments[k].from + (f - starts[k]) / fps;
  const chunks = buildChunks(p as unknown as ShortProps, fps);
  const content = SHORTS[p.content] ?? SHORTS.example;
  const Visual = content.Visual;
  const list = p.shots ?? content.shots(p.variant);
  const shot = list.find((s) => cutT >= s.from && cutT < s.to) ?? list[list.length - 1];
  const faceSplit = p.faceSplit ?? { x: 0.29, y: 0.02, w: 0.42 };
  const faceFull = p.faceFull ?? { x: 0.352, y: 0, w: 0.3164 };
  const faceSrc = projectFile(p.project, p.faceSrc ?? "out/talking_cut.mp4");
  // punch-in: each face shot starts slightly pushed in and keeps pushing; alternate shots go tighter
  const faceIdx = list.filter((s) => s.layout === "face" && s.from <= shot.from).length;
  const prog = Math.min(1, (cutT - shot.from) / Math.max(0.5, shot.to - shot.from));
  const push = (faceIdx % 2 ? 1.06 : 1.0) + 0.04 * prog;
  return (
    <AbsoluteFill style={{ background: "#0b0c10" }}>
      <Series>
        {p.segments.map((g, i) => (
          <Series.Sequence key={i} durationInFrames={Math.round((g.to - g.from) * fps)}>
            {shot.layout === "face" ? (
              <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
                <div style={{ position: "absolute", inset: 0, transform: `scale(${push})`, transformOrigin: "50% 38%" }}>
                  <Cropped src={faceSrc} rect={faceFull} boxW={W} boxH={H} srcAR={16 / 9} startFrom={Math.round(g.from * fps)} />
                </div>
              </div>
            ) : shot.layout === "split" ? (
              <div style={{ position: "absolute", left: 0, top: HALF, width: W, height: HALF, overflow: "hidden" }}>
                <Cropped src={faceSrc} rect={faceSplit} boxW={W} boxH={HALF} srcAR={16 / 9} startFrom={Math.round(g.from * fps)} />
              </div>
            ) : null}
            {p.audioSrc ? <Audio src={projectFile(p.project, p.audioSrc)} startFrom={Math.round(g.from * fps)} /> : null}
          </Series.Sequence>
        ))}
      </Series>
      {shot.layout !== "face" ? (
        <div style={{ position: "absolute", left: 0, top: 0, width: W, height: shot.layout === "full" ? H : HALF, overflow: "hidden" }}>
          <Visual t={cutT} project={p.project} words={p.words ?? []} box={{ w: W, h: shot.layout === "full" ? H : HALF }} layout={shot.layout} variant={p.variant} />
        </div>
      ) : (
        <Visual t={cutT} project={p.project} words={p.words ?? []} box={{ w: W, h: H }} layout="face" variant={p.variant} />
      )}
      {shot.layout === "split" ? <div style={{ position: "absolute", left: 0, right: 0, top: HALF - 2, height: 4, background: "rgba(0,0,0,0.55)" }} /> : null}
      <PillCaptions chunks={chunks} y={shot.layout === "split" ? HALF : 1380} />
      {p.music ? <Audio src={staticFile(p.music.file)} volume={(fr) => shortMusicGain(fr / fps, durationInFrames / fps, chunks, p.music!.lufs, p.music!.gainDb ?? 0)} /> : null}
      {(p.sfx ?? []).map((x, i) => {
        const lib = p.sfxLib?.[x.name];
        if (!lib) return null;
        const cut = (x.w !== undefined ? (p.words ?? []).find((w) => w.src_i === x.w)?.start ?? -1 : x.at ?? -1) + (x.pad ?? 0);
        const seg = p.segments.findIndex((g) => cut >= g.from && cut < g.to);
        if (seg < 0) return null;
        const from = Math.round(starts[seg] + (cut - p.segments[seg].from - (x.hit ? lib.peak_at : 0)) * fps);
        return (
          <Sequence key={i} from={Math.max(0, from)} durationInFrames={Math.ceil(lib.duration * fps) + 2} layout="none">
            <Audio src={sfxUrl(x.name)} volume={(p.sfxVolume ?? 0.0627) * (x.vol ?? 1) * Math.pow(10, (lib.trim_db ?? 0) / 20)} />
          </Sequence>
        );
      })}
      {p.endCard ? <EndCard text={p.endCard} from={durationInFrames - Math.round((p.endSeconds ?? 3) * fps)} accent={ACCENT_GRAD} arrow={p.variant !== "ig"} top={1580} /> : null}
    </AbsoluteFill>
  );
};
