// Classification of the job shown on the S3 screen: current vs earlier (historical).
// Usage: node browser_check_jobs.js <url-with-#token> <flag-file> <completed-run-id> <readiness-id> [screenshot-dir]
// The server must run a (non-synthetic) STUB module whose wrapper loops until <flag-file> exists. Exits non-zero on the first failed expectation.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
let chromium;
try { ({ chromium } = require(process.env.PLAYWRIGHT_MODULE || '/opt/node-tools/node_modules/playwright')); } catch (e) { ({ chromium } = require('playwright')); }
const exe = process.env.PLAYWRIGHT_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const [url, flag, doneId, readyId, shots] = process.argv.slice(2);
const base = url.split('#')[0], tok = /token=([A-Za-z0-9_-]+)/.exec(url)[1];
const jobUrl = (id) => `${base}#token=${tok}&view=module&id=s3` + (id ? `&job=${id}` : '');

(async () => {
  const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
  const p = await b.newPage({ viewport: { width: 1000, height: 800 } });
  const errors = []; p.on('pageerror', (e) => errors.push(String(e)));
  const txt = async (s) => (await p.textContent(s)).trim();
  const shot = async (n) => { if (shots) await p.screenshot({ path: path.join(shots, n), fullPage: true }); };
  const running = () => p.evaluate(async (t) => (await (await fetch('/api/runs', { headers: { 'X-Workbench-Token': t } })).json()).runs.filter((r) => r.state !== 'DONE'), tok);
  const step = (m) => console.log('ok:', m);
  const waitExec = (v) => p.waitForFunction((x) => document.getElementById('v-exec').textContent === x, v, { timeout: 60000 });
  const bannerShown = () => p.locator('#past-banner').isVisible();
  const rows = (sel) => p.locator(sel + ' li').count();

  async function assertEarlier(id, label) {
    assert(await bannerShown(), label + ': the earlier-job banner must be visible');
    const t = await txt('#past-banner'); assert(t.includes('earlier job') && t.includes(id), label + ': banner names the job: ' + t);
    assert(t.includes('only that job'), label + ': banner scopes the result to that job');
    assert.strictEqual(await rows('#ready-rows'), 0, label + ': historical readiness stays out of the current Readiness section');
    assert.strictEqual(await txt('#ready-note'), '', label + ': no current readiness note');
    assert.strictEqual(await txt('#jobid'), id);
  }

  // 1. completed job opened by URL in a fresh page session
  await p.goto(jobUrl(doneId)); await waitExec('COMPLETED');
  assert.strictEqual(await txt('#v-repro'), 'Accepted replay reproduced', 'the actual result and badge are intact');
  await assertEarlier(doneId, 'fresh page, completed job'); assert((await rows('#past-ready-rows')) >= 1, 'its readiness records are shown under Details');
  await shot('r1-completed-url-fresh.png'); step('completed-job URL in a fresh page session carries the earlier-job banner; result and badge intact');

  // 2. reload of that URL
  await p.reload(); await waitExec('COMPLETED');
  assert.strictEqual(await txt('#v-repro'), 'Accepted replay reproduced'); await assertEarlier(doneId, 'reloaded completed job'); step('reloading the completed-job URL keeps the banner');

  // 3. an earlier readiness job by URL
  await p.goto('about:blank'); await p.goto(jobUrl(readyId)); await waitExec('COMPLETED'); assert.strictEqual(await txt('#v-p10'), 'Not applicable');
  await assertEarlier(readyId, 'earlier readiness job'); step('an earlier readiness job does not become current readiness');

  // 4. current readiness started in this page session, then an earlier job is viewed next to it
  await p.click('#btn-ready'); await p.waitForFunction(() => document.getElementById('ready-note').textContent.startsWith('Readiness checked'), null, { timeout: 60000 });
  assert(!(await bannerShown()), 'a readiness job started in this page session is current'); const cur = await rows('#ready-rows'); assert(cur >= 1);
  const note = await txt('#ready-note');
  await p.locator('#jobs li', { hasText: doneId }).click(); await p.waitForFunction(() => !document.getElementById('past-banner').hidden);
  assert.strictEqual(await rows('#ready-rows'), cur, 'viewing an earlier job leaves the current readiness rows alone'); assert.strictEqual(await txt('#ready-note'), note);
  assert(await bannerShown()); step('current readiness survives viewing an earlier job');

  // 5. an active job: started here, then reload and reload of its URL
  assert.strictEqual((await running()).length, 0);
  await p.click('#btn-run'); await p.waitForSelector('#active-bar:not([hidden])'); const A = (await running())[0].job_id;
  assert(!(await bannerShown()), 'a job running now is not shown as an earlier job');
  await p.reload(); await p.waitForSelector('#active-bar:not([hidden])');
  assert.strictEqual(await txt('#jobid'), A); assert(!(await bannerShown()), 'reload while active: no earlier-job banner'); assert(await p.locator('#btn-stop').isEnabled());
  assert.strictEqual((await running()).length, 1, 'reload did not stop the job');
  await p.goto('about:blank'); await p.goto(jobUrl(A)); await p.waitForSelector('#active-bar:not([hidden])'); await p.waitForFunction(() => document.getElementById('phase').textContent !== 'idle');
  assert.strictEqual(await txt('#jobid'), A); assert(!(await bannerShown()), 'active-job URL: no earlier-job banner'); assert.strictEqual((await running()).length, 1);
  await shot('r5-active-job-url.png'); step('viewing an active job (also after reload and by URL) is not labelled as history');

  // 6. explicit Stop of that attached job: completion display of a live job
  await p.click('#btn-stop'); await waitExec('CANCELLED'); await p.waitForSelector('#active-bar', { state: 'hidden' });
  assert(!(await bannerShown()), 'the job we were watching live finishes as a current job'); assert.strictEqual((await running()).length, 0); step('explicit Stop still works on the attached active job');

  // 7. normal completion of a job started in the current page session
  fs.rmSync(flag, { force: true });
  await p.click('#btn-run'); await p.waitForSelector('#active-bar:not([hidden])'); const B = (await running())[0].job_id; assert.notStrictEqual(B, A);
  for (const nav of ['home', 'settings']) { await p.click('header.top nav a[data-nav=' + nav + ']'); await p.waitForTimeout(300); }
  await p.click('header.top .brand'); await p.click('#module-cards .card a'); await p.waitForSelector('#view-s3:not([hidden])');
  fs.writeFileSync(flag, ''); await waitExec('COMPLETED');
  assert.strictEqual(await txt('#v-repro'), 'Accepted replay reproduced'); assert(!(await bannerShown()), 'a job started in this page session is not an earlier job');
  assert((await rows('#ready-rows')) >= 1, 'its own readiness records are the current readiness'); assert.strictEqual(await txt('#jobid'), B);
  await shot('r7-current-completion.png'); step('normal completion of a current-session job: result, badge, current readiness, no earlier-job banner');
  await p.goto('about:blank'); await p.goto(jobUrl(B)); await waitExec('COMPLETED'); await assertEarlier(B, 'the same job in a fresh page session'); step('the same job opened in a fresh page session is an earlier job');
  assert.deepStrictEqual(errors, [], 'no page errors'); await b.close(); console.log('JOB CLASSIFICATION CHECK PASSED');
})().catch((e) => { console.error('JOB CLASSIFICATION CHECK FAILED:', e && e.stack || e); process.exit(1); });
