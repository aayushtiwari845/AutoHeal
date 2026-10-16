// Optional browser acceptance checks; set AUTOHEAL_PLAYWRIGHT to a bundled module path if needed.
const { chromium } = require(process.env.AUTOHEAL_PLAYWRIGHT || 'playwright');
const assert = require('node:assert/strict');
(async () => {
 const edge = process.env.AUTOHEAL_EDGE || (process.platform === 'win32' ? require('node:path').join(process.env['PROGRAMFILES(X86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe') : undefined);
 const browser = await chromium.launch({headless:true, ...(edge ? {executablePath:edge} : {})});
 const page = await browser.newPage({viewport:{width:1366,height:768}});
 const errors=[]; page.on('pageerror',error=>errors.push(error.message)); page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text())});
 const results=[];
 await page.goto('http://127.0.0.1:8765/', {waitUntil:'networkidle'});
 await page.waitForFunction(()=>document.querySelector('#presetSelect').options.length===4 && document.querySelector('#modelSelect').value);
 assert.equal(await page.locator('#presetSelect').inputValue(),'grades');
 assert.ok((await page.locator('#codePane').innerText()).includes('averages'));
 assert.ok((await page.locator('#sampleNotice').innerText()).includes('PREWRITTEN'));
 results.push('Initial grade sample is visible and explicitly prewritten.');
 const waitDone=async()=>page.waitForFunction(()=>['VALIDATED','STRUCTURE PASSED','LIMIT REACHED','MODEL ERROR','STOPPED'].includes(document.querySelector('#runStatus').textContent),{timeout:30000});
 for (const id of ['grades','sales','text']) {
  await page.locator('#presetSelect').selectOption(id);
  await page.locator('#providerSelect').selectOption('replay');
  await page.locator('#runButton').click(); await waitDone();
  assert.equal(await page.locator('#runStatus').innerText(),'VALIDATED');
  assert.equal(await page.locator('#attemptSelect option').count(),2);
  assert.ok((await page.locator('#runFootnote').innerText()).includes('NO AI CALLS'));
  assert.ok(await page.locator('#checksBody .pass').count());
  const wrapped=await page.locator('#codePane').evaluate(e=>({scroll:e.scrollWidth,width:e.clientWidth}));
  assert.ok(wrapped.scroll<=wrapped.width+1,JSON.stringify({id,wrapped}));
  await page.locator('#attemptSelect').selectOption('0');
  assert.ok(await page.locator('#checksBody .fail').count());
  if(id==='grades') assert.equal(await page.locator('#exitMetric').innerText(),'Exit 0');
  else assert.ok((await page.locator('#stderr').innerText()).includes(id==='sales'?'TypeError':'AttributeError'));
  const before=await page.locator('#tracePosition').innerText(); await page.locator('#nextTrace').click(); const after=await page.locator('#tracePosition').innerText(); assert.notEqual(before,after);
  await page.locator('#nextAttempt').click(); await page.locator('#diffTab').click();
  assert.ok(await page.locator('.diff-line.added').count()); assert.ok(await page.locator('.diff-line.removed').count());
  await page.locator('#sourceTab').click(); await page.locator('#wrapLines').uncheck(); assert.equal(await page.locator('#codePane').evaluate(e=>e.classList.contains('wrap-lines')),false); await page.locator('#wrapLines').check();
  results.push(`${id}: automatic replay validates in 2 attempts; first failure, trace navigation, diff, wrap toggle pass.`);
 }
 await page.locator('#presetSelect').selectOption('grades'); await page.locator('#providerSelect').selectOption('replay'); await page.locator('input[name="runStyle"][value="manual"]').check(); await page.locator('#runButton').click();
 const pause=async()=>page.waitForFunction(()=>!document.querySelector('#advanceButton').disabled,{timeout:15000});
 await pause(); const stages=[];
 for(let i=0;i<7;i++) {
  await pause(); const caption=await page.locator('#advanceButton').innerText(); stages.push(caption);
  if(i===2) { await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight/2)); const rect=await page.locator('.control-window').boundingBox(); assert.ok(rect.y>=-1&&rect.y<=1,JSON.stringify(rect)); }
  await page.locator('#advanceButton').click();
  if(i<6) await page.waitForFunction(old=>!document.querySelector('#advanceButton').disabled && document.querySelector('#advanceButton').textContent!==old,caption,{timeout:15000});
 }
 await waitDone(); assert.equal(await page.locator('#runStatus').innerText(),'VALIDATED'); assert.deepEqual(stages,['Next: Generate →','Next: Execute →','Next: Evaluate →','Next: Reflect →','Next: Generate →','Next: Execute →','Next: Evaluate →']); results.push('Manual replay gates exactly Generate→Execute→Evaluate→Reflect→Generate→Execute→Evaluate; sticky Next controller stays at viewport top.');
 await page.locator('#newRunButton').click(); await page.locator('#presetSelect').selectOption('custom'); assert.equal(await page.locator('#taskInput').getAttribute('readonly'),null); assert.equal(await page.locator('#seedFailure').isDisabled(),true); assert.equal(await page.locator('#seedFailure').isChecked(),false); assert.equal(await page.locator('#providerSelect option[value="replay"]').isDisabled(),true); results.push('Custom mode has editable task/DATA, structural-only disclosure, and disables controlled fault/replay.');
 for(const width of [390,1366]) { await page.setViewportSize({width,height:768}); const bounds=await page.evaluate(()=>({viewport:innerWidth,body:document.documentElement.scrollWidth})); assert.ok(bounds.body<=bounds.viewport+1,JSON.stringify(bounds)); results.push(`${width}×768: no horizontal page overflow.`); }
 await page.locator('#aboutButton').click(); assert.equal(await page.locator('#aboutDialog').getAttribute('aria-labelledby'),'aboutTitle'); assert.ok((await page.locator('#aboutDialog').innerText()).includes('16014223003')); await page.keyboard.press('Escape'); results.push('About dialog opens, includes both credits, and closes by Escape.');
 assert.deepEqual(errors,[]); results.push('No page errors or console errors.');
 console.log(JSON.stringify({passed:true,results,errors},null,2)); await browser.close();
})().catch(e=>{console.error(e.stack);process.exit(1)});
