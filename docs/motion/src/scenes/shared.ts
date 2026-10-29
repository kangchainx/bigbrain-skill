import { useCurrentFrame, useVideoConfig } from 'remotion';
import type { Copy } from '../copy';
export type P = { t: Copy; zh: boolean; dur: number };
export const useF = () => ({ frame: useCurrentFrame(), fps: useVideoConfig().fps });
