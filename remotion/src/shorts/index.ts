import React from "react";
import type { Shot, VisualProps } from "../ShortV2";
import { exampleShots, ExampleVisual } from "./example";

/**
 * Content for "fast" shorts (ShortV2): per short (or per kind of short), the shot list and the visual drawn in the
 * "full" and "split" boxes. Add your own here; describe them in .claude/skills/shorts/SKILL.md.
 */
export type ShortContent = { shots: (variant?: "yt" | "ig") => Shot[]; Visual: React.FC<VisualProps> };

export const SHORTS: Record<string, ShortContent> = {
  example: { shots: exampleShots, Visual: ExampleVisual },
};
