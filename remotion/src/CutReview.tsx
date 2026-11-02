import React from "react";
import {
  AbsoluteFill,
  CalculateMetadataFunction,
  OffthreadVideo,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CutWord, Edl, loadEdl, loadWords, projectFile } from "./lib/edl";

export type CutReviewProps = {
  project: string;
  edl?: Edl;
  words?: CutWord[];
};

export const calculateCutReviewMetadata: CalculateMetadataFunction<CutReviewProps> = async ({ props }) => {
  const [edl, words] = await Promise.all([loadEdl(props.project), loadWords(props.project)]);
  return {
    fps: edl.fps_float,
    durationInFrames: edl.out_frames,
    props: { ...props, edl, words },
  };
};

const KIND_COLOR: Record<string, string> = {
  retake: "#ff4d4f",
  restart: "#ff7a45",
  backtrack: "#ffa940",
  stutter: "#ffc53d",
  filler: "#bae637",
  marker: "#f759ab",
  mid_sentence: "#40a9ff",
  pause: "#8c8c8c",
  manual: "#b37feb",
};

const Captions: React.FC<{ words: CutWord[]; t: number }> = ({ words, t }) => {
  const i = words.findIndex((w) => w.end >= t);
  if (i < 0) return null;
  const from = Math.max(0, i - 6);
  const slice = words.slice(from, from + 14);
  return (
    <div style={{ fontSize: 34, lineHeight: 1.35, color: "#fff", fontFamily: "Inter, Helvetica, sans-serif" }}>
      {slice.map((w) => (
        <span
          key={w.src_i}
          style={{ opacity: w.start <= t && t <= w.end + 0.05 ? 1 : w.end < t ? 0.55 : 0.3, marginRight: 10 }}
        >
          {w.w}
        </span>
      ))}
    </div>
  );
};

const Timeline: React.FC<{ edl: Edl; frame: number }> = ({ edl, frame }) => {
  const joins = edl.joins.filter((j) => j.kind !== "head" && j.kind !== "tail");
  return (
    <div style={{ position: "relative", height: 36, background: "#1f1f1f", borderRadius: 6 }}>
      {joins.map((j, k) => (
        <div
          key={k}
          title={j.kind}
          style={{
            position: "absolute",
            left: `${(j.out_frame / edl.out_frames) * 100}%`,
            top: 4,
            bottom: 4,
            width: 3,
            background: KIND_COLOR[j.kind] ?? "#fff",
            outline: j.tight ? "2px solid #fff" : undefined,
          }}
        />
      ))}
      <div
        style={{
          position: "absolute",
          left: `${(frame / edl.out_frames) * 100}%`,
          top: -4,
          bottom: -4,
          width: 2,
          background: "#fff",
        }}
      />
    </div>
  );
};

/** Review the cut: screen recording + talking head side by side, captions and every join. */
export const CutReview: React.FC<CutReviewProps> = ({ project, edl, words = [] }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!edl) return null;
  const t = frame / fps;
  // the join we just passed (shown for 1.5 s)
  const recent = [...edl.joins]
    .filter((j) => j.kind !== "head" && j.kind !== "tail" && j.out_frame <= frame && frame - j.out_frame < fps * 1.5)
    .pop();

  return (
    <AbsoluteFill style={{ background: "#0b0b0b", padding: 32, gap: 20 }}>
      <div style={{ display: "flex", gap: 20, height: 760 }}>
        <div style={{ flex: 1, background: "#000", borderRadius: 8, overflow: "hidden" }}>
          <OffthreadVideo
            src={projectFile(project, "out/screen_cut.mp4")}
            muted
            style={{ width: "100%", height: "100%", objectFit: "contain" }}
          />
        </div>
        <div style={{ width: 430, background: "#000", borderRadius: 8, overflow: "hidden" }}>
          <OffthreadVideo
            src={projectFile(project, "out/talking_cut.mp4")}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        </div>
      </div>
      <Timeline edl={edl} frame={frame} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
        <Captions words={words} t={t} />
        <div style={{ minWidth: 380, textAlign: "right", fontFamily: "monospace", color: "#aaa", fontSize: 22 }}>
          {recent ? (
            <div style={{ color: KIND_COLOR[recent.kind] ?? "#fff" }}>
              ✂ {recent.kind}
              {recent.mid_sentence ? " (mid-sentence)" : ""} · −{recent.removed_s.toFixed(1)}s
              {recent.tight ? " · tight" : ""}
            </div>
          ) : (
            <div>
              {project} · {edl.joins.length} joins
            </div>
          )}
        </div>
      </div>
    </AbsoluteFill>
  );
};
