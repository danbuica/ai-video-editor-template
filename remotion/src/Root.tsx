import { Composition } from "remotion";
import { calculateCutReviewMetadata, CutReview, CutReviewProps } from "./CutReview";
import { calculateMainMetadata, Main, MainProps } from "./Main";
import { calculateReelMetadata, MotionReel, ReelProps } from "./MotionReel";
import { calculateFinalMetadata, Final, FinalProps } from "./Final";
import { calculateFinalSubsetMetadata, FinalSubset, FinalSubsetProps } from "./FinalSubset";
import { calculateShortMetadata, Short, ShortProps } from "./Short";
import { calculateShortV2Metadata, ShortV2, ShortV2Props } from "./ShortV2";

// Pick the project with: npm run dev -- --props='{"project":"<name>"}'
// (or edit the props in the Studio sidebar)
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Main"
        component={Main}
        durationInFrames={30}
        fps={25}
        width={1920}
        height={1080}
        defaultProps={{ project: "example" } satisfies MainProps}
        calculateMetadata={calculateMainMetadata}
      />
      <Composition
        id="Final"
        component={Final}
        durationInFrames={30}
        fps={25}
        width={1920}
        height={1080}
        defaultProps={{ project: "example", motionFile: "motion.json" } satisfies FinalProps}
        calculateMetadata={calculateFinalMetadata}
      />
      <Composition
        id="FinalSubset"
        component={FinalSubset}
        durationInFrames={30}
        fps={25}
        width={1920}
        height={1080}
        defaultProps={{ project: "example", motionFile: "motion.json" } satisfies FinalSubsetProps}
        calculateMetadata={calculateFinalSubsetMetadata}
      />
      <Composition
        id="MotionReel"
        component={MotionReel}
        durationInFrames={30}
        fps={25}
        width={1920}
        height={1080}
        defaultProps={{ project: "example", motionFile: "motion_proposal.json" } satisfies ReelProps}
        calculateMetadata={calculateReelMetadata}
      />
      <Composition
        id="Short"
        component={Short}
        durationInFrames={30}
        fps={25}
        width={1080}
        height={1920}
        defaultProps={{ project: "example", segments: [{ from: 0, to: 5 }] } satisfies ShortProps}
        calculateMetadata={calculateShortMetadata}
      />
      <Composition
        id="ShortV2"
        component={ShortV2}
        durationInFrames={30}
        fps={25}
        width={1080}
        height={1920}
        defaultProps={{ project: "example", segments: [{ from: 0, to: 5 }], content: "example" } satisfies ShortV2Props}
        calculateMetadata={calculateShortV2Metadata}
      />
      <Composition
        id="CutReview"
        component={CutReview}
        durationInFrames={30}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ project: "example" } satisfies CutReviewProps}
        calculateMetadata={calculateCutReviewMetadata}
      />
    </>
  );
};
