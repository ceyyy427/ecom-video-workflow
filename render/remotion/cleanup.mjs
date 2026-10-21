// Pinned Remotion 4.0.519 kills its process before resolving page targets.
// Dispose pages while alive. Failure must stop this instance's own runner and
// stay a failed render; never force exit(0) or accept incomplete scene outputs.
async function bounded(operation, ms, message) {
 let timer;
 try {
  return await Promise.race([
   Promise.resolve().then(operation),
   new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),ms);}),
  ]);
 } finally {clearTimeout(timer);}
}
export async function closeRenderBrowser(browser, timeoutMs=5000) {
 try {
  await bounded(async()=>{
   const pages=await browser.pages();
   await Promise.all(pages.map(page=>page.close()));
   await browser.close({silent:true});
  },timeoutMs,'RENDER_CLEANUP_TIMEOUT: 渲染器关闭超时，请重试；未发布本次结果');
 } catch(error) {
  try {
   // Public on our pinned HeadlessBrowser, operating only its spawned process.
   await bounded(()=>browser.runner.closeProcess(),1000,'RENDER_CLEANUP_PROCESS_TIMEOUT');
  } catch(stopError) {
   throw new AggregateError([error,stopError],'渲染器关闭失败，结束自有进程失败',{cause:error});
  } finally {browser.disconnect();}
  throw error;
 }
}
export async function withRenderBrowser(browser, render) {
 let result, primary;
 try {result=await render();} catch(error) {primary=error;}
 try {await closeRenderBrowser(browser);} catch(cleanup) {
  if(primary)throw new AggregateError([primary,cleanup],'渲染失败，且关闭渲染器失败',{cause:primary});
  throw cleanup;
 }
 if(primary)throw primary;
 return result;
}
