// Shotcraft-inspired, project-owned vertical adaptations (2026-10-18).
// References: vendor/video-shotcraft/2026-10-motion/SOURCES.json, Apache-2.0.
// No upstream demo brands, prices, footage, fonts or audio are reused.
import React from 'react';
import {AbsoluteFill,Img,Video,staticFile,useCurrentFrame} from 'remotion';
import type {Props} from './index';
import {Caption} from './Caption';
import {BlurWords,headlineGroups,cubic,segment} from './motion';
import {NarrativeShot} from './NarrativeShot';

const LegacyRecipeShot:React.FC<Props>=(p)=>{
 const f=useCurrentFrame(), t=f/30, recipe=p.shotRecipe??'none';
 const punch=['kinetic','bauhaus'].includes(p.style), calm=['editorial','quiet','cinema'].includes(p.style);
 const lab=['evidence','lab'].includes(p.style), social=['collage','social'].includes(p.style);
 const {ink,paper,accent}=p.brand;
 const prefix=p.text.slice(0,Math.max(0,p.text.indexOf(p.headline)));
 const offset=Array.from(prefix).filter(c=>/[\p{L}\p{N}]/u.test(c)).length;
 const at=p.format==='showcase'?8:Math.max(0,(p.words[offset]?.start??p.voiceStart)*30);
 const reveal=recipe==='none'?(f>=at?1:0):cubic(segment(f,at,at+12));
 const titleSize=calm?88:punch?116:100;
 const rush=segment(f,at,at+6),settle=segment(f,at+6,at+11);
 const titleScale=recipe==='crash-zoom-punch'?(.72+.34*rush-.06*settle):1;
 const caption=p.captions.find(c=>t>=c.start&&t<c.end);
 const assemble=recipe==='product-card-progressive-assemble';
 const mediaAt=assemble?cubic(segment(f,Math.max(0,at-8),at+8)):1;
 const imageMove=cubic(segment(f,0,Math.max(1,p.frames-25)));
 const zoom=p.motion==='static'?1:p.motion==='pull'?1.10-.1*imageMove:1+.1*imageMove;
 const pan=p.motion==='pan_left'?28-56*imageMove:p.motion==='pan_right'?-28+56*imageMove:0;
 const css:React.CSSProperties={width:'100%',height:'100%',objectFit:p.fit,objectPosition:`${p.focus_x*100}% ${p.focus_y*100}%`,...(p.kind==='image'?{transform:`translateX(${pan}px) scale(${zoom})`,transformOrigin:`${p.focus_x*100}% ${p.focus_y*100}%`}:{})};
 const media=p.kind==='image'?<Img src={staticFile(p.src)} style={css}/>:<Video src={staticFile(p.src)} muted style={css}/>;
 // Brand-plate bridges preserve independent scene caches and the whole-film voice clock.
 // These are short adaptations, not the upstream overlapping-scene / continuous-world demos.
 const enter=p.transition==='push-stack'?1-cubic(segment(f,0,13)):0;
 const leave=p.exitTransition==='push-stack'?cubic(segment(f,p.frames-14,p.frames-1)):0;
 const slide=1920*(enter-leave);
 const lineIn=p.transition==='line-carry'?1-cubic(segment(f,0,14)):0;
 const lineOut=p.exitTransition==='line-carry'?cubic(segment(f,p.frames-15,p.frames-1)):0;
 const scan=recipe==='scanline-annotate-focus'?segment(f,at+8,Math.max(at+9,Math.min(p.frames-1,at+60))):0;
 const focusReveal=cubic(segment(f,at+20,at+32));
 return <AbsoluteFill style={{background:paper,color:ink,fontFamily:'"PingFang SC","Heiti SC",sans-serif',overflow:'hidden'}}>
  <div data-layer="recipe-stage" style={{position:'absolute',inset:0,background:paper,transform:`translateY(${slide}px)`}}>
   {punch&&<div style={{position:'absolute',left:0,right:0,top:0,height:440,background:accent}}/>}
   {social&&<div style={{position:'absolute',right:-110,top:350,width:460,height:460,border:`2px solid ${accent}`,borderRadius:'50%'}}/>}
   <div style={{position:'absolute',top:95,left:72,right:72,display:'flex',justifyContent:'space-between',fontSize:28,letterSpacing:3,color:punch?paper:ink}}><span>{p.brand.name}</span><span>{String(p.index).padStart(2,'0')} / {String(p.count).padStart(2,'0')}</span></div>
   <div data-layer="recipe-title" style={{visibility:p.suppressTitle?'hidden':undefined,position:'absolute',top:calm?225:185,left:72,right:72,opacity:reveal,color:punch?paper:ink,fontSize:titleSize,fontWeight:calm?500:800,fontFamily:calm?'"Songti SC","STSong",serif':undefined,lineHeight:1.25,transform:`translateY(${(1-reveal)*18}px) scale(${titleScale})`,transformOrigin:'left center'}}>
    {recipe==='blur-slide'?<BlurWords groups={headlineGroups(p.headline)} frame={f} start={at} size={titleSize} color={punch?paper:ink}/>:p.headline}
    {recipe==='marker-underline-title'&&p.headline&&<svg data-layer="marker" viewBox="0 0 800 28" style={{display:'block',width:Math.min(900,Array.from(p.headline).length*titleSize),height:28,marginTop:12,overflow:'visible',transform:`scaleX(${cubic(segment(f,at+18,at+28))})`,transformOrigin:'left'}}><path d="M3 21 Q100 8 240 16 T490 14 T795 6" stroke={accent} strokeWidth="9" fill="none" strokeLinecap="round"/><path d="M12 25 Q180 12 350 21 T780 12" stroke={accent} strokeWidth="2" opacity=".45" fill="none"/></svg>}
   </div>
   <div style={{position:'absolute',left:calm?72:40,right:calm?72:40,top:punch?485:510,bottom:330,background:calm?'#ffffff55':paper,border:calm?`1px solid ${accent}55`:social?'12px solid #fffdf5':`2px solid ${accent}33`,borderRadius:lab?0:calm?4:22,overflow:'hidden',opacity:mediaAt,transform:`translateY(${assemble?24*(1-mediaAt):0}px)${social?` rotate(${-1.5+1.5*reveal}deg)`:''}`}}>
    {media}
    {recipe==='scanline-annotate-focus'&&<>
     {scan>0&&scan<1&&<div style={{position:'absolute',left:0,right:0,top:`${scan*100}%`,height:2,background:accent,boxShadow:`0 0 12px ${accent}`}}/>}
     {/* object-position and transform-origin use this same normalized focal point. */}
     <div data-layer="focus" style={{position:'absolute',left:`clamp(0px, calc(${p.focus_x*100}% - 130px + ${p.kind==='image'?pan:0}px), calc(100% - 264px))`,top:`clamp(0px, calc(${p.focus_y*100}% - 110px), calc(100% - 224px))`,width:260,height:220,opacity:focusReveal,border:`2px solid ${accent}`,borderRadius:4}}><span style={{position:'absolute',top:8,left:8,fontSize:26,whiteSpace:'nowrap',padding:'3px 8px',background:paper,color:ink}}>{p.headline}</span></div>
    </>}
   </div>
   {assemble&&<div data-layer="assembly-steps" style={{position:'absolute',left:72,right:72,top:465,display:'flex',gap:12}}>{[0,1,2].map(i=><div key={i} style={{height:5,flex:1,background:accent,opacity:.18+.82*cubic(segment(f,at+16+i*8,at+24+i*8))}}/>)}</div>}
  </div>
  {/* Subtitles never inherit stage motion or zoom. They use the original word clock. */}
  {p.format!=='showcase'&&caption&&<Caption caption={caption} style={{position:'absolute',left:108,right:108,bottom:180,textAlign:'center',fontSize:p.brand.subtitle_size,lineHeight:1.5,padding:'12px 18px',background:paper,borderRadius:6}}/>}
  <div style={{position:'absolute',left:108,right:108,bottom:130,height:2,background:ink+'22'}}><div style={{height:2,width:`${100*(p.index-1+f/Math.max(1,p.frames-1))/p.count}%`,background:accent}}/></div>
  {p.preview&&p.index===p.count&&<div style={{position:'absolute',left:108,bottom:82,fontSize:25,color:ink}}>实拍创意示例 · 待人工审片</div>}
  {p.sample&&<div style={{position:'absolute',left:108,bottom:82,fontSize:25,color:ink}}>虚构商品 · AI示例画面 · 非实拍</div>}
  {(enter>0||leave>0)&&<div data-layer="push-stack" style={{position:'absolute',left:0,right:0,height:1920,top:enter>0?slide-1920:slide+1920,background:paper,boxShadow:'0 -20px 35px #0002',borderTop:`2px solid ${accent}`}}/>}
  {(lineIn>0||lineOut>0)&&<div data-layer="line-carry" style={{position:'absolute',left:0,right:0,top:1500,height:5,background:accent,transform:`scaleX(${Math.max(lineIn,lineOut)})`,transformOrigin:'left'}}/>}
  {p.transition==='wipe'&&<div style={{position:'absolute',inset:0,background:paper,transform:`translateX(${1080*cubic(segment(f,0,12))}px)`}}/>}
  {p.exitTransition==='wipe'&&<div style={{position:'absolute',inset:0,background:paper,transform:`translateX(${-1080+1080*cubic(segment(f,p.frames-12,p.frames-1))}px)`}}/>}
  {(p.transition==='iris'||p.exitTransition==='iris')&&[0,1].map(side=>{const close=Math.max(p.transition==='iris'?1-cubic(segment(f,0,24)):0,p.exitTransition==='iris'?segment(f,p.frames-12,p.frames-1):0);return <div key={side} style={{position:'absolute',left:0,right:0,height:960*close,background:paper,...(side?{bottom:0}:{top:0})}}/>;})}
 </AbsoluteFill>;
};
export const RecipeShot:React.FC<Props>=(p)=>p.motionPlan?.version===2?<NarrativeShot {...p}/>:<LegacyRecipeShot {...p}/>;
