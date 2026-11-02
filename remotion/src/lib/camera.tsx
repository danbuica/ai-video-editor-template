import React from "react";
import { OffthreadVideo } from "remotion";

export type Card = {
  /** card box as fractions of the 1920x1080 frame */
  x: number;
  y: number;
  w: number;
  h: number;
  radius: number; // px
  /** camera crop inside the card (pipeline/tools/facecard.py measures these per recording) */
  faceX: number; // 0..1 horizontal centre of the face in the camera frame
  top: number; // 0..1 where the crop starts vertically in the camera frame
  zoom: number; // 1 = card height shows the full camera height
};

export const CAM_AR = 16 / 9;

/** Camera video cropped into a box of size (bw x bh) px, keeping the face at faceX. Zoom and top are relative to the
 *  box height, so any box with the same framing shows the face at the same size and headroom (face card, V2 PiP). */
export const CameraCrop: React.FC<{ src: string; bw: number; bh: number; card: Pick<Card, "faceX" | "top" | "zoom">; muted?: boolean }> = ({ src, bw, bh, card, muted }) => {
  const vh = bh * card.zoom; // rendered camera height
  const vw = vh * CAM_AR;
  let left = bw / 2 - card.faceX * vw;
  left = Math.min(0, Math.max(bw - vw, left));
  const top = -card.top * vh;
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <OffthreadVideo src={src} muted={muted} style={{ position: "absolute", left, top, width: vw, height: vh }} />
    </div>
  );
};

/** The current frame's face framing (Main provides it, faceKeys included), so graphics can centre the face like the card does. */
export const FaceContext = React.createContext<Card | null>(null);
