import React from "react";
import { CalculateMetadataFunction, Sequence, staticFile, useCurrentFrame } from "remotion";
import { calculateFinalMetadata, Final, FinalProps } from "./Final";

/**
 * Fast 4K final (pipeline/tools/hybrid_render.py): only the Final frames ffmpeg can't draw (graphics, full-screen head, images, chapter cards),
 * back to back. Frame f of this composition = Final frame `frames[f]` (pipeline/tools/hybrid_plan.py → out/hybrid/plan.json).
 * Rendered muted: the sound is mixed separately (pipeline/tools/hybrid_audio.py).
 */
export type FinalSubsetProps = FinalProps & { frames?: number[] };

export const calculateFinalSubsetMetadata: CalculateMetadataFunction<FinalSubsetProps> = async (args) => {
  const base = await calculateFinalMetadata(args as never);
  // no plan yet (any project not rendered this way): stay a 1-frame composition so `remotion compositions` still works
  const res = await fetch(staticFile(`${args.props.project}/out/hybrid/plan.json`));
  const frames: number[] = res.ok ? (await res.json()).remotion_frames : [];
  return { ...base, durationInFrames: Math.max(1, frames.length), props: { ...(base.props as FinalProps), frames } };
};

export const FinalSubset: React.FC<FinalSubsetProps> = (props) => {
  const f = useCurrentFrame();
  const target = props.frames?.[f] ?? f;
  return (
    <Sequence from={f - target} layout="none">
      <Final {...props} silent />
    </Sequence>
  );
};
