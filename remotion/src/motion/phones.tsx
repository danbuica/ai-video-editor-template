import React from "react";
import { AbsoluteFill, Easing, Freeze, interpolate, OffthreadVideo, Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SideShade } from "./MotionLayer";
import { fontFamily } from "./theme";

/**
 * Phone screen recordings floating over the full-screen talking head. Phones that overlap in time stand side by side: a new phone pushes the
 * earlier ones aside. Times are cut-timeline seconds (layout.json "phones").
 */
export type PhoneZoom = { from: number; to: number; x: number; y: number; scale: number; note?: string };
export type PhoneClip = {
  src: string; // file inside the project, e.g. "out/phone1.mp4"
  from: number;
  to: number;
  srcStart?: number; // seconds into the clip at `from`
  rate?: number; // playback speed (fit a long recording to the line)
  side?: "left" | "right" | "center";
  zooms?: PhoneZoom[]; // push into a point of the phone screen (x/y fractions of the screen)
  statusBar?: boolean; // draw an iOS status bar (for a narrow desktop window dressed as a phone)
  srcDuration?: number; // clip length in seconds: freeze the last frame after it
  note?: string;
};

const SPRING_PHONE = { damping: 17, stiffness: 120, mass: 0.9 };

/** 0→1 in at from, back to 0 at to */
export const phonePresence = (frame: number, fps: number, p: PhoneClip) => {
  const a = spring({ frame: frame - Math.round(p.from * fps), fps, config: SPRING_PHONE });
  const b = spring({ frame: frame - Math.round(p.to * fps), fps, config: { damping: 22, stiffness: 140, mass: 0.9 } });
  return Math.max(0, Math.min(1, a - b));
};

/** how much the talking head should move aside (0..1) and to which side */
export const phonesReframe = (frame: number, fps: number, phones: PhoneClip[] = []) => {
  let p = 0;
  let side: "left" | "right" | "center" = "left";
  for (const ph of phones) {
    const v = phonePresence(frame, fps, ph);
    if (v > p) {
      p = v;
      side = ph.side ?? "left";
    }
  }
  return { amount: p, side };
};

/** local frame (inside the clip's Sequence) that shows the clip's last frame */
const freezeAt = (c: { srcStart?: number; rate?: number; srcDuration?: number }, fps: number) =>
  Math.max(0, Math.floor((((c.srcDuration ?? 0) - 0.1 - (c.srcStart ?? 0)) * fps) / (c.rate ?? 1)));

const ease = (t: number, a: number, b: number) =>
  interpolate(t, [a, b], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.65, 0, 0.35, 1) });

const StatusBar: React.FC<{ w: number }> = ({ w }) => {
  const s = w / 393; // iPhone points
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: 54 * s, background: "#fff", zIndex: 2, fontFamily, color: "#000" }}>
      <div style={{ position: "absolute", left: 34 * s, top: 17 * s, fontSize: 17 * s, fontWeight: 600 }}>9:41</div>
      <div style={{ position: "absolute", left: w / 2 - 62 * s, top: 11 * s, width: 124 * s, height: 36 * s, borderRadius: 20 * s, background: "#000" }} />
      <div style={{ position: "absolute", right: 30 * s, top: 19 * s, display: "flex", gap: 6 * s, alignItems: "center" }}>
        {[5, 8, 11, 14].map((h, i) => (
          <div key={i} style={{ width: 3.5 * s, height: h * s, background: "#000", borderRadius: 1 * s, alignSelf: "flex-end" }} />
        ))}
        <div style={{ width: 25 * s, height: 12 * s, border: `${1.2 * s}px solid rgba(0,0,0,0.45)`, borderRadius: 3.5 * s, padding: 1.5 * s, marginLeft: 4 * s }}>
          <div style={{ width: "80%", height: "100%", background: "#000", borderRadius: 2 * s }} />
        </div>
      </div>
    </div>
  );
};

