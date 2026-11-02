import React from "react";
import { AbsoluteFill, Audio, CalculateMetadataFunction, Img, interpolate, OffthreadVideo, Sequence, Series, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { SfxLib } from "./motion/MotionLayer";
import { sfxUrl } from "./motion/types";
import { loadEdl, projectFile } from "./lib/edl";
import { ACCENT, ACCENT2, ACCENT_GRAD, ACCENT_RGB, fontFamily } from "./motion/theme";

/**
 * Vertical short (1080x1920), two panels, cut from a finished long-form project using ONLY lines already said.
 *  - segments: ranges on the cut timeline (seconds) played back to back
 *  - top: the visual (a crop of the 16:9 video: the screen, phones, drawn scenes), 1080x1080
 *  - bottom: the speaker's face from the clean camera cut, 1080x840
 *  - word-by-word captions at the seam, the current word in the accent colour
 *  - an end card ("Full build ↓") over the last seconds: the YouTube related-video link does the sending
 * Spec files live in projects/<name>/shorts/<id>.json (see .claude/skills/shorts/SKILL.md).
 */

type Seg = { from: number; to: number };
type TopMode = { from: number; to: number; mode: "crop" | "fit"; x?: number; y?: number; w?: number };
type Word = { w: string; start: number; end: number; src_i: number };

export type ShortProps = {
  project: string;
  segments: Seg[];
  /** top-panel framing per cut-time range; default: square crop of the left 1080 px */
  top?: TopMode[];
  /** face crop of the camera (fractions; height follows the 1080:840 panel) */
  face?: { x: number; y: number; w: number };
  /** 16:9 source for the top panel (project path), default the cut screen recording; e.g. "out/<name>_final_4k.mp4" */
  topSrc?: string;
  /** a still instead of video for the top panel (accent previews) */
  topImage?: string;
  audioSrc?: string;
  faceSrc?: string;
  endCard?: string;
  endSeconds?: number;
  /** where the end card sits (px from the top); default 1500, just under the chin. Above 1080 = in the top panel */
  endCardTop?: number;
  /** ASR spelling fixes for the captions, e.g. {"Cloud": "Claude"}; "#<src_i>" fixes one word */
  fixes?: Record<string, string>;
  accent?: string;
  /** cut-time ranges shown as a full-screen talking head (1080x1920) instead of the two panels, e.g. the hook */
  full?: Seg[];
  /** camera crop for the full-screen face (fractions; height follows 1080:1920) */
  fullFace?: { x: number; y: number; w: number };
  /** a title over the full-screen face; words wrapped in *stars* get the accent */
  fullTitle?: string;
  /** "ig" = Instagram/TikTok ending (comment keyword, no related-video arrow), "yt" = YouTube (default) */
  variant?: "yt" | "ig";
  /** background music under the voice (staticFile path under projects/), ducked while the speaker talks */
  music?: { file: string; lufs: number; gainDb?: number };
  /** sound effects: `w` = source word index (or `at` = cut-time seconds) + `pad`; `hit` lands the sound's peak on the cue */
  sfx?: { name: string; w?: number; at?: number; pad?: number; vol?: number; hit?: boolean }[];
  sfxVolume?: number;
  words?: Word[];
  sfxLib?: SfxLib;
};

const W = 1080;
const TOP_H = 1080;
const FACE_H = 840;

export const calculateShortMetadata: CalculateMetadataFunction<ShortProps> = async ({ props }) => {
  // the project's own frame rate (its edit list), 25 if there is none
  const fps = await loadEdl(props.project).then((e) => e.fps_float, () => 25);
  const total = props.segments.reduce((s, g) => s + Math.round((g.to - g.from) * fps), 0);
  const words: Word[] = (await (await fetch(projectFile(props.project, "out/transcript_cut.json"))).json()).words;
  let sfxLib: SfxLib = {};
  if (props.sfx?.length) {
    const lib = await fetch(projectFile("_assets", "sfx/library.json"));
    if (lib.ok) sfxLib = await lib.json();
  }
  return { fps, width: W, height: TOP_H + FACE_H, durationInFrames: Math.max(1, total), props: { ...props, words, sfxLib } };
};

/** short-time ↔ cut-time */
export const segStarts = (segs: Seg[], fps: number) => {
  let acc = 0;
  return segs.map((g) => {
    const s = acc;
    acc += Math.round((g.to - g.from) * fps);
    return s;
  });
};

export const Cropped: React.FC<{ src: string; image?: boolean; rect: { x: number; y: number; w: number }; boxW: number; boxH: number; srcAR: number; muted?: boolean; startFrom?: number }> = ({ src, image, rect, boxW, boxH, srcAR, muted = true, startFrom }) => {
  const vw = boxW / rect.w;
  const vh = vw / srcAR;
  const style: React.CSSProperties = { position: "absolute", left: -rect.x * vw, top: -rect.y * vh, width: vw, height: vh };
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      {image ? <Img src={src} style={style} /> : <OffthreadVideo src={src} muted={muted} startFrom={startFrom} style={style} />}
    </div>
  );
};

