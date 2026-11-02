import React from "react";
import { AbsoluteFill, Audio, Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { GRAPHICS } from "./graphics";
import { SPRING_SOFT, theme } from "./theme";
import { isScene, MotionItem, MotionPlan, sfxUrl } from "./types";

/** projects/_assets/sfx/library.json (pipeline/tools/assets.py sfx): length, loudest moment and a loudness trim per sound */
export type SfxLib = Record<string, { duration: number; peak_at: number; trim_db?: number }>;

/** Darken the side the text sits on so white type always reads. */
export const SideShade: React.FC<{ side?: string; amount: number }> = ({ side = "left", amount }) => {
  if (side === "center")
    return <AbsoluteFill style={{ background: `linear-gradient(to top, rgba(5,7,12,${0.7 * amount}) 0%, rgba(5,7,12,0) 45%)` }} />;
  const dir = side === "right" ? "to left" : "to right";
  return (
    <AbsoluteFill
      style={{ background: `linear-gradient(${dir}, rgba(5,7,12,${0.78 * amount}) 0%, rgba(5,7,12,${0.45 * amount}) 38%, rgba(5,7,12,0) 62%)` }}
    />
  );
};

/** A motion.json type with no component yet: shown as a label so it's obvious in the draft. */
const Missing: React.FC<{ item: MotionItem }> = ({ item }) => (
  <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
    <div style={{ padding: "18px 30px", borderRadius: 16, background: "rgba(200,30,30,0.85)", color: "#fff", fontFamily: theme.font, fontSize: 36, fontWeight: 800 }}>
      no graphic "{item.type}" in motion/graphics/index.ts
    </div>
  </AbsoluteFill>
);

/** 0..1 how much a full-frame scene is up (Main blurs/dims the talking head by this). */
export const scenePresence = (frame: number, fps: number, items: MotionItem[]) =>
  Math.max(0, ...items.filter(isScene).map((it) => presence(frame, fps, it.from as number, it.to as number)));

/** 0→1 while an item is on screen (soft in at `from`, soft out at `to`). */
export const presence = (frame: number, fps: number, from: number, to: number) => {
  const a = spring({ frame: frame - Math.round(from * fps), fps, config: SPRING_SOFT });
  const b = spring({ frame: frame - Math.round(to * fps), fps, config: SPRING_SOFT });
  return Math.max(0, Math.min(1, a - b));
};

/** Reframe the full-screen talking head away from the text: returns translateX (fraction of width) and extra scale. */
export const reframe = (frame: number, fps: number, items: MotionItem[]) => {
  let dx = 0;
  let sc = 0;
  for (const it of items) {
    if (!it.side || isScene(it)) continue;
    const p = presence(frame, fps, it.from as number, it.to as number);
    if (p <= 0) continue;
    const dir = it.side === "left" ? 1 : it.side === "right" ? -1 : 0;
    dx += dir * 0.12 * p;
    sc += (dir === 0 ? 0.06 : 0.26) * p;
  }
  return { dx, scale: 1 + sc };
};

export const MotionLayer: React.FC<{ plan: MotionPlan; sfxLib: SfxLib; visibleOnly?: (it: MotionItem) => boolean }> = ({ plan, sfxLib, visibleOnly }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const active = plan.items.filter((it) => t >= (it.from as number) - 0.1 && t <= (it.to as number) + 0.5 && (!visibleOnly || visibleOnly(it)));
  return (
    <AbsoluteFill>
      {active.map((it) => {
        const C = GRAPHICS[it.type] ?? Missing;
        const p = presence(frame, fps, it.from as number, it.to as number);
        return (
          <AbsoluteFill key={it.id}>
            {isScene(it) ? null : <SideShade side={it.side} amount={p} />}
            <C item={it} />
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};

/** Every sound effect of the plan, placed so its loudest moment ("hit") lands on the cue when hit=true. */
export const SfxTrack: React.FC<{ plan: MotionPlan; sfxLib: SfxLib; offsetFrames?: (f: number) => number }> = ({ plan, sfxLib, offsetFrames }) => {
  const { fps } = useVideoConfig();
  const base = plan.sfxVolume ?? 0.22;
  const events = plan.items.flatMap((it) => it.sfx ?? []);
  return (
    <>
      {events.map((s, i) => {
        const lib = sfxLib[s.name];
        if (!lib) return null;
        const start = (s.at as number) - (s.hit ? lib.peak_at : 0);
        let from = Math.round(start * fps);
        if (offsetFrames) from = offsetFrames(from);
        return (
          <Sequence key={i} from={from} durationInFrames={Math.ceil(lib.duration * fps) + 2} layout="none">
            <Audio src={sfxUrl(s.name)} volume={base * (s.vol ?? 1) * Math.pow(10, (lib.trim_db ?? 0) / 20)} />
          </Sequence>
        );
      })}
    </>
  );
};
