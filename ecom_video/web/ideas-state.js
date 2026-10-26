(function(root){
 'use strict';
 const executable=['swiss-motion','blueprint','dataviz','paper-popup','dark-keynote','kino-montage'];
 function rows(text,count){const lines=text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);if(lines.length>count)throw Error('资料条目过多，请先保留核心内容');return lines;}
 function facts(text){return rows(text,8).map(line=>{const at=line.indexOf('｜');if(at<1||!line.slice(at+1).trim())throw Error('事实请按“完整原文｜来源”填写，每行一条');return {text:line.slice(0,at).trim(),source:line.slice(at+1).trim()};});}
 function data(text){return rows(text,6).map(line=>{const cells=line.split('｜').map(s=>s.trim());if(cells.length!==4||!cells[0]||!cells[1]||!Number.isFinite(Number(cells[1]))||!cells[3])throw Error('数据请按“标签｜数值｜单位｜来源”填写，不填则不生成图表');return {label:cells[0],value:Number(cells[1]),unit:cells[2],source:cells[3]};});}
 function brief(values,materials){if(values.preferred&&!executable.includes(values.preferred))throw Error('该风格仍是参考资料，可点“只查参考”，或改选六个可预览方向');return {idea:values.idea.trim(),subject:values.subject.trim(),audience:values.audience.trim(),tone:values.tone.trim(),mode:values.mode,preferred:values.preferred||null,facts:facts(values.facts),data:data(values.data),materials:materials.map(a=>({origin:a.origin,id:a.id,...(a.project_id?{project_id:a.project_id}:{}),source_in:Number(a.source_in||0)}))};}
 const api={executable,facts,data,brief};if(typeof module!=='undefined')module.exports=api;else root.IdeaState=api;
})(typeof window==='undefined'?globalThis:window);
