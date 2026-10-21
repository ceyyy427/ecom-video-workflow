import React from 'react';
import {Img,useCurrentFrame} from 'remotion';

export type CaptionData={text:string;start:number;end:number;image?:string;width?:number;height?:number;emphasis?:{text:string;start:number;end:number;image:string;basis?:string}};
// Whole phrases keep their original times. Only verified word spans change the raster.
export const Caption:React.FC<{caption:CaptionData;style:React.CSSProperties}>=({caption,style})=>{
 const time=useCurrentFrame()/30;
 const mark=caption.emphasis&&time>=caption.emphasis.start&&time<caption.emphasis.end;
 const source=mark?caption.emphasis!.image:caption.image;
 return <div style={style}>{source?<Img src={source} alt={caption.text} style={{display:'block',width:caption.width,height:caption.height,maxWidth:'100%',objectFit:'contain',margin:'0 auto',filter:style.textShadow?'drop-shadow(0 2px 4px #0008)':undefined}}/>:caption.text}</div>;
};
