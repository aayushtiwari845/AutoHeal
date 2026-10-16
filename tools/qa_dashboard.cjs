/* Local browser acceptance checks. Run with the bundled Node/Playwright runtime. */
const { chromium } = require(process.env.AUTOHEAL_PLAYWRIGHT || 'C:/Users/Aayus/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'output', 'verification');
const checks = [];
const errors = [];

async function main() {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1080}, acceptDownloads:true});
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto('http://127.0.0.1:8765/');
    await page.locator('.preset-option').first().waitFor();
    await page.waitForFunction(() => document.querySelector('#modelSelect').value === 'qwen2.5-coder:7b');
    assert.equal(await page.locator('input[name=preset]:checked').inputValue(), 'grades');
    assert.equal(await page.locator('#taskInput').getAttribute('readonly'), '');
    checks.push('Default grade scenario, local model and read-only preset contract');
    await page.locator('#helpButton').click();
    assert.equal(await page.locator('#helpDialog').isVisible(),true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#helpDialog').isVisible(),false);
    checks.push('Help dialog opens and closes with Escape');

    async function run() {
      const started = page.waitForResponse(r => r.url().endsWith('/api/runs') && r.request().method() === 'POST');
      await page.locator('#runButton').click();
      const response = await started;
      assert.equal(response.status(),202);
      const id = (await response.json()).run_id;
      await page.waitForFunction(() => document.querySelector('#cancelButton').hidden && ['Validated','Structure passed','Limit reached','Model error','Stopped'].includes(document.querySelector('#runStatus').textContent), null, {timeout:180000});
      const trace = await (await page.request.get('http://127.0.0.1:8765/api/runs/'+id)).json();
      return trace;
    }
    for (const [id,title] of [['grades','Grade analytics'],['sales','Sales summary'],['text','Text statistics']]) {
      await page.locator('.preset-option').filter({hasText:title}).click();
      await page.locator('.mode-control label').filter({hasText:'Scripted replay'}).click();
      const trace = await run();
      assert.equal(trace.status,'succeeded');
      assert.equal(trace.attempts.length,2);
      assert.equal(trace.mode,'replay');
      assert.equal(await page.locator('.attempt-card').count(),2);
      assert.ok(await page.locator('#runContext').innerText().then(t=>t.includes('no AI model calls')));
      checks.push('Replay '+id+': actual failure, repair and semantic validation');
    }
    await page.locator('.attempt-card').last().getByText('Inspect Python source',{exact:true}).click();
    assert.ok(await page.locator('.code-line').count() > 0);
    await page.locator('#jsonView').click();
    assert.ok((await page.locator('#resultContent').innerText()).includes('token_count'));
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#exportButton').click();
    const download = await downloadPromise;
    await download.saveAs(path.join(output,'ui-exported-replay.json'));
    assert.equal(JSON.parse(fs.readFileSync(path.join(output,'ui-exported-replay.json'),'utf8')).status,'succeeded');
    checks.push('Source disclosure, JSON result view and real trace download');
    await page.locator('.preset-option').filter({hasText:'Grade analytics'}).click();
    await page.locator('.mode-control label').filter({hasText:'Live local model'}).click();
    const grade = await run();
    fs.writeFileSync(path.join(output,'ui-live-grade.json'),JSON.stringify(grade,null,2));
    assert.equal(grade.status,'succeeded');
    assert.equal(grade.attempts[0].seeded,true);
    assert.equal(grade.attempts[0].returncode,0);
    assert.equal(grade.attempts[0].validation.passed,false);
    assert.equal(grade.result.highest,'Mira');
    checks.push('Live seeded grade: logical failure followed by actual local-model repair');
    await page.locator('.attempt-card').last().getByText('Inspect Python source',{exact:true}).click();
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0,0); });
    await page.screenshot({path:path.join(root,'output','project','AutoHeal_Studio_Preview.png'),fullPage:true});
    await page.locator('.preset-option').filter({hasText:'Custom Python task'}).click();
    assert.equal(await page.locator('#taskInput').getAttribute('readonly'),null);
    assert.equal(await page.locator('#seedFailure').isChecked(),false);
    assert.equal(await page.locator('#seedFailure').isDisabled(),true);
    assert.equal(await page.locator('input[name=mode][value=replay]').isDisabled(),true);
    await page.locator('#taskInput').fill('Calculate the sum of the squares of the integers 1 through 20 inclusive. Output a single JSON object with the key sum_of_squares and its calculated numeric value.');
    const custom = await run();
    fs.writeFileSync(path.join(output,'ui-custom.json'),JSON.stringify(custom,null,2));
    assert.equal(custom.status,'succeeded');
    assert.equal(custom.validation_kind,'structural');
    assert.equal(custom.result.sum_of_squares,2870);
    assert.equal(await page.locator('#runStatus').innerText(),'Structure passed');
    assert.ok((await page.locator('#resultValidation').innerText()).toLowerCase().includes('no independent answer oracle'));
    assert.ok((await page.locator('#traceNote').innerText()).includes('Structure passed'));
    assert.equal(await page.locator('[data-phase=reflect]').evaluate(node => node.classList.contains('complete')),false);
    checks.push('Custom task: real generation and clear structural-only verification label');

    await page.locator('.preset-option').filter({hasText:'Grade analytics'}).click();
    await page.locator('#runButton').click();
    await page.locator('#cancelButton').waitFor({state:'visible'});
    await page.locator('#cancelButton').click();
    await page.waitForFunction(() => document.querySelector('#runStatus').textContent === 'Stopped', null, {timeout:10000});
    assert.equal(await page.locator('[data-phase=reflect]').evaluate(node => node.classList.contains('complete')),false);
    checks.push('Cancellation updates the dashboard to Stopped');
    await page.setViewportSize({width:390,height:844});
    await page.reload();
    await page.locator('.preset-option').first().waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    assert.equal(await page.locator('#refreshStatus').isVisible(),true);
    await page.screenshot({path:path.join(output,'mobile-dashboard.png'),fullPage:true});
    checks.push('390px mobile viewport has no horizontal overflow');
    assert.deepEqual(errors,[]);
    checks.push('No browser JavaScript errors');
    fs.writeFileSync(path.join(output,'ui-checks.json'),JSON.stringify({passed:true,checks,errors},null,2));
    console.log(JSON.stringify({passed:true,checks},null,2));
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error); process.exitCode=1;});