const Phone: React.FC<{ clip: PhoneClip; src: string; index: number; offset: number; p: number; t: number }> = ({ clip, src, index, offset, p, t }) => {
  const { fps, width, height } = useVideoConfig();
  const screenH = height * 0.84;
  const screenW = screenH * (1180 / 2556);
  const bezel = screenW * 0.035;
  const outerW = screenW + 2 * bezel;
  const outerH = screenH + 2 * bezel;
  const radius = screenW * 0.15;
  const areaCx = (clip.side === "right" ? 0.7 : clip.side === "center" ? 0.5 : 0.3) * width;
  const cx = areaCx + offset;
  const tiltBase = index % 2 === 0 ? -3 : 3;
  const y = (1 - p) * height * 0.75;
  const rot = tiltBase * (1 + 3 * (1 - p));
  // inner zoom (text on the phone made readable)
  const z = (clip.zooms ?? []).find((r) => t >= r.from - 0.01 && t < r.to + 0.7);
  const za = z ? ease(t, z.from, z.from + 0.7) * (1 - ease(t, z.to, z.to + 0.7)) : 0;
  const local = Math.max(0, t - clip.from);
  const srcT = (clip.srcStart ?? 0) + local * (clip.rate ?? 1);
  const frozen = clip.srcDuration !== undefined && srcT >= clip.srcDuration - 0.05;
  const startFrom = Math.round((clip.srcStart ?? 0) * fps);
  const video = (
    <OffthreadVideo src={src} muted startFrom={startFrom} playbackRate={clip.rate ?? 1}
      style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
  );
  return (
    <div
      style={{
        position: "absolute",
        left: cx - outerW / 2,
        top: (height - outerH) / 2 + y,
        width: outerW,
        height: outerH,
        opacity: Math.min(1, p * 1.6),
        transform: `rotate(${rot}deg) scale(${interpolate(p, [0, 1], [0.92, 1]) * (1 + 0.04 * za)})`,
        borderRadius: radius + bezel,
        background: "linear-gradient(145deg, #3a3d45 0%, #16171b 40%, #0b0c0f 100%)",
        padding: bezel,
        boxShadow:
          "inset 0 0 0 1.5px rgba(255,255,255,0.22), inset 0 0 0 4px rgba(0,0,0,0.6), 0 2px 6px rgba(0,0,0,0.35), 0 40px 90px rgba(0,0,0,0.55)",
      }}
    >
      <div style={{ position: "relative", width: screenW, height: screenH, borderRadius: radius, overflow: "hidden", background: "#000" }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            transform: z ? `scale(${1 + (z.scale - 1) * za})` : undefined,
            transformOrigin: z ? `${z.x * 100}% ${z.y * 100}%` : undefined,
          }}
        >
          {clip.statusBar ? <StatusBar w={screenW} /> : null}
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, top: clip.statusBar ? screenW * (54 / 393) : 0 }}>
            {frozen ? <Freeze frame={freezeAt(clip, fps)}>{video}</Freeze> : video}
          </div>
        </div>
      </div>
    </div>
  );
};

export const PhoneLayer: React.FC<{ phones: PhoneClip[]; resolve: (src: string) => string }> = ({ phones, resolve }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const t = frame / fps;
  const live = phones.map((ph, i) => ({ ph, i, p: phonePresence(frame, fps, ph) })).filter((x) => t >= x.ph.from - 0.05 && x.p > 0.001);
  if (!live.length) return null;
  const spacing = height * 0.84 * (1180 / 2556) * 1.2;
  const shade = Math.max(...live.map((x) => x.p));
  const side = live[0].ph.side ?? "left";
  return (
    <AbsoluteFill>
      {side === "center" ? null : <SideShade side={side} amount={shade * 0.9} />}
      {live.map(({ ph, i, p }) => {
        // others on screen push this phone aside: earlier ones go left, later ones go right
        let offset = 0;
        for (const o of live) {
          if (o.i === i || (o.ph.side ?? "left") !== (ph.side ?? "left")) continue;
          offset += (o.ph.from < ph.from ? 0.5 : -0.5) * spacing * o.p;
        }
        return (
          <Sequence key={i} from={Math.round(ph.from * fps)} layout="none">
            <Phone clip={ph} src={resolve(ph.src)} index={i} offset={offset} p={p} t={t} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

/* ------------------------------------------------------------- demo recordings (pip) */

export type DemoClip = { from: number; to: number; src: string; srcStart?: number; rate?: number; srcDuration?: number; note?: string };

/** A screen recording of a demo (e.g. a claude.ai prompt) in place of the screen, as a floating window
 *  on a soft backdrop left of the face card. */
export const DemoPanel: React.FC<{ clip: DemoClip; src: string; areaW: number }> = ({ clip, src, areaW }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const t = frame / fps;
  const p = spring({ frame: frame - Math.round(clip.from * fps), fps, config: { damping: 18, stiffness: 140 } });
  const local = Math.max(0, t - clip.from);
  const srcT = (clip.srcStart ?? 0) + local * (clip.rate ?? 1);
  const frozen = clip.srcDuration !== undefined && srcT >= clip.srcDuration - 0.05;
  const video = (
    <OffthreadVideo src={src} muted startFrom={Math.round((clip.srcStart ?? 0) * fps)} playbackRate={clip.rate ?? 1}
      style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }} />
  );
  const boxH = height - 2 * 44;
  const boxW = areaW - 2 * 44;
  return (
    <AbsoluteFill style={{ background: "linear-gradient(135deg, #e9eef6 0%, #d6e1f1 55%, #c7d6ec 100%)" }}>
      <div style={{ position: "absolute", left: 44, top: 44, width: boxW, height: boxH, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div
          style={{
            width: "100%",
            height: "100%",
            background: "#fff",
            borderRadius: 22,
            overflow: "hidden",
            boxShadow: "0 24px 70px rgba(30,50,90,0.22), 0 2px 8px rgba(30,50,90,0.08)",
            opacity: interpolate(p, [0, 1], [0, 1]),
            transform: `translateY(${interpolate(p, [0, 1], [24, 0])}px) scale(${interpolate(p, [0, 1], [0.96, 1])})`,
          }}
        >
          <Sequence from={Math.round(clip.from * fps)} layout="none">
            {frozen ? <Freeze frame={freezeAt(clip, fps)}>{video}</Freeze> : video}
          </Sequence>
        </div>
      </div>
    </AbsoluteFill>
  );
};
