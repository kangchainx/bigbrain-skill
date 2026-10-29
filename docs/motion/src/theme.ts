export const C = {
  paper: '#FBF8F2', bg: '#EFE9DD', bg2: '#E2D9C6', tile: '#FAF7F0', line: '#DCD3C2',
  ink: '#1C1B18', ink2: '#45413A', muted: '#857E72',
  cobalt: '#2E4BD6', lime: '#B5D334', limeInk: '#6A8414', red: '#C2412D',
};
export const F = {
  serif: 'New York, Iowan Old Style, Songti SC, Georgia, serif',
  sans: '-apple-system, SF Pro Display, Helvetica Neue, PingFang SC, sans-serif',
  mono: 'SF Mono, Menlo, PingFang SC, monospace',
};
export const FPS = 30;
export const SCENES = { open: 66, enable: 78, ask: 96, plan: 114, stuck: 84, diagnose: 96, fix: 120, end: 66 };
export const TOTAL = Object.values(SCENES).reduce((a, b) => a + b, 0);
export const STARTS = (() => { let s = 0; return Object.values(SCENES).map((d) => { s += d; return s - d; }); })();
