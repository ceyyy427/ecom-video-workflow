import React from 'react';
import {Caption} from './Caption';
import {LiveActionShot} from './LiveActionShot';
import {AbsoluteFill,Img,Video,staticFile,useCurrentFrame,interpolate} from 'remotion';
import type {Props} from './index';
import {BlurWords,TextPortal,FocusMark,headlineGroups,segment,cubic,bounded} from './motion';

// Frame-derived product choreography. No generated views or unsupported product measurements.
export const DirectionShot:React.FC<Props>=(p)=>{
 const f=useCurrentFrame(),t=f/30,style=p.style,cinema=style==='cinema',social=style==='social',lab=style==='lab';
 const treatment=p.treatment==='auto'||!p.treatment?(p.index===1?'hero':p.index===p.count?'end':(['macro','split','context'][(p.index-2)%3])):p.treatment;
 const hero=treatment==='hero',end=treatment==='end',macro=treatment==='macro',split=treatment==='split';
 const silent=p.format==='showcase';
 const ink=p.brand.ink,paper=p.brand.paper,accent=p.brand.accent,plate=cinema?'#171915':p.brand.paper;
 const move=cubic(segment(f,12,(cinema&&hero&&p.frames>=150?100:Math.max(24,p.frames-30)))),entry=cubic(segment(f,0,24));
 const hIndex=Array.from(p.text.slice(0,Math.max(0,p.text.indexOf(p.headline)))).filter(c=>/[\p{L}\p{N}]/u.test(c)).length;
 const anchor=p.words[hIndex]?.start??p.voiceStart;
 const titleStart=silent?12:Math.max(0,anchor*30);
 const groups=headlineGroups(p.suppressTitle?'':p.headline);
 const caption=p.captions.find(c=>t>=c.start&&t<=c.end);
 const z=p.motion==='static'?1:p.motion==='pull'?1.12-.12*move:1+.12*move;
 const px=p.motion==='pan_left'?30-60*move:p.motion==='pan_right'?-30+60*move:0;
 const Media=({scale=1,focus=p.focus_y,fit=p.fit}:{scale?:number;focus?:number;fit?:'cover'|'contain'})=>{
  const css:React.CSSProperties={width:'100%',height:'100%',objectFit:p.kind==='video'?p.fit:fit,objectPosition:`${p.focus_x*100}% ${focus*100}%`,transform:p.kind==='image'?`translateX(${px}px) scale(${scale*z})`:undefined,transformOrigin:`${p.focus_x*100}% ${focus*100}%`};
  return p.kind==='image'?<Img src={staticFile(p.src)} style={css}/>:<Video src={staticFile(p.src)} muted style={css}/>;
 };
 const panel=(css:React.CSSProperties,child:React.ReactNode)=><div style={{position:'absolute',overflow:'hidden',...css}}>{child}</div>;
 const footer=<div style={{position:'absolute',bottom:135,left:64,maxWidth:952,fontSize:40,color:cinema?'#f4eee2':ink,letterSpacing:1,padding:'8px 12px',borderRadius:6,background:cinema?'#171915cc':paper}}>{p.sample?'虚构商品 · AI示例画面 · 非实拍':p.brand.name}</div>;
 const number=String(p.index).padStart(2,'0');
 const transitions=<>
  {/* Closed color plate at both cut edges; no overlap or change to the voice clock. */}
  {p.transition==='wipe'&&<div style={{position:'absolute',inset:0,background:plate,transform:`translateX(${1080*cubic(segment(f,0,12))}px)`}}/>}
  {p.exitTransition==='wipe'&&<div style={{position:'absolute',inset:0,background:plate,transform:`translateX(${-1080+1080*cubic(segment(f,p.frames-12,p.frames-1))}px)`}}/>}
  {(p.transition==='iris'||p.exitTransition==='iris')&&[0,1].map(side=>{const close=Math.max(p.transition==='iris'?1-entry:0,p.exitTransition==='iris'?segment(f,p.frames-12,p.frames-1):0);return <div key={side} style={{position:'absolute',left:0,width:1080,height:960*close,background:plate,...(side?{bottom:0}:{top:0})}}/>;})}
 </>;
 // Full-frame live-action keeps the actual motion and the caller's contain/cover choice.
 // This opt-in treatment leaves existing image/card storyboards unchanged.
 if(treatment==='footage') return <LiveActionShot {...p} transitionLayer={transitions}/>;
 return <AbsoluteFill style={{background:cinema?'#171915':paper,fontFamily:'"PingFang SC","Heiti SC",sans-serif',color:ink,overflow:'hidden'}}>
  {cinema&&<>
   {hero&&p.frames>=150?<TextPortal frame={f} text={p.headline.slice(0,4)}><Media fit="cover"/></TextPortal>:
    split?<>{panel({left:0,top:0,width:1080,height:960},<Media scale={1.4} focus={.24} fit="cover"/>)}{panel({left:0,top:980,width:1080,height:940},<Media scale={1.05} focus={.75} fit="cover"/>)}</>:
    end?panel({left:70,top:380,width:940,height:1050,clipPath:`inset(${(1-entry)*45}% 0)`},<Media fit="contain"/>):panel({inset:0,clipPath:hero?`inset(${(1-entry)*45}% 0)`:undefined},<Media scale={macro?1.55:1} focus={p.focus_y} fit="cover"/>)}
   {<div style={{position:'absolute',inset:0,opacity:hero&&p.frames>=150?segment(f,95,130):1,background:'linear-gradient(180deg,#0007,transparent 40%,transparent 65%,#0009)'}}/>}
   {!(hero&&p.frames>=150)&&<div style={{position:'absolute',left:68,right:68,top:end?185:260}}><BlurWords groups={groups} frame={f} start={titleStart} size={end?104:96} color="#f4eee2"/></div>}
   {hero&&p.frames>=150&&<div style={{position:'absolute',top:1240,left:80,right:80,textAlign:'center',fontSize:64,lineHeight:1.5,letterSpacing:2,color:'#f4eee2',opacity:1-segment(f,95,114)}}>{(p.text.match(/[^，。！？；]+[，。！？；]?/gu)||[p.text]).map((line,i)=><div key={i}>{line}</div>)}</div>}
   {end&&<div style={{position:'absolute',top:1490,left:70,right:70,fontSize:66,color:'#f4eee2',opacity:segment(f,25,45)}}>{p.text}</div>}
  </>}
  {social&&<>
   <div style={{position:'absolute',left:64,right:64,top:190}}><div style={{fontSize:40,letterSpacing:6,marginBottom:24,color:accent}}>{hero?'日常灵感':end?'留一点从容':'生活片段'} / {number}</div><BlurWords groups={groups} frame={f} start={titleStart} size={108} color={ink}/></div>
   {hero?panel({left:64,top:560,width:952,height:940,borderRadius:18,clipPath:`inset(0 0 ${(1-entry)*100}% 0)`},<Media fit="cover"/>):treatment==='context'?<>
    {panel({left:90,top:560,width:740,height:900,border:'16px solid #fffdf5',boxShadow:'0 20px 45px #30231322',transform:`translate(${-75*(1-entry)}px,${100*(1-entry)}px) rotate(${-7+4*move}deg)`},<Media fit="cover"/>)}
    {panel({left:510,top:1000,width:440,height:510,border:'12px solid #fffdf5',boxShadow:'0 15px 35px #30231333',transform:`translateY(${130*(1-cubic(segment(f,18,45)))}px) rotate(${8-4*move}deg)`,opacity:segment(f,18,25)},<Media scale={1.25} focus={.3} fit="cover"/>)}
   </>:split?<>
     {panel({left:55,top:560,width:470,height:920,borderRadius:230,transform:`translateY(${60*(1-entry)}px)`},<Media scale={1.4} focus={.25} fit="cover"/>)}
     {panel({left:555,top:650,width:470,height:830,borderRadius:230,transform:`translateY(${-60*(1-entry)}px)`},<Media focus={.75} fit="cover"/>)}
   </>:panel({left:64,top:550,width:952,height:940,borderRadius:end?450:14,clipPath:`inset(0 ${(1-entry)*100}% 0 0)`},<Media scale={macro?1.35:1} focus={p.focus_y} fit={end?'contain':'cover'}/>)}
   <div style={{position:'absolute',left:66,top:1505,width:80+340*entry,height:5,background:accent}}/>
  </>}
  {lab&&<>
   <div style={{position:'absolute',left:64,top:170,fontSize:40,letterSpacing:6,color:accent}}>{p.format==='review'?'测试记录':'外观观察'} / {number}</div>
   <div style={{position:'absolute',left:64,right:64,top:245}}><BlurWords groups={groups} frame={f} start={titleStart} size={94} color={ink}/></div>
   {split?<>
    {panel({left:64,top:510,width:952,height:540,borderRadius:18},<Media scale={1.4} focus={.2} fit="cover"/>)}
    {panel({left:64,top:1074,width:952,height:440,borderRadius:18},<Media focus={.8} fit="cover"/>)}
    <div style={{position:'absolute',top:1040,left:64,width:130,height:40,background:accent}}/>
   </>:<>
    {panel({left:64,top:500,width:952,height:1000,borderRadius:18},<><Media scale={macro?1.65:1} focus={p.focus_y} fit={end?'contain':'cover'}/>{macro&&<FocusMark frame={f} frames={p.frames} color={accent} label={p.headline}/>}</>)}
    {hero&&<div style={{position:'absolute',left:675,top:1100,width:300,height:300,borderRadius:'50%',overflow:'hidden',border:`8px solid ${paper}`,boxShadow:`0 0 0 2px ${accent}`,transform:`scale(${.4+.6*entry})`}}><Media scale={1.8} focus={.2} fit="cover"/></div>}
   </>}
   <div style={{position:'absolute',top:420,left:64,fontSize:40,color:accent}}>{p.role==='evidence'?'证据：本镜上传素材':'只展示画面可见细节'}</div>
  </>}
  <div style={{position:'absolute',top:85,left:64,right:64,display:'flex',justifyContent:'space-between',fontSize:40,letterSpacing:3,color:cinema?'#f4eee2':ink}}><span>{p.brand.name}</span><span>{number} / {String(p.count).padStart(2,'0')}</span></div>
  {!silent&&caption&&<Caption caption={caption} style={{position:'absolute',left:64,right:64,bottom:245,fontSize:p.brand.subtitle_size,fontWeight:500,lineHeight:1.45,textAlign:'center',color:cinema?'#fff':ink,background:cinema?'#1118':paper,padding:'14px 20px',borderRadius:12}}/>}
  {footer}
  {transitions}

 </AbsoluteFill>;
};
