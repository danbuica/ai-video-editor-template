import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { enterStyle, exitProgress, theme } from "../theme";
import { MotionItem } from "../types";

/**
 * Example graphic. Lines of text that pop in one by one beside the speaker.
 * motion.json: { "id": "g1", "type": "text-pop", "side": "left", "from": {"w": 120}, "to": {"w": 140, "end": true},
 *               "lines": [{ "text": "Sync", "at": {"w": 121} }, { "text": "Cut", "at": {"w": 125}, "accent": true }] }
 */
type Line = { text: string; at: number; accent?: boolean };

export const TextPop: React.FC<{ item: MotionItem }> = ({ item }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const lines = (item.lines as Line[]) ?? [];
  const out = exitProgress(frame, Math.round((item.to as number) * fps), 8);
  const side = item.side ?? "left";
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: side === "center" ? "center" : side === "left" ? "flex-start" : "flex-end",
      padding: `0 ${width * 0.07}px`, opacity: out, fontFamily: theme.font }}>
      {lines.map((l, i) => (
        <div key={i} style={{ fontSize: 110, fontWeight: 900, letterSpacing: "-0.04em", lineHeight: 1.05, textShadow: theme.textShadow,
          color: l.accent ? theme.accent : theme.white, ...enterStyle(frame, fps, Math.round(l.at * fps)) }}>
          {l.text}
        </div>
      ))}
    </AbsoluteFill>
  );
};
