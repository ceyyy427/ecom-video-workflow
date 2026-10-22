import React from 'react';
import {Caption,type CaptionData} from './Caption';
import {DirectionShot} from './directions';
import {Typography,type TypographyData} from './Typography';
import {RecipeShot} from './RecipeShot';
import {AbsoluteFill,Composition,Img,Video,registerRoot,useCurrentFrame,interpolate,Easing,staticFile} from 'remotion';
// Project-owned product layouts and motion. All displayed media belongs to the task.
const clamp=(x:number)=>Math.max(0,Math.min(1,x));
const camEase=(p:number)=>p*p*(3-2*p);
export type Props={suppressTitle?:boolean;typography?:TypographyData;captionNote?:string;titleLayout?:{text:string;image:string;width:number;height:number;font_size:number;lines:string[];font_family?:string};motionPlan?:{quote?:{text:string;fact_ids:string[];label?:string};prompt_card?:string|null;presentation?:{zoom:number;travel_frames:number;shape:string};visual_finish?:string;version:2;amount:number;cue_frame:number;intent:string;strength:string;guard_outcome:string;beats:{text:string;frame:number}[]};shotRecipe?:string;preview?:boolean;format?:string;treatment?:string;transition?:string;exitTransition?:string;captions:CaptionData[];src:string;kind:string;frames:number;text:string;headline:string;style:string;brand:{name:string;ink:string;paper:string;accent:string;subtitle_size:number};motion:string;fit:'contain'|'cover';focus_x:number;focus_y:number;sample:boolean;words:{text:string;start:number;end:number}[];voiceStart:number;voiceEnd:number;index:number;count:number;role:string};
const Shot:React.FC<Props>=(p)=>{
 const f=useCurrentFrame(),t=f/30,progress=camEase(clamp(f/Math.max(1,p.frames-1)));
 const collage=p.style==='collage',quiet=p.style==='quiet',geo=p.style==='bauhaus',evidence=p.style==='evidence',kinetic=p.style==='kinetic';
 const headOffset=p.text.indexOf(p.headline);
 const headWord=Array.from(p.text.slice(0,Math.max(0,headOffset))).filter(c=>/[\p{L}\p{N}]/u.test(c)).length;
 const lead=p.words.length?Math.max(0,p.words[headWord]?.start??p.voiceStart):.3;
 const titleSpring=interpolate(f,[lead*30,lead*30+18],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.bezier(.22,.7,.3,1)});
 const opacity=clamp((t-lead)/.35),tracking=.08*(1-titleSpring);
 const scale=p.motion==='static'?1:p.motion==='pull'?1.08-.08*progress:1+.08*progress;
 const x=p.motion==='pan_left'?25-50*progress:p.motion==='pan_right'?-25+50*progress:0;
 const y=0;
 const mediaStyle:React.CSSProperties={width:'100%',height:'100%',objectFit:p.fit,objectPosition:`${p.focus_x*100}% ${p.focus_y*100}%`,transform:p.kind==='image'?`translate(${x}px,${y}px) scale(${scale})`:undefined};
 const pop=interpolate(f,[0,16],[0,1],{extrapolateRight:'clamp',easing:Easing.bezier(.16,.8,.24,1)});
 const top=quiet?0:evidence?340:collage?380:410, height=quiet?1920:evidence?1040:collage?1000:1040;
 // Whole subtitle phrases switch without bouncing. Character anchors drive the title and cuts.
 const subtitle=p.captions.find(g=>t>=g.start && t<=g.end);
 return <AbsoluteFill style={{background:p.brand.paper,color:p.brand.ink,fontFamily:'"PingFang SC","Heiti SC",sans-serif',overflow:'hidden'}}>
   {geo && <><div style={{position:'absolute',width:610,height:610,borderRadius:'50%',background:p.brand.accent,left:620,top:200,transform:`translateY(${25*progress}px)`}}/><div style={{position:'absolute',width:280,height:24,background:p.brand.ink,left:80,top:1460}}/></>}
   <div style={{position:'absolute',left:quiet?0:80,top,width:quiet?1080:920,height,overflow:'hidden',border:collage?'18px solid white':undefined,boxSizing:'border-box',boxShadow:collage?'0 24px 45px #0002':undefined,transform:collage?`rotate(${-2+2*progress}deg) scale(${.95+.05*pop})`:undefined}}>
    {p.kind==='image'?<Img src={staticFile(p.src)} style={mediaStyle}/>:<Video src={staticFile(p.src)} muted style={mediaStyle}/>}
   </div>
   {quiet && <div style={{position:'absolute',inset:0,background:'linear-gradient(180deg,#0006,transparent 40%,transparent 65%,#0008)'}}/>}
   <div style={{position:'absolute',left:80,right:80,top:100,display:'flex',justifyContent:'space-between',fontSize:34,letterSpacing:4,color:quiet?'white':p.brand.ink}}><span>{p.brand.name}</span><span>{String(p.index).padStart(2,'0')} / {String(p.count).padStart(2,'0')}</span></div>
   {p.headline && !p.suppressTitle && <div style={{position:'absolute',left:80,right:80,top:quiet?220:205,fontSize:kinetic?86:72,fontWeight:600,lineHeight:1.25,color:quiet?'white':p.brand.ink,opacity,letterSpacing:`${tracking}em`,transform:`translateY(${18*(1-titleSpring)}px)`,whiteSpace:'nowrap'}}>{p.headline.slice(0,8)}</div>}
   {evidence && <div style={{position:'absolute',top:1410,left:80,fontSize:34,color:p.brand.accent}}>{p.role==='evidence'?'来源：本任务提供的证据素材':'素材细节 · 以实际商品为准'}</div>}
   {subtitle && <Caption caption={subtitle} style={{position:'absolute',left:80,right:80,bottom:280,textAlign:'center',fontSize:p.brand.subtitle_size,fontWeight:500,lineHeight:1.55,color:quiet?'white':p.brand.ink,textShadow:quiet?'0 2px 8px #0008':undefined}}/>}
   <div style={{position:'absolute',left:80,right:80,bottom:220,height:2,background:quiet?'#fff5':p.brand.ink+'33'}}><div style={{height:2,width:`${100*(p.index-1+progress)/p.count}%`,background:quiet?'white':p.brand.accent}}/></div>
   {p.sample && <div style={{position:'absolute',left:80,bottom:170,fontSize:32,color:quiet?'white':p.brand.ink}}>虚构商品 · AI 示例画面 · 非实拍</div>}
 </AbsoluteFill>;
};
const RenderContent:React.FC<Props>=(p)=>p.shotRecipe!==undefined||['push-stack','line-carry'].includes(p.transition??'')||['push-stack','line-carry'].includes(p.exitTransition??'')?<RecipeShot {...p}/>:(p.treatment==='footage'||['cinema','social','lab'].includes(p.style))?<DirectionShot {...p}/>:<Shot {...p}/>;
const RenderShot:React.FC<Props>=(p)=>!p.typography&&!p.captionNote?<RenderContent {...p}/>:<AbsoluteFill><RenderContent {...p} {...(p.typography?{suppressTitle:true}:{})}/>{p.typography&&<Typography data={p.typography} accent={p.brand.accent}/>} {p.captionNote&&<div style={{position:"absolute",bottom:160,left:80,right:80,textAlign:"center",color:"white",fontSize:28,lineHeight:1.4,fontFamily:"PingFang SC, sans-serif"}}><span style={{background:"#0009",padding:"8px 16px",borderRadius:4}}>{p.captionNote}</span></div>}</AbsoluteFill>;
const Root=()=> <Composition id="ProductShot" component={RenderShot} width={1080} height={1920} fps={30} durationInFrames={150} calculateMetadata={({props})=>({durationInFrames:props.frames})} defaultProps={{captions:[],src:'',kind:'image',frames:150,text:'',headline:'',style:'editorial',brand:{name:'',ink:'#282721',paper:'#f3efe6',accent:'#876f50',subtitle_size:64},motion:'push',fit:'contain',focus_x:.5,focus_y:.5,sample:false,words:[],voiceStart:0,voiceEnd:5,index:1,count:1,role:'product'}}/>;
registerRoot(Root);
