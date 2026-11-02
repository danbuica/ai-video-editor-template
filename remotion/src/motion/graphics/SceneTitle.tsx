import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { ACCENT_GRAD, enterStyle, exitProgress, theme } from "../theme";
import { MotionItem } from "../types";

/**
 * Example full-frame scene ("scene-" prefix: the talking head goes full screen and blurs underneath).
 * motion.json: { "id": "s1", "type": "scene-title", "from": {"w": 10}, "to": {"w": 18, "end": true},
 *               "title": "It does everything.", "sub": "optional second line", "at": {"w": 11} }
 */
export const SceneTitle: React.FC<{ item: MotionItem }> = ({ item }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = Math.round(((item.at as number) ?? (item.from as number)) * fps);
  const out = exitProgress(frame, Math.round((item.to as number) * fps), 8);
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out, fontFamily: theme.font, textAlign: "center" }}>
      <div style={{ fontSize: 150, fontWeight: 900, letterSpacing: "-0.05em", lineHeight: 1, maxWidth: 1600, color: "transparent",
        background: ACCENT_GRAD, WebkitBackgroundClip: "text", backgroundClip: "text", ...enterStyle(frame, fps, at, 60) }}>
        {item.title as string}
      </div>
      {item.sub ? (
        <div style={{ marginTop: 34, fontSize: 52, fontWeight: 600, color: theme.muted, ...enterStyle(frame, fps, at + 8, 30) }}>{item.sub as string}</div>
      ) : null}
    </AbsoluteFill>
  );
};
