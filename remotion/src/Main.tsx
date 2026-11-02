import React from "react";
import {
  AbsoluteFill,
  CalculateMetadataFunction,
  Easing,
  Img,
  interpolate,
  OffthreadVideo,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Edl, loadEdl, projectFile } from "./lib/edl";
import { MotionLayer, presence, reframe, scenePresence, SfxLib, SfxTrack } from "./motion/MotionLayer";
import { CutWord, isScene, MotionPlan, resolvePlan } from "./motion/types";
import { DemoClip, DemoPanel, PhoneClip, PhoneLayer, phonesReframe } from "./motion/phones";
import { ACCENT, ACCENT_RGB } from "./motion/theme";
import { CameraCrop, Card, FaceContext } from "./lib/camera";

/**
 * Final layout.
 *  - "pip":  screen recording full frame, talking head in a rounded portrait card in the
 *            empty area on the right of the recording.
 *  - "full": talking head full screen (used in parts of the hook).
 *  - "images": a still (e.g. a launch post) shown instead of the screen recording, face card stays.
 *  - "zooms": push into a point of the screen recording and ease back out (hook energy, pointing at a UI detail).
 * Layout per project lives in projects/<name>/out/layout.json (times on the cut timeline, seconds).
 */

export type { Card };

export type Layout = {
  card: Card;
  /** ranges (cut-timeline seconds) where the talking head is full screen; everything else is pip */
  full: { from: number; to: number; note?: string }[];
  /** punch-in on jump cuts while full screen */
  punchIn: number;
  /** ranges where a still image (path inside the project, e.g. "out/x_post.png") replaces the screen */
  /** push: slow push-in over the whole range toward x/y (fractions of the image), ending at scale */
  images?: { from: number; to: number; src: string; note?: string; push?: { x: number; y: number; scale: number } }[];
  /** screen zooms: x/y = the point to push into (fractions of the frame), scale = how far (1.4–2.2 reads well) */
  zooms?: { from: number; to: number; x: number; y: number; scale: number; note?: string;
    /** boxes (fractions of the frame, before zooming) that wipe in around the thing once the zoom lands */
    marks?: { x: number; y: number; w: number; h: number }[] }[];
  /** phone screen recordings floating over the full-screen talking head (it moves aside for them) */
  phones?: PhoneClip[];
  /** demo screen recordings (e.g. a prompt run in claude.ai) in place of the screen, face card stays */
  demos?: DemoClip[];
  /** secrets on the screen recording (API keys…): frosted boxes, x/y/w/h fractions of the frame */
  blurs?: { from: number; to: number; x: number; y: number; w: number; h: number; note?: string }[];
  /** face tracking (cut seconds → camera faceX), for long recordings where the speaker shifts in their chair (pipeline/tools/facetrack.py) */
  faceKeys?: { t: number; x: number }[];
};

/** faceX at time t from the tracked keys (linear between keys), else the card's fixed value */
const faceAt = (layout: Layout, t: number) => {
  const k = layout.faceKeys;
  if (!k?.length) return layout.card.faceX;
  if (t <= k[0].t) return k[0].x;
  for (let i = 1; i < k.length; i++) {
    if (t < k[i].t) return interpolate(t, [k[i - 1].t, k[i].t], [k[i - 1].x, k[i].x], { easing: Easing.inOut(Easing.cubic) });
  }
  return k[k.length - 1].x;
};

/** 0→1 eased push-in at `from`, back to 0 at `to` (0.6 s each way, no overshoot so text stays readable) */
const zoomAmount = (t: number, from: number, to: number) => {
  const e = (a: number, b: number) => interpolate(t, [a, b], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.65, 0, 0.35, 1) });
  return e(from, from + 0.6) * (1 - e(to - 0.6, to));
};

export const DEFAULT_CARD: Card = {
  x: 0.7085,
  y: 0.15,
  w: 0.2735,
  h: 0.69,
  radius: 26,
  faceX: 0.48,
  top: 0.0,
  zoom: 1.18,
};

