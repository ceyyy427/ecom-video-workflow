import React from 'react';
import type {Props} from './index';
import {NarrativeShot} from './NarrativeShot';

// Reuse the complete recipe and transition renderer; presentation must not
// silently discard effects or create an independent sound clock.
export const ClientShot: React.FC<Props> = (p) => {
 if (!p.motionPlan && p.shotRecipe && p.shotRecipe !== 'none') {
  throw new Error('客户成片动效需要声音与动作编排，请补齐动效计划或保留历史样式');
 }
 return <NarrativeShot {...p} clientPresentation shotRecipe={p.shotRecipe ?? 'none'} motionPlan={p.motionPlan ?? {version:2,amount:0,cue_frame:0,intent:'plain',strength:'subtle',guard_outcome:'no_motion',beats:[]}}/>;
};
