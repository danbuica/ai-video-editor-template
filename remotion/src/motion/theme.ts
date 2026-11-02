import { loadFont } from "@remotion/google-fonts/Inter";
import { getInputProps, spring, SpringConfig } from "remotion";

/**
 * Your look lives here: font, accent colours, motion springs. Every graphic, chapter card and caption reads from
 * this file, so restyling the whole editor starts here. A render can override the accent with the
 * `accent` / `accent2` props.
 */
const inputs = (() => {
  try {
    return getInputProps() as { accent?: string; accent2?: string };
  } catch {
    return {} as { accent?: string; accent2?: string };
  }
})();
export const ACCENT = inputs.accent ?? "#4F8CFF";
export const ACCENT2 = inputs.accent2 ?? (inputs.accent ? inputs.accent : "#8A5CFF");
export const ACCENT_GRAD = `linear-gradient(90deg, ${ACCENT}, ${ACCENT2})`;
const hx = ACCENT.replace("#", "");
export const ACCENT_RGB = `${parseInt(hx.slice(0, 2), 16)},${parseInt(hx.slice(2, 4), 16)},${parseInt(hx.slice(4, 6), 16)}`;

export const { fontFamily } = loadFont("normal", { weights: ["500", "600", "700", "800", "900"], subsets: ["latin"] });

export const theme = {
  font: fontFamily,
  white: "#FFFFFF",
  ink: "#0B0D14",
  accent: ACCENT,
  muted: "rgba(255,255,255,0.74)",
  faint: "rgba(255,255,255,0.45)",
  textShadow: "0 2px 10px rgba(0,0,0,0.40), 0 1px 2px rgba(0,0,0,0.35)",
};

export const SPRING_IN: Partial<SpringConfig> = { damping: 15, stiffness: 170, mass: 0.7 };
export const SPRING_POP: Partial<SpringConfig> = { damping: 12, stiffness: 200, mass: 0.7 };
export const SPRING_SOFT: Partial<SpringConfig> = { damping: 22, stiffness: 120, mass: 1 };

export const springAt = (frame: number, fps: number, startFrame: number, config = SPRING_IN, durationInFrames?: number) =>
  spring({ frame: frame - startFrame, fps, config, durationInFrames });

/** Entrance: rise + fade. */
export const enterStyle = (frame: number, fps: number, startFrame: number, dist = 40, config = SPRING_IN) => {
  const p = springAt(frame, fps, startFrame, config);
  return {
    opacity: Math.min(1, p * 1.4),
    transform: `translateY(${(1 - p) * dist}px) scale(${0.94 + 0.06 * p})`,
  } as const;
};

export const exitProgress = (frame: number, endFrame: number, len = 8) =>
  Math.max(0, Math.min(1, (endFrame - frame) / len));
