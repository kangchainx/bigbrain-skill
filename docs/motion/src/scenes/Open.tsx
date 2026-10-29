import React from 'react';
import { AbsoluteFill, Easing, interpolate } from 'remotion';
import { C, F } from '../theme';
import { clamp, pop, sp } from '../primitives';
import { P, useF } from './shared';

export const Open: React.FC<P> = ({ t, dur }) => {
  const { frame, fps } = useF();
  const a = sp(frame, fps, 6), b = sp(frame, fps, 16);
  const out = interpolate(frame, [dur - 14, dur], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  return (
    <AbsoluteFill style={{ alignItems: 'center', paddingTop: 120, opacity: 1 - out, transform: `translateY(${-out * 160}px)` }}>
      <div style={{ fontFamily: F.serif, fontSize: 168, lineHeight: 1.04, letterSpacing: -4, textAlign: 'center', color: C.ink }}>
        <div style={{ ...pop(a, 90), filter: `blur(${Math.max(0, 1 - a) * 12}px)` }}>{t.open[0]}</div>
        <div style={{ ...pop(b, 90), filter: `blur(${Math.max(0, 1 - b) * 12}px)`, color: C.cobalt, fontStyle: 'italic' }}>{t.open[1]}</div>
      </div>
    </AbsoluteFill>
  );
};
