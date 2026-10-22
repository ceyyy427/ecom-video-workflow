// Project-owned real-media choreography, from pinned Shotcraft/Huashu methods.
// No generated product geometry, source retiming, stochastic values or audio tracks.
import React from 'react';
import {Img, Video, staticFile, useCurrentFrame} from 'remotion';
import type {Props} from './index';
import {cubic, segment} from './motion';

export const MediaMotion: React.FC<{p: Props; mediaStyle: React.CSSProperties}> = ({p, mediaStyle}) => {
 const f=useCurrentFrame(), plan=p.motionPlan!, cue=plan.cue_frame;
 const spec=plan.presentation??{zoom:1.18,travel_frames:12,shape:'rounded'};
 const media=(style:React.CSSProperties)=>p.kind==='image'?<Img src={staticFile(p.src)} style={style}/>:<Video src={staticFile(p.src)} muted style={style}/>;
 const origin=`${100*p.focus_x}% ${100*p.focus_y}%`;
 const progress=cubic(segment(f,cue,cue+spec.travel_frames));
 if(p.shotRecipe==='product-detail-bracket'){
  const back=cubic(segment(f,cue+spec.travel_frames+30,cue+spec.travel_frames+44));
  const amount=progress*(1-back), x=Math.max(0,Math.min(68,p.focus_x*100-16)),y=Math.max(0,Math.min(68,p.focus_y*100-16));
  return <div data-layer="product-detail-bracket" style={{position:'absolute',inset:0}}>
   {media(mediaStyle)}
   <div style={{position:'absolute',left:`${x}%`,top:`${y}%`,width:'32%',height:'32%',opacity:amount}}>
    {[0,1,2,3].map(k=><div key={k} style={{position:'absolute',width:40,height:40,borderStyle:'solid',borderColor:p.brand.accent,borderWidth:0,...(k%2?{right:0,borderRightWidth:4}:{left:0,borderLeftWidth:4}),...(k>1?{bottom:0,borderBottomWidth:4}:{top:0,borderTopWidth:4}),opacity:cubic(segment(f,cue+k*3,cue+k*3+spec.travel_frames))*(1-back),transform:`translate(${(k%2?1:-1)*14*(1-progress)}px,${(k>1?1:-1)*14*(1-progress)}px)`}}/>)}
   </div>
   {amount>0&&!p.clientPresentation&&<span style={{position:'absolute',left:20,top:20,padding:'4px 10px',fontSize:24,background:p.brand.paper,color:p.brand.ink,opacity:amount}}>文稿焦点 · 人工核对</span>}
  </div>;
 }
 if(p.shotRecipe==='product-fact-row'){
  const amount=progress*(1-cubic(segment(f,p.frames-12,p.frames-1))),quote=plan.quote;
  return <div data-layer="product-fact-row" style={{position:'absolute',inset:0,background:p.brand.paper}}>
   <div style={{position:'absolute',inset:0,bottom:quote?`${30*amount}%`:0,overflow:'hidden'}}>{media(mediaStyle)}</div>
   {quote&&amount>0&&<div style={{position:'absolute',left:'5%',right:'5%',bottom:'3%',height:'24%',padding:'8px 16px',boxSizing:'border-box',opacity:amount,color:p.brand.ink,borderBottom:`3px solid ${p.brand.accent}`,transform:`perspective(900px) translateY(${-35*(1-progress)}px) rotateX(${12*(1-progress)}deg)`,transformOrigin:'center bottom'}}>
    {!p.clientPresentation&&<div style={{fontSize:24,marginBottom:10}}>引用原文 · 条件须人工核对</div>}
    <div style={{fontSize:40,lineHeight:1.35,overflowWrap:'anywhere'}}>{quote.text}</div>
   </div>}
  </div>;
 }
 if(['product-hero-stage','product-explain-relay','product-brand-snap'].includes(p.shotRecipe??'')){
  const back=cubic(segment(f,cue+spec.travel_frames+30,cue+2*spec.travel_frames+30)), amount=progress*(1-back);
  const relay=p.shotRecipe==='product-explain-relay';
  const beats=plan.beats.filter(b=>b.frame<=f && f>=cue), beat=beats[beats.length-1];
  // Relay text is a confirmed excerpt, never a synthetic product claim. Its
  // word clock stays separate from subtitles; only one excerpt can be visible.
  const relayEnd=Math.max(cue+2*spec.travel_frames+30,...plan.beats.map(b=>b.frame+24));
  const active=relay?f>=cue && f<relayEnd:amount>0;
  const inset=active?(relay?5:p.shotRecipe==='product-hero-stage'?3*amount:100*(spec.zoom-1)*amount):0;
  const entry=beat?cubic(segment(f,Math.max(cue,beat.frame),Math.max(cue,beat.frame)+8)):0;
  return <div data-layer={p.shotRecipe} style={{position:'absolute',inset:0,overflow:'hidden',background:relay?p.brand.paper:p.brand.accent}}>
   {p.shotRecipe==='product-hero-stage' && <div style={{position:'absolute',inset:0,background:`radial-gradient(ellipse at 50% 40%, ${p.brand.paper}, ${p.brand.accent})`}}/>}
   <div style={{position:'absolute',left:`${inset}%`,right:`${inset}%`,top:`${inset}%`,bottom:relay&&active?'22%':`${inset}%`,overflow:'hidden',borderRadius:active?20:0,boxShadow:p.shotRecipe==='product-hero-stage'&&active?'0 20px 45px #0004':undefined}}>{media(p.shotRecipe==='product-hero-stage'?{...mediaStyle,transform:`scale(${1+(spec.zoom-1)*amount})`,transformOrigin:origin}:mediaStyle)}</div>
   {relay&&active&&beat && <div style={{position:'absolute',left:'6%',right:'6%',bottom:'3%',height:'15%',display:'flex',alignItems:'center',gap:16,color:p.brand.ink,opacity:entry,transform:`translateY(${12*(1-entry)}px)`,fontSize:36,fontWeight:700}}><span style={{width:6,height:'75%',background:p.brand.accent,flexShrink:0}}/>{beat.text}</div>}
  </div>;
 }
 if(p.shotRecipe==='product-type-mask'){
  if(f<cue || progress>=1) return <div data-layer="product-type-mask" style={{position:'absolute',inset:0}}>{media(mediaStyle)}</div>;
  const id=`product-type-mask-${p.index}`, scale=1+(spec.zoom-1)*progress*progress*progress;
  return <div data-layer="product-type-mask" style={{position:'absolute',inset:0,overflow:'hidden'}}>
   <div style={{position:'absolute',inset:0,opacity:.4}}>{media(mediaStyle)}</div>
   <svg width="0" height="0" aria-hidden="true"><defs><clipPath id={id} clipPathUnits="objectBoundingBox"><text x=".5" y=".57" textAnchor="middle" fontSize=".24" fontWeight="900" fontFamily="PingFang SC,sans-serif" textLength=".88" lengthAdjust="spacingAndGlyphs" transform={`translate(.5 .5) scale(${scale}) translate(-.5 -.5)`}>{Array.from(p.headline).slice(0,8).join('')}</text></clipPath></defs></svg>
   <div style={{position:'absolute',inset:0,clipPath:`url(#${id})`}}>{media(mediaStyle)}</div>
  </div>;
 }
 if(p.shotRecipe==='same-frame-panels'){
  const back=cubic(segment(f,cue+spec.travel_frames+24,cue+2*spec.travel_frames+24)), amount=progress*(1-back);
  if(f<cue || back>=1) return <div data-layer="same-frame-panels" style={{position:'absolute',inset:0}}>{media(mediaStyle)}</div>;
  return <div data-layer="same-frame-panels" style={{position:'absolute',inset:0,overflow:'hidden'}}>
   {media(mediaStyle)}
   {[0,1].map(side=><div key={side} style={{position:'absolute',inset:0,opacity:amount,clipPath:side?'polygon(72% 0%,100% 0%,100% 100%,60% 100%)':'polygon(0% 0%,40% 0%,28% 100%,0% 100%)',transform:`translateX(${(side?1:-1)*40*(1-amount)}%)`}}><div style={{position:'absolute',inset:0,transform:`scale(${spec.zoom})`,transformOrigin:origin}}>{media(mediaStyle)}</div></div>)}
   {!p.clientPresentation&&<span style={{position:'absolute',left:16,top:16,fontSize:24,padding:'5px 10px',color:p.brand.ink,background:p.brand.paper,opacity:amount}}>同帧取景</span>}
  </div>;
 }
 if(p.shotRecipe==='media-punch-in'){
  const back=cubic(segment(f,cue+spec.travel_frames+36,cue+spec.travel_frames+54));
  const zoom=1+(spec.zoom-1)*progress*(1-back);
  return <div data-layer="media-punch" style={{position:'absolute',inset:0,overflow:'hidden'}}><div style={{position:'absolute',inset:0,transform:`scale(${zoom})`,transformOrigin:origin}}>{media(mediaStyle)}</div></div>;
 }
 if(p.shotRecipe==='detail-dual-window'){
  const fade=progress*(1-cubic(segment(f,p.frames-12,p.frames-1)));
  const gap=12, wholeHeight=100-36*fade;
  return <div data-layer="detail-dual" style={{position:'absolute',inset:0,overflow:'hidden'}}>
   <div data-view="whole" style={{position:'absolute',top:0,left:0,right:0,height:`${wholeHeight}%`,overflow:'hidden'}}>{media(mediaStyle)}</div>
   <div data-view="detail" style={{position:'absolute',left:0,right:0,bottom:0,height:`calc(${36*fade}% - ${gap}px)`,minHeight:0,opacity:fade,overflow:'hidden',borderTop:`2px solid ${p.brand.accent}`,background:p.brand.paper}}>
    <div style={{position:'absolute',inset:0,transform:`scale(${spec.zoom})`,transformOrigin:origin}}>{media({...mediaStyle,objectFit:'cover'})}</div>
    {!p.clientPresentation&&<span style={{position:'absolute',left:16,top:12,fontSize:24,padding:'5px 10px',color:p.brand.ink,background:p.brand.paper}}>同帧细节视图</span>}
   </div>
  </div>;
 }
 if(f<cue || progress>=1) return <div data-layer="shape-reveal" style={{position:'absolute',inset:0}}>{media(mediaStyle)}</div>;
 const inset=28*(1-progress), radius=18+110*progress;
 const mask=spec.shape==='circle'?`circle(${radius}% at ${p.focus_x*100}% ${p.focus_y*100}%)`:spec.shape==='diagonal'?`polygon(0% 0%, ${55+45*progress}% 0%, ${35+65*progress}% 100%, 0% 100%)`:`inset(${inset}% ${inset}% round ${36*(1-progress)}px)`;
 return <div data-layer="shape-reveal" style={{position:'absolute',inset:0,overflow:'hidden'}}>
  <div style={{position:'absolute',inset:0,opacity:.28}}>{media(mediaStyle)}</div>
  <div style={{position:'absolute',inset:0,clipPath:mask}}>{media(mediaStyle)}</div>
 </div>;
};