const TopPanel: React.FC<{ p: ShortProps; cutT: number; startFrom: number; segFrom: number }> = ({ p, cutT, startFrom, segFrom }) => {
  const mode = (p.top ?? []).find((m) => cutT >= m.from && cutT < m.to) ?? { from: 0, to: 0, mode: "crop" as const };
  const src = p.topImage ? projectFile(p.project, p.topImage) : projectFile(p.project, p.topSrc ?? "out/screen_cut.mp4");
  if (mode.mode === "fit") {
    const h = (W * 9) / 16;
    return (
      <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 40%, #23242d 0%, #0d0e13 75%)" }}>
        <div style={{ position: "absolute", left: 0, top: (TOP_H - h) / 2, width: W, height: h, overflow: "hidden" }}>
          {p.topImage ? <Img src={src} style={{ width: W, height: h }} /> : <OffthreadVideo src={src} muted startFrom={startFrom} style={{ width: W, height: h }} />}
        </div>
      </AbsoluteFill>
    );
  }
  const w = mode.w ?? 0.5625;
  return <Cropped src={src} image={!!p.topImage} rect={{ x: mode.x ?? 0, y: mode.y ?? 0, w }} boxW={W} boxH={TOP_H} srcAR={16 / 9} startFrom={startFrom} />;
};

/* ---------------------------------------------------------------- captions */
export type Chunk = { words: { text: string; s: number; e: number }[]; s: number; e: number };

export const buildChunks = (p: ShortProps, fps: number): Chunk[] => {
  const starts = segStarts(p.segments, fps);
  const out: Chunk[] = [];
  p.segments.forEach((g, k) => {
    const off = starts[k] / fps - g.from;
    const ws = (p.words ?? []).filter((w) => w.start >= g.from - 0.05 && w.end <= g.to + 0.1);
    let cur: Chunk | null = null;
    ws.forEach((w, i) => {
      // fixes: "#<src_i>" fixes one word, a plain key fixes every occurrence
      const text = (p.fixes ?? {})[`#${w.src_i}`] ?? (p.fixes ?? {})[w.w] ?? w.w;
      const s = w.start + off, e = w.end + off;
      const prev = ws[i - 1];
      const prevText = prev ? ((p.fixes ?? {})[`#${prev.src_i}`] ?? (p.fixes ?? {})[prev.w] ?? prev.w) : "";
      const brk = !cur || cur.words.length >= 3 || /[.,?!—]$/.test(prevText) || (prev && w.start - prev.end > 0.35);
      if (brk) {
        cur = { words: [], s, e };
        out.push(cur);
      }
      cur!.words.push({ text, s, e });
      cur!.e = e;
    });
  });
  // each chunk stays up until the next one starts
  out.forEach((c, i) => { if (out[i + 1]) c.e = Math.max(c.e, Math.min(out[i + 1].s, c.e + 0.6)); else c.e += 0.4; });
  return out;
};

const capStyle: React.CSSProperties = { fontFamily, fontWeight: 900, fontSize: 82, letterSpacing: "-0.02em", lineHeight: 1.05 };

