"""No browser/UI: exercise the actual render cleanup adapter with lifecycle doubles."""

import subprocess


def test_render_cleanup_closes_pages_before_process_and_is_bounded():
    code = r"""
import assert from 'node:assert/strict';
import {closeRenderBrowser} from './render/remotion/src/cleanup.mjs';
const events=[];
const browser={pages:async()=>[{close:async()=>events.push('page')}],close:async()=>events.push('browser'),disconnect:()=>events.push('disconnect')};
await closeRenderBrowser(browser,100);
assert.deepEqual(events,['page','browser']);
const bad={runner:{closeProcess:async()=>{}},pages:async()=>[],close:()=>new Promise(()=>{}),disconnect:()=>events.push('disconnect')};
const started=Date.now();
await assert.rejects(closeRenderBrowser(bad,10),/RENDER_CLEANUP_TIMEOUT/);
assert(Date.now()-started<1000);
assert.equal(events.at(-1),'disconnect');
const error={runner:{closeProcess:async()=>{}},pages:async()=>[],close:async()=>{throw new Error('close failed')},disconnect:()=>{}};
await assert.rejects(closeRenderBrowser(error,100),/close failed/);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], text=True, capture_output=True, timeout=5
    )
    assert result.returncode == 0, result.stderr


def test_customer_package_includes_render_cleanup_dependency_only():
    from ecom_video.customer_setup import package_path_allowed

    assert package_path_allowed("render/remotion/src/cleanup.mjs")
    assert not package_path_allowed("render/remotion/unreviewed.mjs")


def test_successful_cleanup_releases_owned_inherited_stdio_without_forcing_exit():
    code = r"""
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {closeRenderBrowser} from './render/remotion/src/cleanup.mjs';
const child=spawn(process.execPath,['-e','setTimeout(()=>{},1800)'],{stdio:['ignore','ignore','pipe']});
child.unref();
const seen=[];
const browser={pages:async()=>[],close:async()=>seen.push('closed'),runner:{forgetEventLoop:()=>{seen.push('unref');child.stderr.unref();}}};
await closeRenderBrowser(browser,100);
assert.deepEqual(seen,['closed','unref']);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], text=True, capture_output=True, timeout=1.2
    )
    assert result.returncode == 0, result.stderr


def test_cleanup_dependency_uses_source_directory_supported_by_0131_loader():
    from pathlib import Path

    engine = Path(__file__).resolve().parents[1] / "render/remotion"
    assert "from './src/cleanup.mjs'" in (engine / "render.mjs").read_text()
    assert (engine / "src/cleanup.mjs").is_file()
    assert not (engine / "cleanup.mjs").exists()


def test_cleanup_kills_owned_process_if_page_disposal_fails_and_preserves_render_error():
    code = r"""
import assert from 'node:assert/strict';
import {closeRenderBrowser,withRenderBrowser} from './render/remotion/src/cleanup.mjs';
for(const stage of ['pages-error','pages-hang','page-error','page-hang']){
 const seen=[];
 const fail=()=>stage.endsWith('hang')?new Promise(()=>{}):Promise.reject(new Error(stage));
 const b={pages:()=>stage.startsWith('pages')?fail():Promise.resolve([{close:fail}]),close:async()=>seen.push('close'),runner:{closeProcess:async()=>seen.push('owned-stop')},disconnect:()=>seen.push('disconnect')};
 await assert.rejects(closeRenderBrowser(b,10));
 assert.deepEqual(seen,['owned-stop','disconnect']);
}
const primary=new Error('render failed'),cleanup=new Error('cleanup failed');
const b={pages:async()=>[],close:async()=>{throw cleanup},runner:{closeProcess:async()=>{}},disconnect:()=>{}};
await assert.rejects(withRenderBrowser(b,async()=>{throw primary}),e=>e.cause===primary&&e.errors[0]===primary&&e.errors[1]===cleanup);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code], text=True, capture_output=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
