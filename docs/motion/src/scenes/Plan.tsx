import React from 'react';
import { Easing, interpolate } from 'remotion';
import { C, F } from '../theme';
import { Card, Speaker, Words, clamp, sp } from '../primitives';
import { P, useF } from './shared';

export const Plan: React.FC<P> = ({ t, zh, dur }) => {
  const { frame, fps } = useF();
  const bar = interpolate(frame, [62, 80], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <Card dur={dur} side={1}>
      <Speaker who='claude' name='Claude' role={t.claudeRole} />
      <Words text={t.plan} start={6} size={zh ? 58 : 62} zh={zh} family={F.serif} weight={500} />
      <div style={{ marginTop: 36, display: 'grid', gap: 18 }}>
        {t.steps.map((s, i) => {
          const p = Math.min(1, sp(frame, fps, 34 + i * 12, 14));
          const last = i === t.steps.length - 1;
          return (
            <div key={i} style={{ opacity: p, transform: `translateX(${(1 - p) * 80}px)`, display: 'flex', alignItems: 'center', gap: 20, fontFamily: F.sans, fontSize: 36, fontWeight: last ? 700 : 500, color: C.ink }}>
              <span style={{ width: 48, height: 48, flex: 'none', borderRadius: 24, display: 'grid', placeItems: 'center', fontSize: 26, fontWeight: 700, background: last ? C.lime : C.cobalt, color: last ? C.ink : C.tile }}>{i + 1}</span>
              <span style={{ position: 'relative' }}>{s}{last && <span style={{ position: 'absolute', left: 0, right: 0, bottom: -6, height: 6, borderRadius: 3, background: C.lime, transform: `scaleX(${bar})`, transformOrigin: 'left' }} />}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
};
