const {test}=require('node:test');const assert=require('node:assert/strict');
const state=require('../../ecom_video/web/operations-state.js');
test('seven modules keep production and organic reporting separate',()=>{assert.equal(state.modules.length,7);assert.equal(new Set(state.modules.map(x=>x.id)).size,7);});
test('zero, missing and cumulative observations retain distinct display',()=>{assert.equal(state.metric('0'),'0');assert.equal(state.metric(null),'— 未提供');assert.match(state.summary({kind:'observation_snapshot',payload:{counting:'cumulative',rows:[{}]}}),/累计/);});
test('definitions keep full original text and reject duplicate metrics',()=>{assert.deepEqual(state.definitions('views｜完整平台口径'),{views:'完整平台口径'});assert.throws(()=>state.definitions('views｜甲\nviews｜乙'));assert.throws(()=>state.definitions('views'));});
