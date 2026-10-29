import React from 'react';
import { Composition, Folder } from 'remotion';
import { Film } from './Film';
import { COPY } from './copy';
import { Open, Enable, Ask, Plan, Stuck, Diagnose, Fix, End } from './scenes';
import { FPS, TOTAL, SCENES } from './theme';

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id='BigbrainEN' component={Film} durationInFrames={TOTAL} fps={FPS} width={1920} height={1080} defaultProps={{ lang: 'en' as const }} />
    <Composition id='BigbrainZH' component={Film} durationInFrames={TOTAL} fps={FPS} width={1920} height={1080} defaultProps={{ lang: 'zh' as const }} />
    <Folder name="Scenes">
      <Composition id="Open" component={Open} durationInFrames={SCENES.open} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.open }} />
      <Composition id="Enable" component={Enable} durationInFrames={SCENES.enable} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.enable }} />
      <Composition id="Ask" component={Ask} durationInFrames={SCENES.ask} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.ask }} />
      <Composition id="Plan" component={Plan} durationInFrames={SCENES.plan} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.plan }} />
      <Composition id="Stuck" component={Stuck} durationInFrames={SCENES.stuck} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.stuck }} />
      <Composition id="Diagnose" component={Diagnose} durationInFrames={SCENES.diagnose} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.diagnose }} />
      <Composition id="Fix" component={Fix} durationInFrames={SCENES.fix} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.fix }} />
      <Composition id="End" component={End} durationInFrames={SCENES.end} fps={30} width={1920} height={1080} defaultProps={{ t: COPY.en, zh: false, dur: SCENES.end }} />
    </Folder>
  </>
);
