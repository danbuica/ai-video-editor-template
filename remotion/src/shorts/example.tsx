import React from "react";
import { OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { projectFile } from "../lib/edl";
import type { Shot, VisualProps } from "../ShortV2";

/**
 * Example content: the cut screen recording at the same moment, filling the box (cover, centred on `focus`).
 * Real shorts usually swap this for footage of the thing being talked about, drawn scenes or stills.
 */
export const exampleShots = (): Shot[] => [
  { from: 0, to: 2, layout: "face" },
  { from: 2, to: 6, layout: "split" },
  { from: 6, to: 9, layout: "full" },
  { from: 9, to: 9999, layout: "split" },
];

export const ExampleVisual: React.FC<VisualProps & { src?: string; focus?: number }> = ({ t, project, box, layout, src = "out/screen_cut.mp4", focus = 0.35 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (layout === "face") return null;
  // play the source at cut time t: this Sequence's local frame 0 = cut time 0
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: "#0b0c10" }}>
      <Sequence from={frame - Math.round(t * fps)} layout="none">
        <OffthreadVideo src={projectFile(project, src)} muted style={{ width: box.w, height: box.h, objectFit: "cover", objectPosition: `${focus * 100}% 50%` }} />
      </Sequence>
    </div>
  );
};