const Captions: React.FC<{ chunks: Chunk[]; accent: string; top?: number }> = ({ chunks, accent, top = TOP_H - 70 }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const c = chunks.find((k) => t >= k.s - 0.04 && t < k.e);
  if (!c) return null;
  const pop = spring({ frame: f - Math.round(c.s * fps), fps, config: { damping: 14, stiffness: 220, mass: 0.6 } });
  return (
    <div style={{ position: "absolute", left: 40, right: 40, top, display: "flex", justifyContent: "center", flexWrap: "wrap", gap: "0 30px", transform: `scale(${0.9 + 0.1 * pop})` }}>
      {c.words.map((w, i) => {
        const on = t >= w.s - 0.03 && t < (c.words[i + 1]?.s ?? c.e);
        return (
          <span key={i} style={{ position: "relative", display: "inline-block", transform: `scale(${on ? 1.08 : 1})` }}>
            <span style={{ ...capStyle, color: on ? "#000" : "#fff", WebkitTextStroke: "10px #000", paintOrder: "stroke fill", textShadow: "0 6px 18px rgba(0,0,0,0.55)" }}>{w.text.replace(/[.,]$/, "")}</span>
            {on ? <span style={{ ...capStyle, position: "absolute", left: 0, top: 0, background: accent, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>{w.text.replace(/[.,]$/, "")}</span> : null}
          </span>
        );
      })}
    </div>
  );
};

/** The pointer to the full video. On YouTube Shorts the related-video link sits bottom-left, just above the
 *  channel name, so the overlay sits low on the frame and an arrow bounces down-left toward that link. */
export const EndCard: React.FC<{ text: string; from: number; accent: string; arrow?: boolean; top?: number }> = ({ text, from, accent, arrow = true, top = 1500 }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (f < from) return null;
  const p = spring({ frame: f - from, fps, config: { damping: 14, stiffness: 150 } });
  const t = (f - from) / fps;
  const bob = Math.sin(t * 7) * 14;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{ position: "absolute", left: 0, right: 0, top, display: "flex", justifyContent: "center", opacity: Math.min(1, p * 1.5), transform: `translateY(${interpolate(p, [0, 1], [60, 0])}px) scale(${0.85 + 0.15 * p})` }}>
        <div style={{ padding: "26px 46px", borderRadius: 999, background: accent, color: "#06111c", fontFamily, fontWeight: 900, fontSize: 60, letterSpacing: "-0.02em", boxShadow: `0 0 60px rgba(${ACCENT_RGB},0.45), 0 20px 50px rgba(0,0,0,0.55)`, whiteSpace: "nowrap" }}>{text}</div>
      </div>
      <svg width={1080} height={1920} style={{ position: "absolute", inset: 0, opacity: arrow ? Math.min(1, p * 1.5) : 0 }}>
        <defs><linearGradient id="arrowg" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stopColor={ACCENT} /><stop offset="1" stopColor={ACCENT2} /></linearGradient></defs>
          {top < 1300 ? (() => {
            // card in the top panel: one smooth curve down the left edge (off the face) to the related-video link,
            // drawn on, then a solid head that follows the curve's end direction
            const P = [[230, top + 120], [70, top + 300], [70, 1480], [150, 1690]];
            const k = Math.min(1, t * 1.6);
            const ux = (P[3][0] - P[2][0]) / Math.hypot(P[3][0] - P[2][0], P[3][1] - P[2][1]);
            const uy = (P[3][1] - P[2][1]) / Math.hypot(P[3][0] - P[2][0], P[3][1] - P[2][1]);
            const hs = spring({ frame: f - from - Math.round(0.6 * fps), fps, config: { damping: 12, stiffness: 220 } });
            const tip = [P[3][0] + ux * 34, P[3][1] + uy * 34];
            const b1 = [P[3][0] - ux * 12 - uy * 30, P[3][1] - uy * 12 + ux * 30];
            const b2 = [P[3][0] - ux * 12 + uy * 30, P[3][1] - uy * 12 - ux * 30];
            return (
              <g transform={`translate(0 ${Math.sin(t * 5) * 8})`}>
                <path d={`M ${P[0][0]} ${P[0][1]} C ${P[1][0]} ${P[1][1]}, ${P[2][0]} ${P[2][1]}, ${P[3][0]} ${P[3][1]}`} pathLength={1} fill="none" stroke="url(#arrowg)" strokeWidth={14} strokeLinecap="round" strokeDasharray="1" strokeDashoffset={1 - k} style={{ filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.5))" }} />
                <path d={`M ${tip[0]} ${tip[1]} L ${b1[0]} ${b1[1]} L ${b2[0]} ${b2[1]} Z`} fill={ACCENT2} stroke={ACCENT2} strokeWidth={8} strokeLinejoin="round"
                  transform={`translate(${P[3][0]} ${P[3][1]}) scale(${hs}) translate(${-P[3][0]} ${-P[3][1]})`} style={{ filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.5))" }} />
              </g>
            );
          })() : (
            <g transform={`translate(${-bob * 0.7} ${bob})`}>
              <path d="M 300 1640 C 250 1660, 215 1690, 195 1745" pathLength={1} fill="none" stroke="url(#arrowg)" strokeWidth={14} strokeLinecap="round" strokeDasharray="1" strokeDashoffset={1 - Math.min(1, t * 2.2)} />
              <path d="M 168 1700 L 193 1750 L 244 1728" fill="none" stroke="url(#arrowg)" strokeWidth={16} strokeLinecap="round" strokeLinejoin="round" opacity={t > 0.4 ? 1 : 0} />
            </g>
          )}

      </svg>
    </div>
  );
};

