import React from 'react';
import { C, F } from '../theme';
import { Card, Receipt, Speaker, Words, sp } from '../primitives';
import { P, useF } from './shared';

export const Stuck: React.FC<P> = ({ t, zh, dur }) => {
  const { frame, fps } = useF();
  const r1 = sp(frame, fps, 30, 11), r2 = sp(frame, fps, 38, 11), c = sp(frame, fps, 48, 9);
  const shake = frame > 48 ? Math.sin(frame * 1.7) * 10 * Math.max(0, 1 - (frame - 48) / 24) : 0;
  return (
    <Card dur={dur} side={-1}>
      <Speaker who='codex' name='Codex' role={t.codexRole} />
      <Words text={t.stuck} start={6} size={zh ? 60 : 64} zh={zh} />
      <div style={{ position: 'relative', height: 240, marginTop: 40 }}>
        <Receipt p={r1} x={0} rot={-6} tag={t.orderTag} />
        <Receipt p={r2} x={150} rot={5} tag={t.orderTag} />
        <div style={{ position: 'absolute', left: 430, top: 30, display: 'flex', alignItems: 'baseline', gap: 18, color: C.red, fontFamily: F.sans, opacity: Math.min(1, c), transform: `translateX(${shake}px) scale(${0.8 + c * 0.2})` }}>
          <span style={{ fontSize: 170, fontWeight: 800, lineHeight: 1 }}>2</span>
          <span style={{ fontSize: 40, fontWeight: 600 }}>{t.orders}</span>
        </div>
      </div>
    </Card>
  );
};
