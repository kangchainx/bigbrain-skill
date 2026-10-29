import React from 'react';
import { interpolate } from 'remotion';
import { C, F } from '../theme';
import { Card, Speaker, clamp, pop, sp } from '../primitives';
import { P, useF } from './shared';

export const Enable: React.FC<P> = ({ t, dur }) => {
  const { frame, fps } = useF();
  const chars = Array.from(t.prompt);
  const n = Math.round(interpolate(frame, [14, 44], [0, chars.length], clamp));
  const on = sp(frame, fps, 50, 12);
  return (
    <Card dur={dur} side={0} width={1180}>
      <Speaker who='you' name={t.you} />
      <div style={{ display: 'flex', alignItems: 'center', padding: '30px 36px', borderRadius: 24, background: C.bg, fontFamily: F.mono, fontSize: 50, color: C.ink }}>
        {chars.slice(0, n).join('')}
        <span style={{ width: 22, height: 54, marginLeft: 6, background: C.cobalt, opacity: frame % 16 < 9 ? 1 : 0.15 }} />
      </div>
      <div style={{ ...pop(on), marginTop: 30, display: 'inline-flex', alignItems: 'center', gap: 16, padding: '16px 28px', borderRadius: 999, background: C.ink, color: C.tile, fontFamily: F.sans, fontSize: 32, fontWeight: 600 }}>
        <span style={{ width: 18, height: 18, borderRadius: 9, background: C.lime }} />{t.on}
      </div>
    </Card>
  );
};
