import React from 'react';
import { Audio } from '@remotion/media';
import { AbsoluteFill, Series, staticFile, useVideoConfig } from 'remotion';
import { COPY, Lang } from './copy';
import { C, SCENES as S } from './theme';
import { Note, Particles, Plane } from './primitives';
import { Ask, Diagnose, Enable, End, Fix, Open, Plan, Stuck } from './scenes';

export const Film: React.FC<{ lang: Lang }> = ({ lang }) => {
  const { fps } = useVideoConfig();
  const t = COPY[lang];
  const zh = lang === 'zh';
  return (
    <AbsoluteFill style={{ background: `radial-gradient(120% 90% at 50% 0%, ${C.paper} 0%, ${C.bg} 55%, ${C.bg2} 100%)` }}>
      <Audio name="City Loop · CC0" src={staticFile("audio/city-loop-24s.mp3")} durationInFrames={24 * fps} premountFor={fps} />
      <Plane />
      <Particles />
      <Series>
        <Series.Sequence name="Open" durationInFrames={S.open} premountFor={fps}><Open t={t} zh={zh} dur={S.open} /></Series.Sequence>
        <Series.Sequence name="Enable" durationInFrames={S.enable} premountFor={fps}><Enable t={t} zh={zh} dur={S.enable} /></Series.Sequence>
        <Series.Sequence name="Ask" durationInFrames={S.ask} premountFor={fps}><Ask t={t} zh={zh} dur={S.ask} /></Series.Sequence>
        <Series.Sequence name="Plan" durationInFrames={S.plan} premountFor={fps}><Plan t={t} zh={zh} dur={S.plan} /></Series.Sequence>
        <Series.Sequence name="Stuck" durationInFrames={S.stuck} premountFor={fps}><Stuck t={t} zh={zh} dur={S.stuck} /></Series.Sequence>
        <Series.Sequence name="Diagnose" durationInFrames={S.diagnose} premountFor={fps}><Diagnose t={t} zh={zh} dur={S.diagnose} /></Series.Sequence>
        <Series.Sequence name="Fix" durationInFrames={S.fix} premountFor={fps}><Fix t={t} zh={zh} dur={S.fix} /></Series.Sequence>
        <Series.Sequence name="End" durationInFrames={S.end} premountFor={fps}><End t={t} zh={zh} dur={S.end} /></Series.Sequence>
      </Series>
      <Note text={t.note} />
    </AbsoluteFill>
  );
};
