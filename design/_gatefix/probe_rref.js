/* design/_gatefix/probe_rref.js — which rule paints .cl-rref (colour rgb(127,29,29) on Kuva Crimson)? */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SCAN = `(() => {
  const el = document.querySelector('.cl-rref');
  if (!el) return { missing: true, count: document.querySelectorAll('.cl-rref').length };
  const hits = [];
  const walk = (rules, sheet) => {
    for (const r of rules) {
      if (r.cssRules) { walk(r.cssRules, sheet); continue; }
      if (!r.selectorText) continue;
      let m = false;
      try { m = el.matches(r.selectorText); } catch (e) { m = false; }
      if (m && (r.style.color || r.style.cssText)) hits.push({ sheet: sheet, sel: r.selectorText, color: r.style.color || '', text: r.style.cssText.slice(0, 120) });
    }
  };
  for (const sh of document.styleSheets) {
    try { walk(sh.cssRules, sh.href || '(inline)'); } catch (e) { hits.push({ sheet: sh.href, err: String(e).slice(0, 60) }); }
  }
  const chain = [];
  for (let n = el; n; n = n.parentElement) {
    const cs = getComputedStyle(n);
    chain.push({ tag: n.tagName.toLowerCase(), cls: String(n.className || '').slice(0, 30), color: cs.color, own: !!n.style.color, inline: n.getAttribute('style') || '' });
    if (n.tagName === 'BODY') break;
  }
  return { colour: getComputedStyle(el).color, hits, chain };
})()`;
(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  await page.goto(BASE + '/collection.html', { waitUntil: 'load' });
  await sleep(4000);
  await page.evaluate(() => { location.hash = '#relics'; });
  await sleep(3000);
  await page.evaluate(() => window.wfmApplyTheme(2));
  await sleep(900);
  const out = await page.evaluate(SCAN);
  console.log(JSON.stringify(out, null, 1).slice(0, 4000));
  await browser.close();
})().catch((e) => { console.error('PROBE FAILED: ' + e.stack); process.exit(1); });
