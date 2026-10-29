import React from 'react';
import { C, F } from '../theme';
import { Card, Speaker, Words, pop, sp } from '../primitives';
import { P, useF } from './shared';

export const Ask: React.FC<P> = ({ t, zh, dur }) => {
  const { frame, fps } = useF();
  const chip = sp(frame, fps, 34, 12);
  return (
    <Card dur={dur} side={-1}>
      <Speaker who='codex' name='Codex' role={t.codexRole} />
      <Words text={t.ask} start={6} size={zh ? 60 : 66} zh={zh} />
      <div style={{ ...pop(chip), marginTop: 40, display: 'flex', alignItems: 'center', gap: 22 }}>
        <div style={{ padding: '18px 30px', borderRadius: 20, border: `3px dashed ${C.muted}`, fontFamily: F.sans, fontSize: 36, fontWeight: 600, color: C.ink2 }}>{t.task}</div>
        <div style={{ fontFamily: F.serif, fontSize: 96, lineHeight: 1, color: C.cobalt, transform: `rotate(${Math.sin(frame / 5) * 6 * Math.min(1, chip)}deg)` }}>?</div>
      </div>
    </Card>
  );
};
