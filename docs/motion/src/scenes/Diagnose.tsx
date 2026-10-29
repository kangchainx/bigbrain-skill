import React from 'react';
import { Easing, interpolate } from 'remotion';
import { C, F } from '../theme';
import { Card, Speaker, Words, clamp, sp } from '../primitives';
import { P, useF } from './shared';

export const Diagnose: React.FC<P> = ({ t, zh, dur }) => {
  const { frame, fps } = useF();
  const W = 820;
  const line = interpolate(frame, [28, 46], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const move = interpolate(frame, [50, 72], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const k = Math.min(1, sp(frame, fps, 40, 12));
  const kx = (0.86 - move * 0.72) * W - 60;
  return (
    <Card dur={dur} side={1}>
      <Speaker who='claude' name='Claude' role={t.claudeRole} />
      <Words text={t.diag} start={6} size={zh ? 58 : 60} zh={zh} family={F.serif} weight={500} />
      <div style={{ position: 'relative', width: W, height: 170, marginTop: 50 }}>
        <div style={{ position: 'absolute', left: 0, top: 70, width: W, height: 4, borderRadius: 2, background: C.ink, transform: `scaleX(${line})`, transformOrigin: 'left' }} />
        {t.marks.map((m, i) => (
          <div key={m} style={{ position: 'absolute', left: (i ? 0.86 : 0.14) * W - 100, top: 96, width: 200, textAlign: 'center', opacity: line, fontFamily: F.sans, fontSize: 28, color: C.muted }}>
            <div style={{ width: 16, height: 16, borderRadius: 8, background: C.ink, margin: '-34px auto 18px' }} />{m}
          </div>
        ))}
        <div style={{ position: 'absolute', left: 0.86 * W - 60, top: 6, width: 120, height: 48, boxSizing: 'border-box', borderRadius: 24, border: `2px dashed ${C.muted}`, opacity: move * 0.8 }} />
        <div style={{ position: 'absolute', left: 0, top: 6, width: 120, height: 48, borderRadius: 24, display: 'grid', placeItems: 'center', background: C.cobalt, color: C.tile, fontFamily: F.mono, fontSize: 26, fontWeight: 700, opacity: k, transform: `translate(${kx}px, ${(1 - k) * -40}px) rotate(${(move - move * move) * -24}deg)` }}>{t.key}</div>
      </div>
    </Card>
  );
};
