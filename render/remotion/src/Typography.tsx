import React from 'react';
import {Img,interpolate,spring,useCurrentFrame,useVideoConfig} from 'remotion';
export type TypographyData={top:number;scale:number;height:number;width:number;mode:'impact'|'reveal'|'contrast';keyword:string;start:number;end:number;static:boolean;basis:string;segments:{text:string;image:string;width:number;height:number;keyword:boolean;start:number}[]};
// Clip-and-reveal inspired by Anime.js splitText; no DOM timers or runtime text splitting.
export const Typography:React.FC<{data:TypographyData;accent:string}> = ({data,accent})=>{
 const frame=useCurrentFrame(),{fps}=useVideoConfig(),time=frame/fps;
 if(time<data.start||time>=data.end)return null;
 const fade=interpolate(time,[data.end-.2,data.end],[1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 return <div aria-label={data.segments.map(s=>s.text).join('')} style={{position:'absolute',left:90,right:90,top:data.top,transform:`scale(${data.scale})`,transformOrigin:'left top',display:'flex',flexDirection:data.mode==='contrast'?'column':'row',alignItems:'flex-start',gap:data.mode==='contrast'?0:8,opacity:fade,filter:'drop-shadow(0 4px 10px #000b)',pointerEvents:'none'}}>
 {data.segments.map((s,i)=>{
  const at=data.mode==='reveal'?s.start:data.start;
  const local=frame-at*fps;
  const enter=data.static?1:spring({frame:local,fps,config:{damping:18,stiffness:230,overshootClamping:true},durationInFrames:16});
  const stress=data.static?1:spring({frame:frame-s.start*fps,fps,config:{damping:20,stiffness:230,overshootClamping:true},durationInFrames:12});
  const pulse=data.static||!s.keyword?1:.9+.1*stress;
  return <div key={i} style={{position:'relative',overflow:'hidden',padding:'6px 10px',background:'#101b208c',borderRadius:3,opacity:local<0&&!data.static?0:1}}>
   <div style={{transform:`translateY(${data.mode==='reveal'?110*(1-enter):18*(1-enter)}%) scale(${data.mode==='impact'?(.88+.12*enter)*pulse:1})`,transformOrigin:'left center'}}><Img src={s.image} alt={s.text} style={{display:'block',width:s.width,height:s.height}}/></div>
   {s.keyword&&<div style={{position:'absolute',left:10,right:10,bottom:3,height:data.mode==='impact'?8:4,background:accent,transform:`scaleX(${data.static?1:stress})`,transformOrigin:'left'}}/>}
  </div>;
 })}</div>;
};