/** title over the full-screen face (the hook): pops in word by word at the top of the frame */
const FullTitle: React.FC<{ text: string; accent: string }> = ({ text, accent }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = text.split(" ");
  return (
    <div style={{ position: "absolute", left: 60, right: 60, top: 230, display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "0 26px" }}>
      {words.map((w, i) => {
        const hl = w.startsWith("*");
        const p = spring({ frame: f - 3 - i * 3, fps, config: { damping: 13, stiffness: 200 } });
        const txt = w.replace(/\*/g, "");
        return (
          <span key={i} style={{ position: "relative", display: "inline-block", opacity: Math.min(1, p * 2), transform: `translateY(${(1 - p) * 40}px) scale(${0.8 + 0.2 * p})` }}>
            <span style={{ ...capStyle, fontSize: 96, color: "#fff", WebkitTextStroke: "12px #000", paintOrder: "stroke fill", textShadow: "0 8px 24px rgba(0,0,0,0.5)" }}>{txt}</span>
            {hl ? <span style={{ ...capStyle, fontSize: 96, position: "absolute", left: 0, top: 0, background: accent, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>{txt}</span> : null}
          </span>
        );
      })}
    </div>
  );
};

const dbl = (x: number) => Math.pow(10, x / 20);
/** music level at short time t: the track normalised to -20 LUFS, then -22 dB under speech and -17 dB in pauses
 *  (same mix as the long-form Final), 0.6 s release, fades at both ends */
export const shortMusicGain = (t: number, total: number, chunks: Chunk[], lufs: number, gainDb: number) => {
  let duck = 0;
  for (const c of chunks) {
    if (t >= c.s - 0.15 && t <= c.e) { duck = 1; break; }
    if (t > c.e) duck = Math.max(duck, interpolate(t - c.e, [0, 0.6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  }
  const level = interpolate(duck, [0, 1], [-17, -22]);
  const fade = interpolate(t, [0, 0.8], [0, 1], { extrapolateRight: "clamp" }) * interpolate(t, [total - 1.5, total], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return dbl(-20 - lufs + gainDb) * dbl(level) * fade;
};

export const Short: React.FC<ShortProps> = (p) => {
  const { fps, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const accent = p.accent ?? ACCENT_GRAD;
  const starts = segStarts(p.segments, fps);
  // which segment / cut time are we in
  let k = 0;
  while (k + 1 < starts.length && f >= starts[k + 1]) k++;
  const cutT = p.segments[k].from + (f - starts[k]) / fps;
  const chunks = buildChunks(p, fps);
  const face = p.face ?? { x: 0.31, y: 0.08, w: 0.45 };
  const inFull = (p.full ?? []).some((r) => cutT >= r.from && cutT < r.to);
  const fullFace = p.fullFace ?? { x: 0.342, y: 0, w: 0.3164 };
  return (
    <AbsoluteFill style={{ background: "#0d0e13" }}>
      <Series>
        {p.segments.map((g, i) => (
          <Series.Sequence key={i} durationInFrames={Math.round((g.to - g.from) * fps)}>
            {inFull ? (
              <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
                <Cropped src={projectFile(p.project, p.faceSrc ?? "out/talking_cut.mp4")} rect={fullFace} boxW={W} boxH={TOP_H + FACE_H} srcAR={16 / 9} startFrom={Math.round(g.from * fps)} />
              </div>
            ) : (
              <>
                <div style={{ position: "absolute", left: 0, top: 0, width: W, height: TOP_H, overflow: "hidden" }}>
                  <TopPanel p={p} cutT={cutT} startFrom={Math.round(g.from * fps)} segFrom={g.from} />
                </div>
                <div style={{ position: "absolute", left: 0, top: TOP_H, width: W, height: FACE_H, overflow: "hidden" }}>
                  <Cropped src={projectFile(p.project, p.faceSrc ?? "out/talking_cut.mp4")} rect={face} boxW={W} boxH={FACE_H} srcAR={16 / 9} startFrom={Math.round(g.from * fps)} />
                </div>
              </>
            )}
            {p.audioSrc ? <Audio src={projectFile(p.project, p.audioSrc)} startFrom={Math.round(g.from * fps)} /> : null}
          </Series.Sequence>
        ))}
      </Series>
      {/* soft seam between the two panels */}
      {inFull ? null : <div style={{ position: "absolute", left: 0, right: 0, top: TOP_H - 2, height: 4, background: "rgba(0,0,0,0.6)" }} />}
      {inFull && p.fullTitle ? <FullTitle text={p.fullTitle} accent={accent} /> : null}
      <Captions chunks={chunks} accent={accent} top={inFull ? 1380 : undefined} />
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
      {p.endCard ? <EndCard text={p.endCard} from={durationInFrames - Math.round((p.endSeconds ?? 4) * fps)} accent={accent} arrow={p.variant !== "ig"} top={p.endCardTop} /> : null}
    </AbsoluteFill>
  );
};
