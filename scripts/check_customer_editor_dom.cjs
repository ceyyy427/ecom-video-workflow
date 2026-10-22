const {parseHTML}=require(process.env.LINKEDOM_MODULE || 'linkedom');const fs=require('node:fs'),assert=require('node:assert/strict');const root=require('node:path').resolve(__dirname,'..');const {mount,compactShot}=require(root+'/ecom_video/web/customer-editor.js');
const {document}=parseHTML(fs.readFileSync(root+'/ecom_video/web/customer.html','utf8'));
const originalCreate=document.createElement.bind(document);document.createElement=(tag)=>{const e=originalCreate(tag);if(tag==='video')e.pause=()=>{};return e;};for(const e of document.querySelectorAll('audio,video'))e.pause=()=>{};
const data={duration:8,shots:[{shot_id:'a',start:0,duration:4,asset_id:'v',source_in:1},{shot_id:'b',start:4,duration:4,asset_id:'v',source_in:3}],captions:[{start:.2,end:1.5,text:'拉链口袋'}],audio:{narration:{asset_id:'voice'},music_id:'music'}};
const edits=[];let loads=[];const app=mount(document,{load:()=>new Promise(resolve=>loads.push(resolve)),edit:(id,time)=>edits.push({id,time})});
const oldRepeat=document.getElementById('motionRepeatLimit').closest('details');assert.equal(oldRepeat.className,'cut-settings');for(const detail of document.querySelectorAll('details')){if(detail.querySelector('summary')?.textContent==='高级：动效重复限制')assert.equal(detail.hidden,true,'empty old advanced section must disappear');}
const p={id:'p',product:{},job:{id:'j',status:'needs_review',storyboard:{},storyboard_revision:1,assets:[{id:'v',kind:'video',name:'藏蓝.mp4',metadata:{duration:15}}],artifacts:[{kind:'video'}]}};
(async()=>{
 const form=document.createElement('fieldset'),grid=document.createElement('div');grid.className='customer-grid';form.append(grid);
 const make=(name,value)=>{const label=document.createElement('label'),input=document.createElement('input');input.setAttribute('aria-label',name);input.value=value;label.append(input);grid.append(label);return input;};
 const common=make('第 1 镜字卡','穿得利落'),advanced=make('第 1 镜动效偏移秒数','.3'),note=make('画面小字（不读出，最多40字）','防泼水演示');const approval=make('确认人','');
 compactShot(form);assert.equal(form.querySelector('.cut-advanced').open,undefined);assert.ok(advanced.closest('details'));assert.equal(advanced.value,'.3');assert.equal(common.closest('details'),null);assert.equal(note.closest('details'),null);assert.equal(approval.closest('details'),null);assert.equal(form.querySelectorAll('input').length,4);

 let pending=app.update({project:p});loads.shift()(data);await pending;
 assert.equal(document.querySelectorAll('.cut-track').length,4);
 assert.equal(document.querySelectorAll('#shotList').length,1);
 const seek=document.querySelector('input[aria-label="时间轴播放头"]');seek.value='4.5';seek.oninput();assert.equal(document.getElementById('cutPreview').currentTime,4.5);
 const trim=document.querySelector('.cut-inspector input[type=range]');trim.value='6';trim.oninput();assert.deepEqual(edits,[{id:'b',time:6}]);assert.equal(document.querySelector('#cutPreview').getAttribute('src'),'/api/jobs/j/assets/v');
 assert.equal(document.getElementById('filmChecked').checked,undefined);assert.equal(document.getElementById('voiceChecked').checked,undefined);
 const p2={id:'p2',product:{},job:null};let second=app.update({project:p2});assert.equal(document.getElementById('cutPreview').getAttribute('src'),null,'old project media clears immediately');loads.shift()({shots:[],duration:0,captions:[]});await second;assert.equal(document.getElementById('cutPreview').getAttribute('src'),null);
 let old=app.update({project:p}),fresh=app.update({project:p2});const resolveOld=loads.shift(),resolveFresh=loads.shift();resolveFresh({shots:[],duration:0,captions:[]});await fresh;resolveOld(data);await old;assert.equal(document.querySelectorAll('.cut-video').length,0);
 for(const a of document.querySelectorAll('.workspace-steps a'))a.dispatchEvent(new document.defaultView.Event('click'));assert.equal(document.getElementById('step4').hidden,false);
 console.log('PASS: real HTML mount, four tracks, scrub seek, explicit edit, approvals untouched, stale-response isolation, empty state, step navigation; no browser/layout/media decoding performed');
})().catch(e=>{console.error(e);process.exitCode=1;});
