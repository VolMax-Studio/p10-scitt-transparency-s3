// Browser scenario for the module home screen. Usage: node browser_check.js <url-with-#token> [screenshot-dir]
// Environment: PLAYWRIGHT_MODULE (default /opt/node-tools/node_modules/playwright), PLAYWRIGHT_CHROMIUM (default the pre-installed Chromium).
// Exits non-zero on the first failed expectation. Meant for a server with a STUB module (synthetic runs) whose workspace already holds one
// finished job and a stub wrapper that runs "forever".
const assert = require('assert');
const path = require('path');
let chromium;
try { ({ chromium } = require(process.env.PLAYWRIGHT_MODULE || '/opt/node-tools/node_modules/playwright')); } catch (e) { ({ chromium } = require('playwright')); }
const exe = process.env.PLAYWRIGHT_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const [url, shots] = process.argv.slice(2);
const base = url.split('#')[0], tok = /token=([A-Za-z0-9_-]+)/.exec(url)[1];
const TITLE = 'S3 — Accepted capture replay';
const DESC = 'Reproduce the accepted S3 capture offline using the approved package and the existing verification chain.';

(async () => {
  const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
  const p = await b.newPage({ viewport: { width: 1000, height: 760 } });
  const errors = []; p.on('pageerror', (e) => errors.push(String(e)));
  const shot = async (n) => { if (shots) await p.screenshot({ path: path.join(shots, n), fullPage: true }); };
  const txt = (sel) => p.textContent(sel);
  const visible = (sel) => p.locator(sel).isVisible();
  const runs = () => p.evaluate(async (t) => (await (await fetch('/api/runs', { headers: { 'X-Workbench-Token': t } })).json()).runs, tok);
  const step = (m) => console.log('ok:', m);

  // 1. Home
  await p.goto(url); await p.waitForSelector('#module-cards .card');
  assert.strictEqual(await p.locator('#module-cards .card').count(), 1, 'exactly one module card');
  assert.strictEqual((await txt('#module-cards .card h2')).trim(), TITLE);
  assert.strictEqual((await txt('#module-cards .card p')).trim(), DESC);
  assert.strictEqual((await txt('#module-cards .card a')).trim(), 'Open module');
  assert.strictEqual(await p.locator('#module-cards a, #module-cards button').count(), 1, 'no placeholder links or buttons');
  const home = await p.locator('#view-home').innerText();
  for (const w of ['S1', 'S2', 'verified', 'reproduced', 'MATCH', 'BINDING', 'COMPLETED']) assert(!home.includes(w), 'Home must not mention ' + w);
  assert.strictEqual((await txt('header.top .brand')).trim(), 'P10 Replay Workbench');
  assert(!(await visible('#active-bar')), 'no active job yet');
  await shot('01-home.png'); step('home shows one module card, no badge, no placeholders');

  // 2. S3 module screen
  await p.click('#module-cards .card a'); await p.waitForSelector('#view-s3:not([hidden])');
  assert.strictEqual((await txt('#s3-title')).trim(), TITLE);
  for (const id of ['exec', 'p10', 'repro']) assert.strictEqual((await txt('#v-' + id)).trim(), '-', 'results start empty: ' + id);
  assert(!(await visible('#past-banner')), 'no past job is shown');
  assert((await p.locator('#jobs li').count()) >= 1, 'history lists the earlier job');
  assert((await txt('#sum-lean')).trim().startsWith('/'), 'saved Lean path is shown in the summary');
  assert.strictEqual(await p.locator('#view-home').isHidden(), true);
  const s3text = await p.locator('#view-s3').innerText();
  assert(!/Accepted replay reproduced/.test(s3text), 'an earlier successful job must not make the module look verified');
  await shot('02-s3-module.png'); step('S3 screen opens empty; history does not populate the result panels');

  // 3. Host settings and back
  await p.click('#view-s3 a[data-nav=settings]'); await p.waitForSelector('#view-settings:not([hidden])');
  assert((await p.inputValue('#leanbin')).startsWith('/'), 'saved Lean path restored in the fields');
  await p.fill('#deadline', '77'); await p.click('#btn-save-settings'); await p.waitForFunction(() => document.getElementById('settings-status').textContent === 'Host settings saved.');
  await shot('03-host-settings.png');
  await p.click('#view-settings a[data-nav=home]'); await p.waitForSelector('#view-home:not([hidden])');
  await p.click('#module-cards .card a'); await p.waitForSelector('#view-s3:not([hidden])');
  assert.strictEqual((await txt('#sum-deadline')).trim(), '77 minutes'); step('Home > S3 > Host settings > S3 keeps and shows the saved settings');

  // 4. Start a (synthetic) job that keeps running
  assert.strictEqual((await runs()).filter((r) => r.state !== 'DONE').length, 0);
  await p.click('#btn-run'); await p.waitForSelector('#active-bar:not([hidden])');
  const active = (await runs()).filter((r) => r.state !== 'DONE'); assert.strictEqual(active.length, 1); const jid = active[0].job_id;
  assert((await txt('#active-text')).includes(jid));
  assert.strictEqual(await p.locator('#btn-stop').isEnabled(), true);
  await shot('04-running-in-s3.png');

  // 5. Navigation does not stop it
  for (const nav of ['home', 'settings', 'home']) { await p.click('header.top nav a[data-nav=' + nav + ']'); await p.waitForTimeout(500);
    const now = (await runs()).filter((r) => r.state !== 'DONE'); assert.strictEqual(now.length, 1, 'job still running after navigating to ' + nav); assert.strictEqual(now[0].job_id, jid);
    assert(await visible('#active-bar'), 'indicator visible on ' + nav); }
  await shot('05-home-with-active-job.png');
  await p.click('#active-link'); await p.waitForSelector('#view-s3:not([hidden])');
  assert.strictEqual((await txt('#jobid')).trim(), jid, 'the indicator link opens the existing status view of that job');
  await p.reload(); await p.waitForSelector('#active-bar:not([hidden])');
  assert.strictEqual((await runs()).filter((r) => r.state !== 'DONE').length, 1, 'a reload does not stop the job'); step('navigation, links and reload leave the running job untouched');

  // 6. Explicit Stop still works
  await p.goto(url.split('#')[0] + '#token=' + tok + '&view=module&id=s3'); await p.waitForSelector('#view-s3:not([hidden])');
  await p.waitForFunction(() => !document.getElementById('btn-stop').disabled);
  await p.click('#btn-stop');
  await p.waitForFunction(() => document.getElementById('active-bar').hidden, null, { timeout: 60000 });
  await p.waitForFunction(() => document.getElementById('v-exec').textContent === 'CANCELLED', null, { timeout: 30000 });
  assert.strictEqual((await runs()).filter((r) => r.state !== 'DONE').length, 0);
  assert.strictEqual((await txt('#v-repro')).includes('reproduced'), false); await shot('06-after-stop.png'); step('explicit Stop cancels the job');

  // 7. Past job view is labelled, and Home stays neutral
  const done = (await runs()).filter((r) => r.state === 'DONE' && r.execution === 'COMPLETED')[0];
  await p.locator('#jobs li', { hasText: done.job_id }).click(); await p.waitForSelector('#past-banner:not([hidden])');
  assert((await txt('#past-banner')).includes('earlier job')); await p.waitForFunction(() => document.getElementById('v-exec').textContent === 'COMPLETED');
  await shot('07-past-job.png');
  await p.click('#view-s3 a[data-nav=home]'); await p.waitForSelector('#view-home:not([hidden])');
  const home2 = await p.locator('#view-home').innerText(); for (const w of ['reproduced', 'verified', 'MATCH', 'COMPLETED']) assert(!home2.includes(w));
  assert(!(await visible('#module-cards .badge'))); step('a past successful job is labelled and never shows on Home');

  // 8. Unknown module and pages
  for (const [hash, expect] of [['view=module&id=s9', 'Unknown module'], ['view=module&id=S3', 'Unknown module'], ['view=module&id=..%2Fx', 'Unknown module'], ['view=module', 'Unknown module'], ['view=bogus', 'Unknown module']]) {
    await p.goto(base + '#token=' + tok + '&' + hash); await p.waitForSelector('#view-unknown:not([hidden])');
    assert.strictEqual((await txt('#unknown-title')).trim(), expect, hash); assert(await p.locator('#view-s3').isHidden(), 'no module screen for ' + hash); }
  await shot('08-unknown-module.png'); await p.click('#view-unknown a[data-nav=home]'); await p.waitForSelector('#view-home:not([hidden])');
  step('unknown module identifiers are rejected'); assert.deepStrictEqual(errors, [], 'no page errors'); await b.close(); console.log('BROWSER CHECK PASSED');
})().catch((e) => { console.error('BROWSER CHECK FAILED:', e && e.stack || e); process.exit(1); });
