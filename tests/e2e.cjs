/* Optional actual-browser integration check. Starts its own isolated API server. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'..');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'mathtech-e2e-'));
const artifacts=process.env.E2E_ARTIFACTS||path.join(temporary,'artifacts');
fs.mkdirSync(artifacts,{recursive:true});
const python=process.env.PYTHON_EXECUTABLE||path.join(ROOT,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
let logs='',browser,server;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  server=spawn(python,['-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8127','--workers','1','--ws-max-size','4194304'],{cwd:ROOT,env:{...process.env,ADMIN_PASSWORD:'E2E-password-2026',DATA_DIR:path.join(temporary,'data'),PUBLIC_ORIGIN:'http://127.0.0.1:8127'},stdio:['ignore','pipe','pipe']});
  server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
  let ready=false;for(let i=0;i<60;i++){try{const r=await fetch('http://127.0.0.1:8127/api/health');if(r.ok){ready=true;break}}catch{}await delay(150)}
  assert(ready,'API did not start: '+logs);
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),args:['--no-sandbox','--disable-dev-shm-usage','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
  const context=await browser.newContext({viewport:{width:1600,height:1120},acceptDownloads:true});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error'&&!m.text().includes('401'))errors.push(m.text())});
  await page.goto('http://127.0.0.1:8127');
  await page.fill('#password','E2E-password-2026');await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#workspace:not([hidden])');
  await page.setInputFiles('#video-upload',path.join(ROOT,'samples/vehicle-validation.mp4'));
  await page.waitForFunction(()=>document.querySelector('#media-select').value!=='');
  await page.click('#run-analysis');
  await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='COMPLETED',null,{timeout:25000});
  await page.waitForFunction(()=>document.querySelector('#results-table').textContent.includes('bus'));
  await page.waitForFunction(()=>['feed','mask-feed','trail-feed'].every(id=>{const el=document.getElementById(id);return el.complete&&el.naturalWidth>0&&!el.hidden}));
  assert((await page.locator('#object-count').textContent())!=='0');
  await page.screenshot({path:path.join(artifacts,'dashboard-desktop.png'),fullPage:true});
  // Saved replay reads a persisted earlier frame rather than rerunning inference.
  await page.locator('#timeline').evaluate(el=>{el.value='1';el.dispatchEvent(new Event('input',{bubbles:true}))});
  await page.waitForFunction(()=>document.querySelector('#timeline').value==='1');
  await page.click('[data-page="analysis"]');await page.waitForSelector('[data-summary]');await page.click('[data-summary]');
  await page.waitForSelector('#summary-section:not([hidden])');
  const [download]=await Promise.all([page.waitForEvent('download'),page.click('[data-kind="json"]')]);
  const downloadPath=await download.path();const exported=JSON.parse(fs.readFileSync(downloadPath,'utf8'));
  assert(exported.frames.length===15);assert(exported.frames.some(f=>f.objects.some(o=>o.class_name==='bus'&&o.mask_area_px>0)));
  // Dataset editor -> save -> actual ZIP export.
  await page.click('[data-page="dataset"]');await page.click('[data-annotate]');await page.waitForFunction(()=>document.querySelector('#annotation-placeholder').hidden);
  const box=await page.locator('#annotation-canvas').boundingBox();
  for(const [x,y]of [[.15,.25],[.65,.25],[.65,.65],[.15,.65]])await page.mouse.click(box.x+box.width*x,box.y+box.height*y);
  await page.click('#finish-polygon');await page.click('#save-annotations');await page.waitForFunction(()=>document.querySelector('#media-list').textContent.includes('Annotations saved'));
  const [dataset]=await Promise.all([page.waitForEvent('download'),page.click('#export-dataset')]);assert(dataset.suggestedFilename()==='MathTech-Vehicle-Dataset.zip');
  await page.click('[data-page="models"]');await page.click('[data-verify]');await page.waitForFunction(()=>document.querySelector('#verify-yolov8n-seg').textContent.includes('Checksum verified'));
  await page.click('[data-page="settings"]');await page.waitForFunction(()=>document.querySelector('#system-details').textContent.includes('SQLite'));
  await page.locator('#settings-form [name=trail_length]').fill('30');await page.click('#settings-form button[type=submit]');
  await page.waitForFunction(()=>document.querySelector('#settings-form [name=trail_length]').value==='30');
  await page.click('[data-page="logs"]');await page.waitForFunction(()=>document.querySelector('#logs-table').textContent.includes('Analysis started'));
  // Live feed uses a browser synthetic camera, real WebSockets, JPEG decoding and ONNX inference.
  await page.click('[data-page="live"]');await page.click('#enable-camera');await page.waitForFunction(()=>document.querySelector('#camera-status').textContent==='CONNECTED');
  await page.click('#camera-to-dashboard');await page.click('#run-analysis');
  await page.waitForFunction(()=>document.querySelector('#session-title').textContent.startsWith('Camera')&&document.querySelector('#job-message').textContent.match(/[1-9]\d* saved frames/),null,{timeout:15000});
  await page.click('#pause-analysis');await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='PAUSED');
  await page.click('#pause-analysis');await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='RUNNING');
  await page.click('#stop-analysis');await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='STOPPED');
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(artifacts,'dashboard-mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);assert(!overflow,'Mobile dashboard has horizontal overflow');
  assert.deepEqual(errors,[],'Browser errors: '+errors.join('\n'));
  console.log('Browser E2E passed: video, masks, replay, exports, dataset, models, settings, logs, camera, pause/resume/stop, mobile layout.');
})().catch(e=>{console.error(e);console.error(logs.slice(-7000));process.exitCode=1}).finally(async()=>{if(browser)await browser.close();if(server)server.kill('SIGTERM');setTimeout(()=>{fs.rmSync(temporary,{recursive:true,force:true})},1500)});