export type MainProps = { project: string; edl?: Edl; layout?: Layout; plan?: MotionPlan; sfxLib?: SfxLib; motionFile?: string; silent?: boolean;
  /** drafts: read 720p proxies (out/proxy/*) instead of the full-res cut files */
  proxy?: boolean;
  /** shorts: graphics only, centred on a designed background (no camera, no screen recording) */
  scenesOnly?: boolean };

export const calculateMainMetadata: CalculateMetadataFunction<MainProps> = async ({ props }) => {
  const edl = await loadEdl(props.project);
  const res = await fetch(projectFile(props.project, "out/layout.json"));
  const layout: Layout = res.ok
    ? await res.json()
    : { card: DEFAULT_CARD, full: [], punchIn: 1.1 };
  layout.card = { ...DEFAULT_CARD, ...layout.card };
  // Motion plan (optional): word-anchored graphics → resolve to seconds on this cut
  let plan: MotionPlan | undefined;
  let sfxLib: SfxLib = {};
  const mres = await fetch(projectFile(props.project, `out/${props.motionFile ?? "motion.json"}`));
  if (mres.ok) {
    const words: CutWord[] = (await (await fetch(projectFile(props.project, "out/transcript_cut.json"))).json()).words;
    plan = resolvePlan(await mres.json(), words);
    const lib = await fetch(projectFile("_assets", "sfx/library.json"));
    if (lib.ok) sfxLib = await lib.json();
  }
  return { fps: edl.fps_float, durationInFrames: edl.out_frames, props: { ...props, edl, layout, plan, sfxLib } };
};

const PUNCH_MIN_GAP = 5;

