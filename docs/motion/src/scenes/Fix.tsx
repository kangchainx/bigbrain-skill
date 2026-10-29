import React from 'react';
import { Easing, interpolate } from 'remotion';
import { C, F } from '../theme';
import { Card, Receipt, Speaker, Words, clamp, pop, sp } from '../primitives';
import { P, useF } from './shared';

export const Fix: React.FC<P> = ({ t, zh, dur }) => {
  const { frame, fps } = useF();
  const merge = interpolate(frame, [22, 40], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const ok = sp(frame, fps, 40, 10), offer = sp(frame, fps, 56, 16);
  const ul = interpolate(frame, [70, 88], [0, 1], clamp);
  return (
    <Card dur={dur} side={-1}>
      <Speaker who='codex' name='Codex' role={t.codexRole} />
      <Words text={t.fix} start={4} size={zh ? 56 : 58} zh={zh} />
      <div style={{ position: 'relative', height: 230, marginTop: 34 }}>
        <Receipt p={1 - merge} x={150 - merge * 150} rot={5} tag={t.orderTag} />
        <Receipt p={1} x={0} rot={-6 + merge * 6} tag={t.orderTag} />
        <div style={{ ...pop(ok), position: 'absolute', left: 260, top: 60, display: 'flex', alignItems: 'center', gap: 20, fontFamily: F.sans, fontSize: 44, fontWeight: 700, color: C.ink }}>
          <span style={{ width: 64, height: 64, borderRadius: 32, background: C.lime, display: 'grid', placeItems: 'center' }}><svg width={34} height={34} viewBox={'0 0 34 34'}><path d={'M7 18 L14 25 L27 9'} stroke={C.ink} strokeWidth={5} fill={'none'} strokeLinecap={'round'} strokeLinejoin={'round'} /></svg></span>{t.one}
        </div>
      </div>
      <div style={{ ...pop(offer, 30), position: 'relative', display: 'inline-block', marginTop: 26, fontFamily: F.sans, fontSize: zh ? 40 : 42, fontWeight: 500, color: C.ink2 }}>
        {t.offer}
        <span style={{ position: 'absolute', left: 0, right: 0, bottom: -10, height: 0, borderTop: `3px dashed ${C.cobalt}`, transform: `scaleX(${ul})`, transformOrigin: 'left' }} />
      </div>
    </Card>
  );
};
