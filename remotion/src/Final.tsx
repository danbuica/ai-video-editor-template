import React from "react";
import { AbsoluteFill, Audio, CalculateMetadataFunction, Freeze, interpolate, Sequence, Series, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { calculateMainMetadata, Main, MainProps } from "./Main";
import { CHAPTER_CARDS } from "./motion/chapters";
import { theme } from "./motion/theme";
import { CutWord, sfxUrl } from "./motion/types";

/**
 * The finished video: Main (layout + graphics + SFX) split at chapter starts with inserted chapter cards,
 * plus a music bed that ducks under the voice. Times: "cut" = Main's timeline, "final" = with cards.
 */
export type MusicTrack = { file: string; lufs: number; gainDb?: number; label?: string };
export type FinalProps = MainProps & {
  chapterStyle?: string;
  music?: MusicTrack;
  label?: string;
  /** parts of a long video (pipeline/tools/parts_split.py): where this part's music starts in the bed (s), and no fade at a part join */
  musicFrom?: number;
  noFadeIn?: boolean;
  noFadeOut?: boolean;
  /** a part of a long video whose next part opens on a chapter card: the music rises into it 0.1 s early, as in one video */
  cardAfter?: boolean;
  // computed
  segments?: { start: number; end: number }[]; // cut frames
  cards?: { number: number; title: string; sub?: string; at: number }[]; // at = cut frame of the chapter start
  speech?: [number, number][]; // final seconds
  cardSpans?: [number, number][]; // final seconds
  cardFrames?: number;
};

export const calculateFinalMetadata: CalculateMetadataFunction<FinalProps> = async (args) => {
  const base = await calculateMainMetadata(args as never);
  const props = base.props as FinalProps;
  const fps = base.fps as number;
  const total = base.durationInFrames as number;
  const plan = props.plan;
  const cardFrames = Math.round((plan?.chapterSeconds ?? 2) * fps);
  const chapters = (plan?.chapters ?? []).map((c) => ({ number: c.number, title: c.title, sub: c.sub, at: Math.round((c.at as number) * fps) })).sort((a, b) => a.at - b.at);
  const bounds = [0, ...chapters.map((c) => c.at), total];
  // a part that opens on a chapter card has an empty first segment: keep it as length 0, skipped when drawn
  const segments = bounds.slice(0, -1).map((s, i) => ({ start: s, end: bounds[i + 1] }));
  // speech spans on the final timeline (for music ducking)
  const words: CutWord[] = (await (await fetch(staticFile(`${props.project}/out/transcript_cut.json`))).json()).words;
  const shift = (cutSec: number) => cutSec + (chapters.filter((c) => c.at <= cutSec * fps + 0.5).length * cardFrames) / fps;
  const speech: [number, number][] = [];
  for (const w of words) {
    const s = shift(w.start), e = shift(w.end);
    const last = speech[speech.length - 1];
    if (last && s - last[1] < 0.45) last[1] = e;
    else speech.push([s, e]);
  }
  const cardSpans: [number, number][] = chapters.map((c, i) => {
    const s = (c.at + i * cardFrames) / fps;
    return [s, s + cardFrames / fps];
  });
  return {
    ...base,
    durationInFrames: total + chapters.length * cardFrames,
    props: { ...props, segments, cards: chapters, speech, cardSpans, cardFrames },
  };
};

const db = (x: number) => Math.pow(10, x / 20);

/** Music level (linear gain) at final time t: under speech ≈ -42 LUFS, pauses ≈ -37, chapter cards ≈ -32. */
const musicGain = (t: number, total: number, speech: [number, number][], cards: [number, number][], trackLufs: number, gainDb = 0,
  noFadeIn = false, noFadeOut = false) => {
  const norm = db(-20 - trackLufs + gainDb); // bring the track to -20 LUFS first (+ per-video trim)
  const inCard = cards.some(([a, b]) => t >= a - 0.1 && t <= b + 0.1);
  if (inCard) return norm * db(-12);
  // ducking with look-ahead (0.15 s) and release (0.6 s)
  let duck = 0;
  for (const [a, b] of speech) {
    if (t >= a - 0.15 && t <= b) { duck = 1; break; }
    if (t < a - 0.15) { duck = Math.max(duck, interpolate(a - t, [0.15, 0.45], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })); break; }
    if (t > b) duck = Math.max(duck, interpolate(t - b, [0, 0.6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  }
  const level = interpolate(duck, [0, 1], [-17, -22]); // relative to the -20 LUFS normalised track
  const fadeIn = noFadeIn ? 1 : interpolate(t, [0, 1.5], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = noFadeOut ? 1 : interpolate(t, [total - 3, total], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return norm * db(level) * fadeIn * fadeOut;
};

const Label: React.FC<{ text?: string }> = ({ text }) =>
  text ? (
    <div style={{ position: "absolute", top: 28, left: 28, padding: "10px 20px", borderRadius: 14, background: "rgba(0,0,0,0.72)", color: "#fff", fontFamily: theme.font, fontSize: 30, fontWeight: 800 }}>{text}</div>
  ) : null;

export const Final: React.FC<FinalProps> = (props) => {
  const { segments = [], cards = [], cardFrames = 50, speech = [], cardSpans = [] } = props;
  const Card = CHAPTER_CARDS[props.chapterStyle ?? props.plan?.chapterStyle ?? "default"] ?? CHAPTER_CARDS.default;
  const chapterSfx = props.plan?.chapterSfx;
  const music = props.music ?? props.plan?.music;
  const { fps, durationInFrames } = useVideoConfig();
  const sfxBase = props.plan?.sfxVolume ?? 0.125;
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <Series>
        {segments.map((sg, i) => (
          <React.Fragment key={i}>
            {i > 0 ? (
              <Series.Sequence durationInFrames={cardFrames}>
                <Card number={cards[i - 1].number} title={cards[i - 1].title} sub={cards[i - 1].sub} durationInFrames={cardFrames}
                  backdrop={<Freeze frame={sg.start}><Main {...props} silent /></Freeze>} />
                {chapterSfx ? (
                  <Sequence from={0} layout="none">
                    <Audio src={sfxUrl(chapterSfx)} volume={sfxBase * 0.9} startFrom={Math.round(0.6 * fps)} />
                  </Sequence>
                ) : null}
              </Series.Sequence>
            ) : null}
            {sg.end > sg.start ? (
              <Series.Sequence durationInFrames={sg.end - sg.start}>
                <Sequence from={-sg.start}>
                  <Main {...props} />
                </Sequence>
              </Series.Sequence>
            ) : null}
          </React.Fragment>
        ))}
      </Series>
      {music ? (
        <Audio src={staticFile(music.file)} startFrom={Math.round((props.musicFrom ?? 0) * fps)}
          volume={(f) => musicGain(f / fps, durationInFrames / fps, speech, props.cardAfter ? [...cardSpans, [durationInFrames / fps, durationInFrames / fps + cardFrames / fps]] : cardSpans, music.lufs, music.gainDb ?? 0, props.noFadeIn, props.noFadeOut)} />
      ) : null}
      <Label text={props.label} />
    </AbsoluteFill>
  );
};

export const useFinalFrame = () => useCurrentFrame();