/** A still (screenshot of a post, a page…) as a floating card on a soft backdrop, in the area left of the face card. */
const ImagePanel: React.FC<{ src: string; from: number; to: number; areaW: number; push?: { x: number; y: number; scale: number } }> = ({ src, from, to, areaW, push }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const p = spring({ frame: frame - Math.round(from * fps), fps, config: { damping: 18, stiffness: 140 } });
  const pad = 40;
  const boxH = height - 2 * 44;
  return (
    <AbsoluteFill style={{ background: "linear-gradient(135deg, #e9eef6 0%, #d6e1f1 55%, #c7d6ec 100%)" }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: areaW, height, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div
          style={{
            maxHeight: boxH,
            padding: pad,
            background: "#fff",
            borderRadius: 28,
            boxShadow: "0 24px 70px rgba(30,50,90,0.22), 0 2px 8px rgba(30,50,90,0.08)",
            opacity: interpolate(p, [0, 1], [0, 1]),
            transform: `translateY(${interpolate(p, [0, 1], [24, 0])}px) scale(${interpolate(p, [0, 1], [0.95, 1])})`,
          }}
        >
          <div style={{ overflow: "hidden", borderRadius: 8 }}>
            <Img src={src} style={{ maxHeight: boxH - 2 * pad, maxWidth: areaW - 2 * pad - 72, width: "auto", height: "auto", display: "block",
              transform: push ? `scale(${interpolate(frame / fps, [from, to], [1, push.scale], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) })})` : undefined,
              transformOrigin: push ? `${push.x * 100}% ${push.y * 100}%` : undefined }} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** shorts background: deep charcoal, a soft accent glow and a faint dot grid */
const ScenesBackdrop: React.FC = () => (
  <AbsoluteFill style={{ background: "radial-gradient(900px 700px at 50% 45%, #1d1f2a 0%, #0c0d12 70%)" }}>
    <AbsoluteFill style={{ background: `radial-gradient(600px 420px at 50% 42%, rgba(${ACCENT_RGB},0.16), rgba(${ACCENT_RGB},0) 70%)` }} />
    <AbsoluteFill style={{ backgroundImage: "radial-gradient(rgba(255,255,255,0.07) 1.5px, transparent 1.6px)", backgroundSize: "34px 34px" }} />
  </AbsoluteFill>
);

export const Main: React.FC<MainProps> = ({ project, edl, layout, plan, sfxLib = {}, silent, proxy, scenesOnly }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  if (!edl || !layout) return null;
  if (scenesOnly) {
    const centred = plan ? { ...plan, items: plan.items.map((it) => ("side" in it && it.side ? { ...it, side: "center" as const } : it)) } : undefined;
    const phones = (layout.phones ?? []).map((p) => ({ ...p, side: "center" as const }));
    return (
      <AbsoluteFill>
        <ScenesBackdrop />
        {phones.length ? <PhoneLayer phones={phones} resolve={(s) => projectFile(project, s)} /> : null}
        {centred ? <MotionLayer plan={centred} sfxLib={sfxLib} /> : null}
      </AbsoluteFill>
    );
  }
  const t = frame / fps;
  // full-screen talking head: layout ranges + graphics that ask for an extra full-screen moment
  const fullRanges = [
    ...layout.full,
    ...(plan?.items ?? []).filter((it) => it.fullscreen || isScene(it)).map((it) => ({ from: it.from as number, to: it.to as number })),
  ];
  const full = fullRanges.find((r) => t >= r.from && t < r.to);
  const image = full ? undefined : (layout.images ?? []).find((r) => t >= r.from && t < r.to);
  const demo = full || image ? undefined : (layout.demos ?? []).find((r) => t >= r.from && t < r.to);
  const zr = full || image || demo ? undefined : (layout.zooms ?? []).find((r) => t >= r.from && t < r.to);
  const za = zr ? zoomAmount(t, zr.from, zr.to) : 0;
  const rf = full && plan ? reframe(frame, fps, plan.items) : { dx: 0, scale: 1 };
  // phones on one side push the talking head to the other
  const ph = full ? phonesReframe(frame, fps, layout.phones) : { amount: 0, side: "left" as const };
  if (ph.amount > 0) {
    rf.dx += (ph.side === "left" ? 1 : -1) * 0.15 * ph.amount;
    rf.scale = Math.max(rf.scale, 1 + 0.32 * ph.amount);
  }
  const sp = full && plan ? scenePresence(frame, fps, plan.items) : 0;
  // a full-frame scene with card: true keeps the face card on top
  const cardScene = full && plan ? Math.max(0, ...plan.items.filter((it) => it.card).map((it) => presence(frame, fps, it.from as number, it.to as number))) : 0;
  const dir = proxy ? "out/proxy" : "out";
  const talking = projectFile(project, `${dir}/talking_cut.mp4`);
  const screen = projectFile(project, `${dir}/screen_cut.mp4`);
  const card = { ...layout.card, faceX: faceAt(layout, t) };

  // Jump-cut punch-in while full screen: alternate zoom at every join inside the range
  // Punch in only on real jump cuts (a retake removed, not a shortened pause) and at most every
  // PUNCH_MIN_GAP s: flipping at every join made the talking head look broken.
  let zoom = 1;
  if (full) {
    let last = -Infinity;
    let flips = 0;
    for (const j of edl.joins) {
      if (j.out_s <= full.from || j.out_s > t) continue;
      if (j.kind === "head" || j.kind === "tail" || j.kind === "pause" || j.kind === "mid_sentence") continue;
      if ((j.removed_s ?? 0) < 1 || j.out_s - last < PUNCH_MIN_GAP) continue;
      flips += 1;
      last = j.out_s;
    }
    zoom = flips % 2 === 1 ? layout.punchIn : 1;
  }

  const bw = card.w * width;
  const bh = card.h * height;
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {/* Both videos stay mounted so switching layouts never re-seeks */}
      <AbsoluteFill style={{ visibility: full ? "hidden" : "visible" }}>
        <AbsoluteFill style={{ transform: zr ? `scale(${1 + (zr.scale - 1) * za})` : undefined, transformOrigin: zr ? `${zr.x * 100}% ${zr.y * 100}%` : undefined }}>
          <OffthreadVideo src={screen} muted style={{ width: "100%", height: "100%", objectFit: "cover", visibility: image || demo ? "hidden" : "visible" }} />
          {zr?.marks?.map((m, i) => {
            const k = interpolate(t, [zr.from + 0.55 + i * 0.25, zr.from + 0.95 + i * 0.25], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.33, 1, 0.68, 1) }) * za;
            return (
              <div key={i} style={{ position: "absolute", left: m.x * width - 6, top: m.y * height - 4, width: m.w * width + 12, height: m.h * height + 8, borderRadius: 10,
                border: `${3.5 / zr.scale}px solid ${ACCENT}`, background: `rgba(${ACCENT_RGB},${0.1 * k})`, boxShadow: `0 0 ${22 * k}px rgba(${ACCENT_RGB},0.55)`,
                clipPath: `inset(0 ${100 - 100 * k}% 0 0 round 10px)`, opacity: k > 0 ? 1 : 0 }} />
            );
          })}
        </AbsoluteFill>
        {!image && !demo
          ? (layout.blurs ?? []).filter((b) => t >= b.from && t < b.to).map((b, i) => (
              <div key={i} style={{ position: "absolute", left: b.x * width, top: b.y * height, width: b.w * width, height: b.h * height,
                backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)", background: "rgba(240,240,240,0.25)", borderRadius: 6 }} />
            ))
          : null}
        {image ? <ImagePanel src={projectFile(project, image.src)} from={image.from} to={image.to} push={image.push} areaW={card.x * width} /> : null}
        {demo ? <DemoPanel clip={demo} src={projectFile(project, demo.src)} areaW={card.x * width} /> : null}
        <div
          style={{
            position: "absolute",
            left: card.x * width,
            top: card.y * height,
            width: bw,
            height: bh,
            borderRadius: card.radius,
            overflow: "hidden",
            boxShadow: "0 12px 40px rgba(0,0,0,0.35)",
          }}
        >
          <CameraCrop src={talking} bw={bw} bh={bh} card={card} muted={silent} />
        </div>
      </AbsoluteFill>
      {full ? (
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <OffthreadVideo
            src={talking}
            muted
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              // face-safe: zoom anchored just above the head so the top never gets cropped; while a graphic
              // reframes, its zoom replaces the jump-cut punch-in instead of stacking on top of it
              transform: `translateX(${rf.dx * width}px) scale(${Math.max(zoom, rf.scale) * (1 + 0.06 * sp)})`,
              transformOrigin: `${card.faceX * 100}% 6%`,
              filter: sp > 0.001 ? `blur(${34 * sp}px) brightness(${1 - 0.62 * sp}) saturate(${1 - 0.45 * sp})` : undefined,
            }}
          />
        </AbsoluteFill>
      ) : null}
      {layout.phones?.length ? <PhoneLayer phones={layout.phones} resolve={(s) => projectFile(project, s)} /> : null}
      {full && plan ? (
        <FaceContext.Provider value={card}>
          <MotionLayer plan={plan} sfxLib={sfxLib} />
        </FaceContext.Provider>
      ) : null}
      {full && cardScene ? (
        <div style={{ position: "absolute", left: card.x * width, top: card.y * height, width: bw, height: bh, borderRadius: card.radius, overflow: "hidden",
          boxShadow: "0 12px 40px rgba(0,0,0,0.35)", opacity: cardScene }}>
          <CameraCrop src={talking} bw={bw} bh={bh} card={card} muted />
        </div>
      ) : null}
      {plan && !silent ? <SfxTrack plan={plan} sfxLib={sfxLib} /> : null}
    </AbsoluteFill>
  );
};
