// Project-owned narrative adaptations of Shotcraft. Apache-2.0 reference cards and
// unchanged originals: vendor/video-shotcraft/2026-10-motion/SOURCES.json.
import React from 'react';
import {CodeVisual} from './CodeVisual';
import {AbsoluteFill, Img, Video, staticFile, useCurrentFrame} from 'remotion';
import type {Props} from './index';
import {Caption} from './Caption';
import {MediaMotion} from './MediaMotion';
import {BlurWords, headlineGroups, cubic, segment} from './motion';

export const NarrativeShot: React.FC<Props> = (p) => {
 const f = useCurrentFrame(), t = f / 30, plan = p.motionPlan!;
 const client = p.clientPresentation === true;
 const chrome = !client && !p.cleanPresentation;
 const polished = plan.visual_finish === 'polished-v1';
 const film = ['cinema', 'quiet'].includes(p.style), quiet = p.style === 'quiet';
 const study = ['lab', 'evidence', 'bauhaus'].includes(p.style);
 const social = ['social', 'collage', 'kinetic'].includes(p.style);
 const {paper, ink, accent} = p.brand;
 const stageColor = film ? '#171b17' : paper;
 const titleColor = client ? '#ffffff' : film ? '#f5eddf' : ink;
 const cue = plan.cue_frame, amount = plan.amount;
 const recipe = p.shotRecipe ?? 'none';
 const reveal = recipe === 'none' ? Number(f >= cue) : cubic(segment(f, cue, cue + 12));
 const rush = segment(f, cue, cue + 6), settle = segment(f, cue + 6, cue + 11);
 const titleScale = recipe === 'crash-zoom-punch' ? 1 + amount * (-.22 + .26 * rush - .04 * settle) : 1;
 const enter = p.transition === 'push-stack' ? 1 - cubic(segment(f, 0, 13)) : 0;
 const leave = p.exitTransition === 'push-stack' ? cubic(segment(f, p.frames - 14, p.frames - 1)) : 0;
 const slide = (enter - leave) * 1920;
 const titleTop = client ? 210 : film ? quiet ? 335 : 235 : study ? 195 : 165;
 const baseCardTop = film ? 420 : study ? 355 : 350;
 const cardTop = polished && p.titleLayout ? Math.max(baseCardTop, titleTop + p.titleLayout.height + 24) : baseCardTop;
 const mediaTop = polished && recipe === 'product-card-progressive-assemble' ? Math.max(study ? 460 : 440, cardTop + 90) : study ? 460 : 440;
 const mediaEffect = !p.codeVisual && ['product-detail-bracket','product-fact-row','product-hero-stage','product-explain-relay','product-brand-snap','media-punch-in','detail-dual-window','product-shape-reveal','product-type-mask','same-frame-panels'].includes(recipe);
 const mediaBox: React.CSSProperties = client ? {inset:0} : mediaEffect ? {left:40,right:40,top:Math.max(440,mediaTop),bottom:365} : film ? {inset: 0} : study ? {left: 64, right: 64, top: mediaTop, bottom: 365} : social ? {left: 0, right: 0, top: mediaTop, bottom: 0} : {left: 72, right: 72, top: 500, bottom: 350};
 const imageProgress = cubic(segment(f, 0, Math.max(1, p.frames - 25)));
 const zoom = p.motion === 'static' ? 1 : p.motion === 'pull' ? 1.1 - .1 * imageProgress : 1 + .1 * imageProgress;
 const pan = p.motion === 'pan_left' ? 28 - 56 * imageProgress : p.motion === 'pan_right' ? -28 + 56 * imageProgress : 0;
 const mediaStyle: React.CSSProperties = {width: '100%', height: '100%', objectFit: p.fit, objectPosition: `${p.focus_x * 100}% ${p.focus_y * 100}%`, ...(p.kind === 'image' ? {transform: `translateX(${pan}px) scale(${zoom})`, transformOrigin: `${p.focus_x * 100}% ${p.focus_y * 100}%`} : {})};
 const fontSize = p.titleLayout?.font_size ?? (film ? quiet ? 82 : 110 : study ? 94 : social ? 112 : 86);
 const focusReveal = cubic(segment(f, cue + 12, cue + 26));
 const scan = recipe === 'scanline-annotate-focus' ? segment(f, cue + 4, Math.max(cue + 5, Math.min(p.frames - 1, cue + 50))) : 0;
 const caption = p.captions.find(c => t >= c.start && t < c.end);
 const line = Math.max(p.transition === 'line-carry' ? 1 - cubic(segment(f, 0, 14)) : 0, p.exitTransition === 'line-carry' ? cubic(segment(f, p.frames - 15, p.frames - 1)) : 0);

 return <AbsoluteFill style={{background: stageColor, color: ink, fontFamily: '"PingFang SC","Heiti SC",sans-serif', overflow: 'hidden'}}>
  <div style={{position: 'absolute', inset: 0, background: stageColor, transform: `translateY(${slide}px)`}}>
   <div data-layer="continuous-footage" style={{position: 'absolute', ...mediaBox, overflow: 'hidden', opacity: 1, border: study && !client ? `2px solid ${accent}` : undefined}}>
    {mediaEffect ? <MediaMotion p={p} mediaStyle={mediaStyle}/> : p.codeVisual ? <CodeVisual data={p.codeVisual} style={mediaStyle}/> : p.kind === 'image' ? <Img src={staticFile(p.src)} style={mediaStyle}/> : <Video src={staticFile(p.src)} muted style={mediaStyle}/>}
    {(p.transition==='media-pass'||p.exitTransition==='media-pass')&&(()=>{
     const entry=p.transition==='media-pass'?1-cubic(segment(f,0,14)):0;
     const exit=p.exitTransition==='media-pass'?cubic(segment(f,p.frames-14,p.frames-1)):0;
     if(entry===0&&exit===0)return null;
     const x=entry>0?-115*(1-entry):115*(1-exit);
     return <div data-layer="media-pass" style={{position:'absolute',inset:'-5% -8%',transform:`translateX(${x}%)`,background:`linear-gradient(90deg,transparent,${accent} 8%,${paper} 18%,${paper} 90%,transparent)`,pointerEvents:'none'}}/>;
    })()}

    {!p.codeVisual && recipe === 'scanline-annotate-focus' && <>
     {scan > 0 && scan < 1 && <div style={{position: 'absolute', left: 0, right: 0, top: `${100 * scan}%`, height: 2, background: accent, opacity: .65}}/>}
     <div data-layer="focus" style={{position: 'absolute', left: `clamp(0px, calc(${100 * p.focus_x}% - 160px), calc(100% - 324px))`, top: `clamp(0px, calc(${100 * p.focus_y}% - 115px), calc(100% - 234px))`, width: 320, height: 230, opacity: focusReveal}}>
      {[0,1,2,3].map(k => <div key={k} style={{position: 'absolute', width: 44, height: 44, borderColor: accent, borderStyle: 'solid', borderWidth: 0, ...(k % 2 ? {right: 0, borderRightWidth: 3} : {left: 0, borderLeftWidth: 3}), ...(k > 1 ? {bottom: 0, borderBottomWidth: 3} : {top: 0, borderTopWidth: 3}), transform: `translate(${(k%2?1:-1)*18*(1-focusReveal)*amount}px, ${(k>1?1:-1)*18*(1-focusReveal)*amount}px)`}}/>)}
      <span style={{position: 'absolute', top: 8, left: 8, fontSize: 28, padding: '5px 10px', background: paper, color: ink, whiteSpace: 'nowrap'}}>{p.headline}</span>
     </div>
    </>}
   </div>
   {film && !client && <><div style={{position: 'absolute', left: 0, top: 0, right: 0, height: 600, background: 'linear-gradient(#171b17a8,#171b1700)'}}/><div style={{position: 'absolute', left: 0, bottom: 0, right: 0, height: 430, background: 'linear-gradient(#171b1700,#171b17cc)'}}/></>}
   {social && !client && <><div style={{position: 'absolute', left: 0, right: 0, top: 0, height: mediaTop, background: paper}}/><div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 340, background: 'linear-gradient(transparent,#1d2821cc)'}}/></>}
   {chrome && <div style={{position: 'absolute', left: 72, right: 72, top: 92, display: 'flex', justifyContent: 'space-between', fontSize: 28, letterSpacing: 3, color: film ? '#e9deca' : ink}}><span>{p.brand.name}</span><span>{study ? '观察 / ' : ''}{String(p.index).padStart(2,'0')} / {String(p.count).padStart(2,'0')}</span></div>}
   {(!client || recipe !== 'none' && !mediaEffect) && <div data-layer="narrative-title" style={{visibility:p.suppressTitle?'hidden':undefined,position: 'absolute', left: film ? 96 : 72, right: 72, top: titleTop, opacity: reveal, color: titleColor, fontSize, fontFamily: !client && (film || !study && !social) ? '"Songti SC","STSong",serif' : undefined, fontWeight: film ? 500 : social ? 800 : 700, lineHeight: 1.2, transform: `translateY(${recipe==='none'?0:(1-reveal)*24*amount}px) scale(${titleScale})`, transformOrigin: 'left center', textShadow:client?'0 3px 12px #0009':undefined}}>
    {p.titleLayout ? <Img src={p.titleLayout.image} alt={p.headline} style={{display:'block',width:p.titleLayout.width,height:p.titleLayout.height,maxWidth:'100%',objectFit:'contain'}}/> : recipe === 'blur-slide' ? <BlurWords groups={headlineGroups(p.headline)} frame={f} start={cue} size={fontSize} color={titleColor}/> : p.headline}
    {recipe === 'marker-underline-title' && p.headline && <svg data-layer="marker" viewBox="0 0 800 28" style={{display: 'block', width: Math.min(900, p.titleLayout?.width ?? Array.from(p.headline).length * fontSize), height: 28, marginTop: 15, transform: `scaleX(${cubic(segment(f,cue+18,cue+28))})`, transformOrigin: 'left'}}><path d="M5 20 Q120 9 260 17 T510 13 T795 7" stroke={accent} strokeWidth={6 + 3 * amount} strokeLinecap="round" fill="none"/><path d="M15 25 Q200 15 410 21 T790 13" stroke={accent} strokeWidth="2" opacity=".45" fill="none"/></svg>}
   </div>}
   {!p.codeVisual && recipe === 'product-card-progressive-assemble' && <div style={{position: 'absolute', top: cardTop, left: 72, right: 72, display: 'flex', gap: 16}}>{plan.beats.map((beat,i) => {
    const start = Math.max(cue + i*8, beat.frame), progress = cubic(segment(f,start,start+12));
    return <div key={i} data-layer="semantic-beat" style={{flex: 1, minWidth: 0, opacity: progress, padding: '13px 16px', fontSize: 32, fontWeight: 500, color: film ? '#f4ecdc' : ink, background: film ? '#171b17b8' : paper, borderBottom: `3px solid ${accent}`, transform: `translateY(${12*amount*(1-progress)}px)`, whiteSpace: 'nowrap'}}>{beat.text}</div>;
   })}</div>}
   {study && !client && <div style={{position: 'absolute', top: polished ? mediaTop - 40 : 420, left: 64, width: 952, height: 2, background: accent, opacity: .65}}/>}
  </div>
  {p.format !== 'showcase' && caption && <Caption caption={caption} style={{position: 'absolute', left: client?90:108, right: client?90:108, bottom: client?235:190, fontSize: p.brand.subtitle_size, lineHeight: 1.5, padding: client?'8px 0':'12px 18px', background: client?undefined:study ? ink : film ? '#171b17aa' : social ? '#23372ccb' : paper, borderRadius: film || social ? 8 : 0, textAlign: 'center',textShadow:client?'0 2px 6px #000b':undefined,zIndex:client||polished?30:undefined}}/>}
  {chrome && <div style={{position: 'absolute', left: 108, right: 108, bottom: 130, height: 2, background: film || social ? '#ffffff33' : ink+'33'}}><div style={{height: 2, background: film ? '#e9deca' : accent, width: `${100*(p.index-1+f/Math.max(1,p.frames-1))/p.count}%`}}/></div>}
  {chrome && p.preview && p.index === p.count && <div style={{position: 'absolute', left: 108, bottom: 82, fontSize: 25, color: film || social ? '#f6edde' : ink}}>实拍创意示例 · 待人工听核与审片</div>}
  {p.sample && <div style={{position: 'absolute', left: 108, bottom: 82, fontSize: 25, color: film || social ? '#f6edde' : ink}}>虚构商品 · AI示例画面 · 非实拍</div>}
  {(enter > 0 || leave > 0) && <div data-layer="push-stack" style={{position: 'absolute', left: 0, right: 0, height: 1920, top: enter > 0 ? slide-1920 : slide+1920, background: stageColor, boxShadow: '0 -20px 35px #0002', borderTop: `2px solid ${accent}`}}/>}
  {line > 0 && <div data-layer="line-carry" style={{position: 'absolute', left: 64, right: 64, top: study ? 1545 : 1470, height: 3, background: accent, transform: `scaleX(${line})`, transformOrigin: 'left'}}/>}
  {p.transition === 'wipe' && <div style={{position:'absolute',inset:0,background:stageColor,transform:`translateX(${1080*cubic(segment(f,0,12))}px)`}}/>}
  {p.exitTransition === 'wipe' && <div style={{position:'absolute',inset:0,background:stageColor,transform:`translateX(${-1080+1080*cubic(segment(f,p.frames-12,p.frames-1))}px)`}}/>}
  {(p.transition === 'iris' || p.exitTransition === 'iris') && [0,1].map(side => {const close=Math.max(p.transition==='iris'?1-cubic(segment(f,0,24)):0,p.exitTransition==='iris'?segment(f,p.frames-12,p.frames-1):0);return <div key={side} style={{position:'absolute',left:0,right:0,height:960*close,background:stageColor,...(side?{bottom:0}:{top:0})}}/>;})}
 </AbsoluteFill>;
};
