import fs from 'node:fs';
import {withRenderBrowser} from './cleanup.mjs';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {openBrowser,selectComposition,renderMedia,renderStill} from '@remotion/renderer';
const chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browserExecutable=fs.existsSync(chrome)?chrome:undefined;
// A full system Chrome requires new headless mode; the default is Headless Shell.
const chromeMode=browserExecutable?'chrome-for-testing':'headless-shell';
const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const serveUrl=await bundle({entryPoint:path.resolve(import.meta.dirname,'src/index.tsx'),publicDir:config.publicDir});
const browser=await openBrowser('chrome',{browserExecutable,chromeMode});
await withRenderBrowser(browser,async()=>{
 for(const shot of config.shots){
  const inputProps=shot.props;
  const common={serveUrl,puppeteerInstance:browser,chromeMode};
  const composition=await selectComposition({...common,id:'ProductShot',inputProps});
  await renderStill({...common,composition,inputProps,output:path.join(config.outputDir,shot.key+'.png'),frame:Math.min(inputProps.frames-1,45),logLevel:'error'});
  if(config.mode!=='still') await renderMedia({...common,composition,inputProps,codec:'h264',outputLocation:path.join(config.outputDir,shot.key+'.mp4'),concurrency:2,crf:20,pixelFormat:'yuv420p',muted:true,logLevel:'error'});
 }
});
