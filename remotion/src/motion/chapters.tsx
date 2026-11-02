import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { ACCENT_GRAD, exitProgress, springAt, SPRING_POP, theme } from "./theme";

/**
 * Chapter cards, inserted between chapters (motion.json `chapters`, `chapterSeconds`, `chapterStyle`).
 * `backdrop` is the frozen first frame of the chapter that follows. Add your own styles to CHAPTER_CARDS.
 */
export type ChapterCardProps = { number: number; title: string; sub?: string; durationInFrames: number; backdrop: React.ReactNode };

/** Example style: the next chapter's first frame, blurred and dimmed, with the number and title on top. */
const DefaultCard: React.FC<ChapterCardProps> = ({ number, title, sub, durationInFrames, backdrop }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  const out = exitProgress(frame, durationInFrames, 8);
  const p = springAt(frame, fps, 3, SPRING_POP);
  const line = interpolate(frame, [8, durationInFrames - 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: "#000", fontFamily: theme.font }}>
      <AbsoluteFill style={{ filter: `blur(${36 * inn * out}px) brightness(${1 - 0.65 * inn * out})`, transform: `scale(${1 + 0.05 * inn * out})` }}>{backdrop}</AbsoluteFill>
      <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 160, opacity: out }}>
        <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: "0.3em", textTransform: "uppercase", color: theme.accent, opacity: p }}>
          Chapter {String(number).padStart(2, "0")}
        </div>
        <div style={{ fontSize: 130, fontWeight: 900, letterSpacing: "-0.05em", lineHeight: 1, color: theme.white, maxWidth: 1400, marginTop: 20,
          transform: `translateY(${(1 - p) * 50}px)`, opacity: Math.min(1, p * 1.5) }}>{title}</div>
        {sub ? <div style={{ fontSize: 46, fontWeight: 600, color: theme.muted, marginTop: 22, opacity: p }}>{sub}</div> : null}
        <div style={{ height: 8, width: 520, borderRadius: 4, background: "rgba(255,255,255,0.14)", marginTop: 40, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${line * 100}%`, background: ACCENT_GRAD }} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const CHAPTER_CARDS: Record<string, React.FC<ChapterCardProps>> = {
  default: DefaultCard,
};
