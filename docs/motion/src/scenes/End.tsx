import React from 'react';
import { AbsoluteFill } from 'remotion';
import { C, F } from '../theme';
import { pop, sp } from '../primitives';
import { P, useF } from './shared';

export const End: React.FC<P> = ({ t }) => {
  const { frame, fps } = useF();
  const a = sp(frame, fps, 8, 13), b = sp(frame, fps, 20, 16);
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ ...pop(a, 80), padding: '64px 110px', borderRadius: 44, background: 'rgba(250,247,240,0.86)', boxShadow: '0 50px 120px rgba(60,48,25,0.22)', textAlign: 'center' }}>
        <div style={{ fontFamily: F.serif, fontSize: 176, lineHeight: 1.05, letterSpacing: -5, color: C.ink }}>Bigbrain</div>
        <div style={{ ...pop(b, 30), marginTop: 22, fontFamily: F.sans, fontSize: 46, fontWeight: 500, color: C.ink2 }}>{t.end}</div>
      </div>
    </AbsoluteFill>
  );
};
