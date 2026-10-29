import React from 'react';
import { AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { C, F, STARTS, TOTAL } from './theme';

export const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;
export const sp = (frame: number, fps: number, delay = 0, damping = 15) =>
  spring({ frame: frame - delay, fps, config: { damping, stiffness: 110, mass: 0.9 } });
export const pop = (p: number, dy = 40) => ({ opacity: Math.min(1, p), transform: `translateY(${(1 - p) * dy}px) scale(${0.94 + p * 0.06})` });

const COLS = 22, ROWS = 12, T = 210, G = 34;
const W = COLS * (T + G), H = ROWS * (T + G);

const Glyph: React.FC<{ kind: number; accent: string; seed: string }> = ({ kind, accent, seed }) => {
  const s = { stroke: C.ink2, strokeWidth: 3, fill: 'none', strokeLinecap: 'round' as const };
  return (
    <svg viewBox={'0 0 100 100'} width={'100%'} height={'100%'} style={{ padding: 36, boxSizing: 'border-box', opacity: 0.72 }}>
      {kind === 0 && [30, 20, 10].map((r, i) => <circle key={r} cx={50} cy={50} r={r} {...s} stroke={i === 1 ? accent : C.ink2} />)}
      {kind === 1 && [0, 1, 2, 3, 4, 5].map((i) => { const h = 20 + random(seed + i) * 62; return <rect key={i} x={8 + i * 15} y={92 - h} width={7} height={h} rx={3} fill={i === 3 ? accent : C.ink2} />; })}
      {kind === 2 && Array.from({ length: 25 }, (_, i) => <circle key={i} cx={14 + (i % 5) * 18} cy={14 + Math.floor(i / 5) * 18} r={4} fill={random(seed + i) > 0.72 ? accent : C.muted} />)}
      {kind === 3 && [0, 1, 2].map((i) => <line key={i} x1={10} x2={i === 2 ? 60 : 90} y1={30 + i * 20} y2={30 + i * 20} {...s} strokeWidth={7} stroke={i === 2 ? accent : C.ink2} />)}
      {kind === 4 && <path d={'M5 50 C 20 12, 35 12, 50 50 S 80 88, 95 50'} {...s} stroke={accent} strokeWidth={4} />}
    </svg>
  );
};

export const Plane: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const K = [0, 30, ...STARTS.slice(1), TOTAL];
  const io = { ...clamp, easing: Easing.inOut(Easing.cubic) };
  const rx = interpolate(f, K, [74, 58, 54, 52, 54, 52, 54, 52, 50, 40], io);
  const rz = interpolate(f, K, [-26, -18, -16, -14, -16, -14, -16, -14, -12, -4], io);
  const x = interpolate(f, K, [0, 0, -240, -480, -720, -960, -1200, -1440, -1680, -840], io);
  const z = interpolate(f, K, [-1600, -300, -150, -150, -150, -150, -150, -150, -150, -700], io);
  const endAt = STARTS[7];
  const blur = interpolate(f, [56, 90, endAt, endAt + 30], [0, 2.5, 2.5, 0], clamp);
  const cx = (COLS - 1) / 2, cy = (ROWS - 1) / 2;
  const tiles = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const d = Math.hypot(c - cx, r - cy);
      const id = `${r}-${c}`;
      const rise = Math.min(1, sp(f, fps, 2 + d * 1.4, 14));
      const wave = interpolate(f - endAt - 6 - d * 2.2, [0, 8, 26], [0, 1, 0], clamp);
      const accent = random('a' + id) > 0.5 ? C.cobalt : C.limeInk;
      tiles.push(
        <div key={id} style={{ position: 'absolute', left: c * (T + G), top: r * (T + G), width: T, height: T, borderRadius: 28, background: C.tile, opacity: rise, transform: `translateZ(${(1 - rise) * -380 + wave * 70}px)`, boxShadow: `0 ${10 + wave * 30}px ${24 + wave * 40}px rgba(70,55,30,${0.1 + wave * 0.1}), inset 0 0 0 ${wave * 5}px ${accent}` }}>
          <Glyph kind={Math.floor(random('k' + id) * 5)} accent={accent} seed={id} />
        </div>
      );
    }
  }
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ perspective: 1600, perspectiveOrigin: '50% 20%', filter: `blur(${blur}px)` }}>
        <div style={{ position: 'absolute', left: '50%', top: '64%', width: W, height: H, transformStyle: 'preserve-3d', transform: `translate(-50%, -50%) translateZ(${z}px) rotateX(${rx}deg) rotateZ(${rz}deg) translateX(${x}px)` }}>{tiles}</div>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${C.paper} 0%, rgba(251,248,242,0.85) 20%, rgba(251,248,242,0) 46%)` }} />
    </AbsoluteFill>
  );
};

export const Particles: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill>
      {Array.from({ length: 36 }, (_, i) => {
        const r = (n: string) => random(`p${i}${n}`);
        const depth = 0.4 + r('d') * 0.9;
        const size = 3 + r('s') * 6;
        const x = (((r('x') * 2100 - f * 1.2 * depth) % 2100) + 2100) % 2100 - 90;
        const y = (((r('y') * 1180 - f * 0.9 * depth) % 1180) + 1180) % 1180 - 50;
        const col = i % 3 === 0 ? C.cobalt : i % 3 === 1 ? C.lime : C.muted;
        return <div key={i} style={{ position: 'absolute', left: x, top: y, width: size, height: size, borderRadius: '50%', background: col, opacity: 0.18 + depth * 0.25, filter: `blur(${depth < 0.7 ? 1.5 : 0}px)` }} />;
      })}
    </AbsoluteFill>
  );
};

export const Card: React.FC<{ dur: number; side: -1 | 0 | 1; width?: number; children: React.ReactNode }> = ({ dur, side, width = 1060, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = sp(frame, fps, 0, 17);
  const out = interpolate(frame, [dur - 14, dur], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const x = (1 - p) * 1300 - out * 1500 + side * 300;
  const ry = (1 - p) * -30 + out * 26 + side * -7;
  const z = (1 - p) * -500 - out * 300;
  return (
    <AbsoluteFill style={{ perspective: 1800, alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width, boxSizing: 'border-box', padding: '56px 64px', borderRadius: 36, background: C.tile, border: '1px solid rgba(255,255,255,0.85)', boxShadow: '0 40px 90px rgba(60,48,25,0.18), 0 6px 18px rgba(60,48,25,0.10)', opacity: Math.min(1, p * 1.5) * (1 - out), transform: `translate3d(${x}px, ${(1 - p) * 60}px, ${z}px) rotateY(${ry}deg) rotateX(${(1 - p) * 10}deg)` }}>{children}</div>
    </AbsoluteFill>
  );
};

export const Words: React.FC<{ text: string; start?: number; size: number; zh?: boolean; family?: string; weight?: number; color?: string }> = ({ text, start = 0, size, zh, family = F.sans, weight = 600, color = C.ink }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const parts = zh ? Array.from(text) : text.split(' ');
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', columnGap: zh ? 0 : size * 0.26, fontFamily: family, fontSize: size, fontWeight: weight, color, lineHeight: 1.18, letterSpacing: zh ? 0 : -size * 0.015 }}>
      {parts.map((w, i) => { const q = sp(frame, fps, start + i * (zh ? 1.2 : 2.6), 18); return <span key={i} style={{ display: 'inline-block', opacity: Math.min(1, q), transform: `translateY(${(1 - q) * size * 0.5}px)`, filter: `blur(${Math.max(0, 1 - q) * 8}px)` }}>{w}</span>; })}
    </div>
  );
};

export const Speaker: React.FC<{ who: 'claude' | 'codex' | 'you'; name: string; role?: string }> = ({ who, name, role }) => {
  const badge = who === 'claude'
    ? <div style={{ width: 72, height: 72, borderRadius: 36, background: C.cobalt, display: 'grid', placeItems: 'center' }}><svg width={40} height={40} viewBox={'0 0 40 40'}>{[0, 30, 60, 90, 120, 150].map((a) => <line key={a} x1={20} y1={4} x2={20} y2={36} stroke={C.tile} strokeWidth={4} strokeLinecap={'round'} transform={`rotate(${a} 20 20)`} />)}</svg></div>
    : who === 'codex'
      ? <div style={{ width: 72, height: 72, borderRadius: 18, background: C.ink, color: C.lime, fontFamily: F.mono, fontSize: 30, fontWeight: 700, display: 'grid', placeItems: 'center' }}>{'>_'}</div>
      : <div style={{ width: 72, height: 72, borderRadius: 36, border: `3px solid ${C.ink}`, boxSizing: 'border-box', display: 'grid', placeItems: 'center' }}><div style={{ width: 22, height: 22, borderRadius: 11, background: C.ink }} /></div>;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 22, marginBottom: 34 }}>
      {badge}
      <div>
        <div style={{ fontFamily: F.sans, fontSize: 36, fontWeight: 700, color: C.ink }}>{name}</div>
        {role && <div style={{ fontFamily: F.sans, fontSize: 26, color: C.muted, marginTop: 2 }}>{role}</div>}
      </div>
    </div>
  );
};

export const Receipt: React.FC<{ p: number; x: number; rot: number; tag: string }> = ({ p, x, rot, tag }) => (
  <div style={{ position: 'absolute', left: 0, top: 0, width: 180, height: 220, boxSizing: 'border-box', padding: 24, borderRadius: 20, background: C.tile, border: `1px solid ${C.line}`, boxShadow: '0 20px 40px rgba(60,48,25,0.16)', opacity: Math.min(1, p), transform: `translate(${x}px, ${(1 - p) * -120}px) rotate(${rot * p}deg)` }}>
    <div style={{ fontFamily: F.mono, fontSize: 24, color: C.muted, marginBottom: 22 }}>{tag}</div>
    {[100, 80, 60].map((w) => <div key={w} style={{ width: `${w}%`, height: 10, borderRadius: 5, background: C.line, marginBottom: 16 }} />)}
  </div>
);

export const Note: React.FC<{ text: string }> = ({ text }) => (
  <div style={{ position: 'absolute', left: 64, bottom: 44, padding: '10px 20px', borderRadius: 999, background: 'rgba(250,247,240,0.82)', fontFamily: F.sans, fontSize: 26, color: C.muted }}>{text}</div>
);
