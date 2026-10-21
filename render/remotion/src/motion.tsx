// Adapted from Vincentwei1021/video-shotcraft, Apache-2.0.
// TextAsMask.tsx and BlurSlide.tsx. Original sources retained under vendor/video-shotcraft/p6.
// Changes: portrait product media, caller-supplied copy, voice anchors, no fixture dashboards.
import React from 'react';
import {Easing, interpolate} from 'remotion';
export const bounded={extrapolateLeft:'clamp',extrapolateRight:'clamp'} as const;
export const segment=(f:number,a:number,b:number)=>interpolate(f,[a,b],[0,1],bounded);
export const cubic=(x:number)=>1-Math.pow(1-x,3);
// Word segmentation preserves Chinese lexical units; merge a leading single character.
export function headlineGroups(text:string){
 const words=[...new Intl.Segmenter('zh',{granularity:'word'}).segment(text)].map(v=>v.segment);
 const groups:string[]=[];
 for(let i=0;i<words.length;i++){
  const word=words[i];
  if(Array.from(word).length===1&&i+1<words.length)groups.push(word+words[++i]);
  else groups.push(word);
 }
 return groups;
}
export function BlurWords({groups,frame,start=0,size=90,color,align='left'}:{groups:string[];frame:number;start?:number;size?:number;color:string;align?:'left'|'center'}){
 return <div style={{display:'flex',flexWrap:'wrap',justifyContent:align==='center'?'center':'flex-start',gap:'0 .12em',fontSize:size,fontWeight:650,lineHeight:1.25,color}}>{groups.map((word,i)=>{const p=cubic(segment(frame,start+i*3.5,start+i*3.5+20));return <span key={i} style={{opacity:p,transform:`translateY(${40*(1-p)}px)`,filter:`blur(${10*(1-p)}px)`}}>{word}</span>;})}</div>;
}
export function TextPortal({frame,text,children}:{frame:number;text:string;children:React.ReactNode}){
 const end=interpolate(frame,[100,130],[0,1],{...bounded,easing:Easing.bezier(.4,0,.2,1)});
 const s=1+25*end,dx=frame<100?interpolate(frame,[20,100],[110,-110],bounded):-110*(1-end);
 const size=Math.min(390,940/Math.max(2,text.length));
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920"><text x="540" y="1080" font-family="PingFang SC,Heiti SC,sans-serif" font-size="${size}" font-weight="900" text-anchor="middle" fill="white">${text.replace(/[<>&"']/g,'')}</text></svg>`;
 const mask=`url("data:image/svg+xml,${encodeURIComponent(svg)}")`,origin='43% 51%';
 const content=<div style={{position:'absolute',inset:0,transform:`translateX(${dx}px) scale(${1.15-.15*end})`}}>{children}</div>;
 return <><div style={{position:'absolute',inset:0,opacity:.16}}>{content}</div><div style={{position:'absolute',inset:0,transform:`scale(${s})`,transformOrigin:origin,WebkitMaskImage:mask,maskImage:mask,maskSize:'1080px 1920px',WebkitMaskSize:'1080px 1920px',maskRepeat:'no-repeat'}}><div style={{position:'absolute',inset:0,transform:`scale(${1/s})`,transformOrigin:origin}}>{content}</div></div><div style={{position:'absolute',inset:0,opacity:segment(end,.25,.9)}}>{content}</div></>;
}
// Adapted target-arrival timing and 1.75x focus closure from ScanlineAnnotateFocus.tsx.
export function FocusMark({frame,frames,color,label}:{frame:number;frames:number;color:string;label:string}){
 const t=frame/Math.max(frames,138),y=410,h=420;
 const trigger=.06+((y+h+30)/1080)*.6;
 const a=segment(t,trigger,trigger+.13),back=1+2.70158*Math.pow(a-1,3)+1.70158*Math.pow(a-1,2);
 const scale=1.75-.75*back,scan=-30+1080*segment(t,.06,.66);
 return <><div style={{position:'absolute',left:0,top:scan,width:'100%',height:3,background:color,opacity:segment(t,.04,.09)*(1-segment(t,.66,.71))}}/>
 <div style={{position:'absolute',left:'14%',top:y,width:'72%',height:h,opacity:Math.min(1,a*1.6),transform:`scale(${scale})`}}>{[0,1,2,3].map(k=><div key={k} style={{position:'absolute',width:30,height:30,...(k%2?{right:0,borderRight:`3px solid ${color}`}:{left:0,borderLeft:`3px solid ${color}`}),...(k>1?{bottom:0,borderBottom:`3px solid ${color}`}:{top:0,borderTop:`3px solid ${color}`})}}/>)}</div><div style={{position:'absolute',left:'14%',top:y+h+22,color,background:'#fffdf2ee',padding:'6px 14px',borderRadius:6,fontSize:40,opacity:segment(t,trigger+.13,trigger+.18)}}>{label}</div></>;
}
