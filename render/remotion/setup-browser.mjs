import fs from 'node:fs';
import {ensureBrowser} from '@remotion/renderer';

const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const system = fs.existsSync(chrome);
const result = await ensureBrowser({
  browserExecutable: system ? chrome : undefined,
  chromeMode: system ? 'chrome-for-testing' : 'headless-shell',
  logLevel: 'error',
});
if (result.type === 'no-browser' || result.type === 'version-mismatch') {
  throw new Error('渲染浏览器未就绪，请检查首次安装指南');
}
console.log(JSON.stringify({ready: true, type: result.type, path: result.path}));
