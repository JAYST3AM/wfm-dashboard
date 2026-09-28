/* design/_gatefix/probe_btncols3.js — (a) what the user sees when the Columns disclosure is opened
   right after a dark->light theme switch, (b) whether dropping background-color from .btn's
   transition list makes the computed value follow the theme (the proposed fix). */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const READ = `(() => { const b = document.getElementById('btnCols');
  return { bg: getComputedStyle(b).backgroundColor, color: getComputedStyle(b).color, open: document.getElementById('invAdv').open }; })()`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });

  /* (a) unfixed CSS: dark -> light, then open the disclosure */
  await page.goto(BASE + '/#inventory', { waitUntil: 'load' });
  await sleep(2500);
  await page.evaluate(() => window.wfmApplyTheme(2));
  await sleep(800);
  console.log('A after Kuva(2) closed: ' + JSON.stringify(await page.evaluate(READ)));
  await page.evaluate(() => window.wfmApplyTheme(14));
  await sleep(800);
  console.log('A after Frost(14) closed: ' + JSON.stringify(await page.evaluate(READ)));
  await page.evaluate(() => document.querySelector('#invAdv > summary').click());
  await sleep(100);
  console.log('A opened +100ms: ' + JSON.stringify(await page.evaluate(READ)));
  await sleep(1200);
  console.log('A opened +1.3s : ' + JSON.stringify(await page.evaluate(READ)));

  /* (b) proposed fix: no background-color transition on .btn */
  const page2 = await browser.newPage();
  await page2.setViewport({ width: 1920, height: 1080 });
  await page2.goto(BASE + '/#inventory', { waitUntil: 'load' });
  await sleep(2500);
  await page2.evaluate(() => {
    const st = document.createElement('style');
    st.textContent = '.btn{transition:border-color .2s ease,transform .1s ease,filter .2s ease}';
    document.head.appendChild(st);
  });
  await page2.evaluate(() => window.wfmApplyTheme(2));
  await sleep(800);
  console.log('B after Kuva(2) closed  : ' + JSON.stringify(await page2.evaluate(READ)));
  await page2.evaluate(() => window.wfmApplyTheme(14));
  await sleep(800);
  console.log('B after Frost(14) closed: ' + JSON.stringify(await page2.evaluate(READ)));
  await browser.close();
})().catch((e) => { console.error('PROBE FAILED: ' + e.stack); process.exit(1); });
