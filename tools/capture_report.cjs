// Capture actual, labelled UI states. Requires Playwright and Microsoft Edge.
const {chromium}=require(process.env.AUTOHEAL_PLAYWRIGHT||'playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'..');
const DIR=path.join(ROOT,'docs/screenshots');
const EVIDENCE=path.join(ROOT,'docs/evidence');
const BASE=process.env.AUTOHEAL_URL||'http://127.0.0.1:8765';
const entries={};
(async()=>{
 fs.mkdirSync(DIR,{recursive:true});fs.mkdirSync(EVIDENCE,{recursive:true});
 const edge=process.env.AUTOHEAL_EDGE||(process.platform==='win32'?path.join(process.env['PROGRAMFILES(X86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'):undefined);
 const browser=await chromium.launch({headless:true,...(edge?{executablePath:edge}:{})});
 const errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1120,height:1000},deviceScaleFactor:1});
  page.on('pageerror',error=>errors.push(String(error)));
  await page.goto(BASE);await page.locator('#presetSelect option[value=custom]').waitFor({state:'attached'});
  await page.waitForFunction(()=>document.querySelector('#modelSelect').value==='qwen2.5-coder:7b');
  async function read(id){return (await page.request.get(BASE+'/api/runs/'+id)).json();}
  async function uiSync(id,predicate){let result;for(let i=0;i<1400;i++){result=await read(id);if(predicate(result)){
   const latest=result.attempts.at(-1);
   await page.waitForFunction(({id,count,code,status})=>{
    if(!document.querySelector('#runFootnote').textContent.includes(id))return false;
    if(count&&document.querySelector('#attemptSelect').value!==String(count-1))return false;
    if(code){const displayed=[...document.querySelectorAll('#codePane .line-text')].map(e=>e.textContent.trimEnd()).join('\n').trim();if(displayed!==code.split('\n').map(s=>s.trimEnd()).join('\n').trim())return false;}
    const label=document.querySelector('#runStatus').textContent;
    return status==='succeeded'?label==='VALIDATED':status==='cancelled'?label==='STOPPED':true;
   },{id,count:result.attempts.length,code:latest?.code||'',status:result.status},{timeout:15000});
   return result;
  }await page.waitForTimeout(150);}throw Error('State timeout '+JSON.stringify(result));}
  async function begin(preset,control='manual'){
   if(!await page.locator('#newRunButton').isDisabled())await page.locator('#newRunButton').click();
   await page.locator('#presetSelect').selectOption(preset);await page.locator('#providerSelect').selectOption('replay');
   await page.locator(`input[name=runStyle][value=${control}]`).check();
   const response=page.waitForResponse(r=>r.url()===BASE+'/api/runs'&&r.request().method()==='POST');
   await page.locator('#runButton').click();const id=(await (await response).json()).run_id;
   return id;
  }
  async function advance(id,nextPhase,nextAttempt){await page.locator('#advanceButton').click();return uiSync(id,s=>s.awaiting_step&&s.next_phase===nextPhase&&s.next_attempt===nextAttempt);}
  async function shot(key,name,selector,caption,observation,run){
   const file=path.join(DIR,name+'.png');
   if(selector){
    await page.locator(selector).evaluate(element=>element.scrollIntoView({block:'center'}));
    const rect=await page.locator(selector).boundingBox();
    await page.evaluate(y=>window.scrollBy(0,y-135),rect.y);
    await page.locator(selector).screenshot({path:file});
   }else await page.screenshot({path:file,fullPage:true});
   entries[key]={file:path.relative(ROOT,file).replaceAll('\\','/'),caption,observation,run_id:run?.id||null,mode:run?.mode||'ready',provider:run?.provider||null,control_mode:run?.control_mode||null,redaction:'No credentials or private data appear. Fixed teaching datasets only.'};
  }
  await shot('overview','01-workbench-overview',null,'The complete Windows 95-inspired workbench, ready before a run.','Task contract, input DATA, provider and control settings, labelled prewritten Python sample, process output and result-check panels are visible. No model call or execution has occurred.');
  const grade=await begin('grades');await uiSync(grade,s=>s.awaiting_step);
  let state=await advance(grade,'execute',1);
  await shot('manual_candidate','02-manual-candidate','.source-window','Step-through mode: the labelled controlled-fault candidate is ready before execution.','Grade replay attempt 1 is prewritten. The source calculates an unweighted average and has not executed at this paused boundary.',state);
  await advance(grade,'evaluate',1);state=await advance(grade,'reflect',1);
  await shot('semantic_failure','03-semantic-check-failure','.evaluation-window','A zero exit code can still produce an incorrect answer.','Grade attempt 1 ran successfully but failed independent weighted-result checks; field-level expected and actual values are shown.',state);
  state=await advance(grade,'generate',2);await page.locator('#feedbackDisclosure').evaluate(e=>e.open=true);
  await shot('reflection','04-structured-repair-feedback','#feedbackDisclosure','Structured failure evidence is ready for the next candidate.','The completed Reflect stage stores actual wrong result fields and corrective constraints. This scripted run uses fixed replacement source and makes no AI call. The scrollable JSON view is shown at its start.',state);
  state=await advance(grade,'execute',2);
  await shot('repaired_candidate','05-repaired-source','.source-window','The second scripted candidate uses weighted scores and explicit result construction.','The replacement is fixed replay source, paused before Python execution. It uses the original DATA and does not substitute a reference answer.',state);
  await page.locator('#diffTab').click();
  await shot('diff','06-source-changes','.source-window','The Changes view compares the actual first and second candidate sources.','Added and removed lines are computed from stored source using an LCS comparison; code remains selectable with true source line numbers.',state);
  await page.locator('#sourceTab').click();await advance(grade,'evaluate',2);await page.locator('#advanceButton').click();state=await uiSync(grade,s=>s.status==='succeeded');
  await page.locator('#feedbackDisclosure').evaluate(e=>e.open=false);await page.locator('#resultDisclosure').evaluate(e=>e.open=false);
  await shot('validation','07-independent-validation','.evaluation-window','Grade replay terminates after the independent reference checks pass.','All fixed-preset result fields pass. The displayed final JSON is the program output, and the loop stops at attempt 2.',state);
  fs.writeFileSync(path.join(EVIDENCE,`manual-grades-${grade}.json`),JSON.stringify(state,null,2)+'\n');
  await page.locator('#localsDisclosure').evaluate(e=>e.open=true);
  for(let i=0;i<8;i++)await page.locator('#nextTrace').click();
  await shot('trace','08-captured-python-locals','.locals-disclosure','Captured Python line events show source location and bounded local-variable snapshots.','These are actual CPython observations recorded before each selected line, replayed after execution. They are not a live line debugger.',state);
  const downloadPromise=page.waitForEvent('download');await page.locator('#exportButton').click();const download=await downloadPromise;const exportPath=path.join(EVIDENCE,download.suggestedFilename());await download.saveAs(exportPath);
  assert.equal(JSON.parse(fs.readFileSync(exportPath,'utf8')).id,grade);
  const exportPage=await browser.newPage({viewport:{width:800,height:430}});await exportPage.goto(BASE+'/api/runs/'+grade);await exportPage.screenshot({path:path.join(DIR,'09-actual-trace-json.png'),fullPage:false});
  entries.export={file:'docs/screenshots/09-actual-trace-json.png',caption:'The exported run is machine-readable JSON with exact input, candidates, execution and stage evidence.',observation:'The dashboard Export trace button downloaded this same run; its ID was checked against the current run. The browser view shows the real API snapshot, with no manufactured fields.',run_id:grade,mode:'replay',control_mode:'manual',redaction:'No credentials; fixed teaching data.'};await exportPage.close();
  const sales=await begin('sales');await uiSync(sales,s=>s.awaiting_step);await advance(sales,'execute',1);state=await advance(sales,'evaluate',1);
  await shot('execution_failure','10-runtime-traceback','.output-window','A separate sales replay demonstrates a real Python exception and traceback.','Attempt 1 sums raw string amounts using sum, whose starting value is numeric zero. Python exits with a TypeError; stdout, stderr, exit code and elapsed process time are captured.',state);
  await page.locator('#stopButton').click();state=await uiSync(sales,s=>s.status==='cancelled');fs.writeFileSync(path.join(EVIDENCE,`manual-sales-${sales}.json`),JSON.stringify(state,null,2)+'\n');
  const auto=await begin('text','auto');state=await uiSync(auto,s=>s.status==='succeeded');
  await page.locator('#historyDisclosure').evaluate(e=>e.open=true);await page.locator('#historyDisclosure').scrollIntoViewIfNeeded();
  await shot('automatic','11-automatic-event-history','.control-window','Automatic replay advances through the recorded stages and stops after successful validation.','Text replay executes a failing source and a corrected source without manual stepping. The event history records actual Generate, Execute, Evaluate and Reflect stage transitions.',state);
  fs.writeFileSync(path.join(EVIDENCE,`automatic-text-${auto}.json`),JSON.stringify(state,null,2)+'\n');
  await page.locator('#newRunButton').click();await page.locator('#aboutButton').click();
  await shot('authors','12-project-credits','#aboutDialog','Joint laboratory submission and explanation of the two demonstration modes.','Both student names, roll numbers and divisions appear in the About view. Live and replay modes are explained separately.');
  if(process.argv.includes('--live-case')){
   await page.keyboard.press('Escape');
   for(const id of ['historyDisclosure','localsDisclosure','feedbackDisclosure','resultDisclosure'])await page.locator('#'+id).evaluate(e=>e.open=false);
   await page.locator('#presetSelect').selectOption('grades');await page.locator('#providerSelect').selectOption('ollama');
   await page.locator('input[name=runStyle][value=manual]').check();
   const response=page.waitForResponse(r=>r.url()===BASE+'/api/runs'&&r.request().method()==='POST');await page.locator('#runButton').click();
   const id=(await(await response).json()).run_id;await uiSync(id,s=>s.awaiting_step);
   await advance(id,'execute',1);await advance(id,'evaluate',1);await advance(id,'reflect',1);await advance(id,'generate',2);
   state=await advance(id,'execute',2);
   assert.equal(await page.locator('#sourceOrigin').innerText(),'MODEL-GENERATED PYTHON');
   await page.locator('#codePane').evaluate(e=>e.scrollTop=0);
   await shot('live_repair','13-live-ollama-candidate','.source-window','A live Ollama repair is paused before execution in the same step-through interface.','Unlike the scripted walkthrough, this candidate was actually generated by the selected local model from the controlled grade fault and its failed result checks. The source header identifies it as model-generated Python. The captured state precedes its execution.',state);
   await advance(id,'evaluate',2);await page.locator('#advanceButton').click();
   state=await uiSync(id,s=>s.status==='succeeded'||s.awaiting_step);
   if(state.status!=='succeeded'){await page.locator('#stopButton').click();state=await uiSync(id,s=>s.status==='cancelled');}
   fs.writeFileSync(path.join(EVIDENCE,`manual-live-grades-${id}.json`),JSON.stringify(state,null,2)+'\n');
   console.log('LIVE WALKTHROUGH '+id+': '+state.status);
  }
  fs.writeFileSync(path.join(DIR,'index.json'),JSON.stringify({screenshots:entries},null,2)+'\n');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({screenshots:Object.keys(entries),errors,manual_grade:grade,runtime_failure:sales,automatic_text:auto,export_verified:true},null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
