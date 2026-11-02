import React from "react";
import { AbsoluteFill, CalculateMetadataFunction, Sequence, Series, useVideoConfig } from "remotion";
import { calculateMainMetadata, Main, MainProps } from "./Main";
import { theme } from "./motion/theme";

/** Preview reel: each proposed graphic in context (a little before → a little after), labelled by id. */
export type ReelProps = MainProps & { clips?: { id: string; note?: string; start: number; end: number }[]; only?: string[] };

export const calculateReelMetadata: CalculateMetadataFunction<ReelProps> = async (args) => {
  const base = await calculateMainMetadata(args as never);
  const props = base.props as ReelProps;
  const fps = base.fps as number;
  const items = (props.plan?.items ?? []).filter((it) => !args.props.only || args.props.only.includes(it.id));
  const clips = items.map((it) => ({ id: it.id, note: it.note, start: (it.from as number) - 0.9, end: (it.to as number) + 0.7 }));
  const total = clips.reduce((s, c) => s + Math.round((c.end - c.start) * fps), 0);
  return { ...base, durationInFrames: Math.max(1, total), props: { ...props, clips } };
};

export const MotionReel: React.FC<ReelProps> = (props) => {
  const { fps } = useVideoConfig();
  const clips = props.clips ?? [];
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <Series>
        {clips.map((c) => {
          const len = Math.round((c.end - c.start) * fps);
          return (
            <Series.Sequence key={c.id} durationInFrames={len}>
              <Sequence from={-Math.round(c.start * fps)}>
                <Main {...props} />
              </Sequence>
              <div style={{ position: "absolute", top: 28, left: 28, padding: "10px 20px", borderRadius: 14, background: "rgba(0,0,0,0.7)", color: "#fff", fontFamily: theme.font, fontSize: 30, fontWeight: 800 }}>
                {c.id}
                <span style={{ fontWeight: 600, opacity: 0.7, marginLeft: 14, fontSize: 24 }}>{c.note}</span>
              </div>
            </Series.Sequence>
          );
        })}
      </Series>
    </AbsoluteFill>
  );
};
