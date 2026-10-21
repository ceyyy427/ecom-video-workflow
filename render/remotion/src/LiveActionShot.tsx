import React from 'react';
import {AbsoluteFill,Img,Video,staticFile,useCurrentFrame} from 'remotion';
import type {Props} from './index';
import {Caption} from './Caption';
import {cubic,segment} from './motion';

// Live action is the continuous subject. Typography and framing change by narrative,
// while source color, voice time and the user's crop remain unchanged.
export const LiveActionShot:React.FC<Props & {transitionLayer?:React.ReactNode}>=(p)=>{
 const f=useCurrentFrame(),t=f/30,quiet=p.style==='quiet',editorial=p.style==='editorial',kinetic=p.style==='kinetic',collage=p.style==='collage',geo=p.style==='bauhaus',cinema=p.style==='cinema'||quiet,lab=['lab','evidence','bauhaus'].includes(p.style);
 const ink=p.brand.ink,paper=p.brand.paper,accent=p.brand.accent;
 const end=p.index===p.count,hook=p.index===1;
 const offset=Array.from(p.text.slice(0,Math.max(0,p.text.indexOf(p.headline)))).filter(c=>/[\p{L}\p{N}]/u.test(c)).length;
 const anchor=Math.max(0,p.words[offset]?.start??p.voiceStart);
 const titleAt=hook?Math.min(anchor*30,12):anchor*30;
 const reveal=cubic(segment(f,titleAt,titleAt+14));
 const captions=p.captions.find(c=>t>=c.start&&t<c.end);
 const label=String(p.index).padStart(2,'0'),total=String(p.count).padStart(2,'0');
 const mediaStyle:React.CSSProperties={width:'100%',height:'100%',objectFit:p.fit,objectPosition:`${p.focus_x*100}% ${p.focus_y*100}%`};
 const media=p.kind==='image'?<Img src={staticFile(p.src)} style={mediaStyle}/>:<Video src={staticFile(p.src)} muted style={mediaStyle}/>;
 const mediaBox:React.CSSProperties=lab?{left:64,right:64,top:geo?520:475,height:geo?970:1080}:cinema?{inset:0}:editorial?{left:72,right:72,top:440,height:1080}:collage?{left:50,right:50,top:440,height:1090,border:'16px solid #fffdf5',transform:`rotate(${-2+2*reveal}deg)`}:{left:0,right:0,top:390,bottom:0};
 const heading:React.CSSProperties=cinema?{top:quiet?390:240,left:100,right:100,fontFamily:'"Songti SC","STSong",serif',fontSize:quiet?78:116,fontWeight:500,lineHeight:1.2}:lab?{top:208,left:72,right:72,fontSize:geo?92:104,fontWeight:750,lineHeight:1.18}:{top:165,left:72,right:72,fontFamily:editorial?'"Songti SC","STSong",serif':undefined,fontSize:editorial?80:kinetic?128:112,fontWeight:editorial?500:800,lineHeight:1.16};
 const titleColor=cinema?'#f8f1e4':ink;

 return <AbsoluteFill style={{background:cinema?'#171815':paper,color:ink,fontFamily:'"PingFang SC","Heiti SC",sans-serif',overflow:'hidden'}}>
  <div style={{position:'absolute',overflow:'hidden',...mediaBox}}>{media}</div>
  {geo&&<div style={{position:'absolute',left:72,top:400,width:480*reveal,height:18,background:accent}}/>}
  {kinetic&&<div style={{position:'absolute',right:72,top:315,width:150*reveal,height:10,background:accent}}/>}
  {cinema&&<div style={{position:'absolute',inset:0,background:'linear-gradient(180deg,#111814a8 0%,#11181433 30%,transparent 52%,transparent 75%,#111814b0 100%)'}}/>}
  {!cinema&&!lab&&<div style={{position:'absolute',left:0,right:0,bottom:0,height:420,background:'linear-gradient(transparent,#18251ec9)'}}/>}
  <div style={{position:'absolute',top:108,left:cinema?100:72,right:cinema?100:72,display:'flex',justifyContent:'space-between',fontSize:28,letterSpacing:3,color:cinema?'#e7dbc5':ink}}>
   <span>{p.brand.name}</span><span>{lab?'观察 / ':''}{label}—{total}</span>
  </div>
  <div style={{position:'absolute',...heading,color:titleColor,opacity:reveal,transform:`translateY(${(1-reveal)*(cinema?14:28)}px)`}}>
   {p.headline}
   {hook&&!cinema&&<div style={{width:lab?125:85,height:lab?3:8,background:accent,marginTop:28}}/>}
  </div>
  {lab&&<>
   <div style={{position:'absolute',left:88,top:geo?540:503,fontSize:27,padding:'8px 16px',background:paper,color:ink}}>{geo?'设计 / 陈列':p.style==='evidence'?'细节 / 解说':'外观观察 / 近看'}</div>
   {[0,1,2,3].map(k=><div key={k} style={{position:'absolute',width:34,height:34,opacity:segment(f,15,28),...(k%2?{right:100,borderRight:`3px solid ${accent}`}:{left:100,borderLeft:`3px solid ${accent}`}),...(k>1?{top:1490,borderBottom:`3px solid ${accent}`}:{top:555,borderTop:`3px solid ${accent}`})}}/>)}
  </>}
  {p.format!=='showcase'&&captions&&<Caption caption={captions} style={{position:'absolute',left:108,right:108,bottom:190,textAlign:'center',fontSize:p.brand.subtitle_size,lineHeight:1.5,padding:'12px 18px',background:lab?ink:cinema?'#1718159c':'#1c3026c7',borderRadius:lab?0:10,textShadow:cinema?'0 2px 6px #0006':undefined}}/>}
  <div style={{position:'absolute',left:108,right:108,bottom:130,height:2,background:cinema?'#ffffff24':ink+'33'}}><div style={{width:`${100*(p.index-1+f/Math.max(1,p.frames-1))/p.count}%`,height:2,background:cinema?'#e7dbc5':accent}}/></div>
  {end&&p.preview&&<div style={{position:'absolute',left:108,bottom:86,fontSize:25,letterSpacing:2,color:lab?ink:cinema?'#eadfcf':'#fff',opacity:segment(f,p.frames-45,p.frames-25)}}>实拍创意示例 · 待人工审片</div>}
  {p.sample&&<div style={{position:'absolute',left:108,bottom:85,fontSize:26,color:cinema?'white':ink}}>虚构商品 · AI示例画面 · 非实拍</div>}
  {p.transitionLayer}
 </AbsoluteFill>;
};
