import React from "react";
import { MotionItem } from "../types";
import { SceneTitle } from "./SceneTitle";
import { TextPop } from "./TextPop";

/**
 * The graphics library: motion.json item `type` → component. This template ships two tiny examples so the engine
 * runs end to end. Add your own graphics here (one file each in this folder) and describe them in
 * .claude/skills/motion/SKILL.md so Claude knows when to use them.
 *
 * Each component gets `item` with every TimeRef already resolved to seconds on the cut timeline; use
 * useCurrentFrame()/fps to animate. Graphics draw over the full-screen talking head; "scene-*" types take the
 * whole frame (the head is blurred underneath).
 */
export const GRAPHICS: Record<string, React.FC<{ item: MotionItem }>> = {
  "text-pop": TextPop,
  "scene-title": SceneTitle,
};
