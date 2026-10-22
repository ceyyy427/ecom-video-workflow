const {test}=require('node:test');
const assert=require('node:assert/strict');
let editor={};try{editor=require('../../ecom_video/web/customer-editor.js');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
const data={duration:8,shots:[{shot_id:'a',start:0,duration:4,asset_id:'v',source_in:2,source_cuts:[{asset_id:'v',source_in:2,source_duration:1,duration:2},{asset_id:'w',source_in:5,source_duration:2,duration:2}]},{shot_id:'b',start:4,duration:4,asset_id:'w',source_in:0}],captions:[{start:.2,end:1,text:'袖口'},{start:2,end:3,text:'下摆'}]};
test('preview clock follows source cuts/speed and leaves speech pauses empty',()=>{
 assert.equal(typeof editor.frameAt,'function');
 assert.deepEqual(editor.frameAt(data,1),{shot_id:'a',asset_id:'v',source_time:2.5,caption:''});
 assert.equal(editor.frameAt(data,2.5).source_time,5.5);
 assert.equal(editor.frameAt(data,2.5).caption,'下摆');
 assert.equal(editor.frameAt(data,4).shot_id,'b');
 assert.equal(editor.frameAt(data,100).source_time,4);
});
test('trim preview rejects multi-cut/protected/running shots, clamps within source',()=>{
 assert.equal(typeof editor.trimRange,'function');
 assert.equal(editor.trimRange(data.shots[0],20,'draft').enabled,false);
 assert.equal(editor.trimRange({...data.shots[1],motion_plan:{windows:[{basis:'manual',start:0,end:2}]}},20,'draft').enabled,false);
 assert.equal(editor.trimRange(data.shots[1],20,'rendering').enabled,false);
 assert.deepEqual(editor.trimRange(data.shots[1],10,'draft'),{enabled:true,min:0,max:6});
 assert.equal(editor.trimRange(data.shots[1],2,'draft').enabled,false);
});
test('caption fallback never fabricates generated subtitles',()=>{
 assert.equal(editor.frameAt({...data,captions:[]},.5).caption,'');
 assert.equal(editor.frameAt({shots:[],duration:0},0),null);
});
