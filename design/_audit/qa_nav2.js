/* Audit-1 check 3b: aria-current / active-pill truth table.
 *  - hard loads of every destination (what the shell renders at mount)
 *  - a click walk on the SPA from one clean load (what the pill shows after routing)
 *  - collection.html's own section row (Collection | Relics | Mastery | Cards)
 *   node design/_audit/qa_nav2.js   ->  design/_audit/nav2.json
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const READ = `(() => ({
  hash: location.hash, path: location.pathname,
  rail: [...document.querySelectorAll('#mainnav .navpill')].map(p => ({ v: p.dataset.v, active: p.classList.contains('active'), cur: p.getAttribute('aria-current') || null })),
  sub: [...document.querySelectorAll('nav.mainnav.subnav .navpill, nav.subnav .navpill')].map(p => ({ v: p.dataset.v, t: p.textContent.trim(), href: p.getAttribute('href'), active: p.classList.contains('active'), cur: p.getAttribute('aria-current') || null }))
}))()`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const out = { hard_loads: {}, click_walk: [], subnav: {} };

  /* 1. hard loads: a UNIQUE query per URL so the document really reloads (same query + new hash
        would be a same-document hash change and would not re-mount the shell) */
  const hard = [['/#home', '/?q=1#home'], ['/#trade', '/?q=2#trade'], ['/#inventory', '/?q=3#inventory'],
    ['/#tools', '/?q=4#tools'], ['/#tools/deals', '/?q=5#tools/deals'], ['/#more', '/?q=6#more'],
    ['/#market', '/?q=7#market'], ['/#player', '/?q=8#player'], ['/#history', '/?q=9#history'],
    ['/collection.html', '/collection.html'], ['/cards.html', '/cards.html'], ['/settings.html', '/settings.html'],
    ['/item.html', '/item.html']];
  for (const [label, url] of hard) {
    await page.goto(BASE + url, { waitUntil: 'networkidle2' });
    await sleep(700);
    const r = await page.evaluate(READ);
    out.hard_loads[label] = { landed: r.path + r.hash, active: r.rail.filter(p => p.active).map(p => p.v), ara: r.rail.filter(p => p.cur).map(p => p.v + '=' + p.cur) };
    console.log(`hard ${label.padEnd(16)} landed=${(r.path + r.hash).padEnd(28)} active=${JSON.stringify(r.rail.filter(p => p.active).map(p => p.v))} aria=${JSON.stringify(r.rail.filter(p => p.cur).map(p => p.v))} rails=${r.rail.length}`);
  }

  /* 2. one clean load, then click through the rail: does the pill/aria follow the router? */
  await page.goto(BASE + '/?fresh=1#home', { waitUntil: 'networkidle2' });
  await sleep(600);
  for (const v of ['trade', 'inventory', 'tools', 'home']) {
    await page.evaluate(v => document.querySelector('#mainnav .navpill[data-v="' + v + '"]').click(), v);
    await sleep(500);
    const r = await page.evaluate(READ);
    out.click_walk.push({ clicked: v, hash: r.hash, active: r.rail.filter(p => p.active).map(p => p.v), aria: r.rail.filter(p => p.cur).map(p => p.v) });
    console.log(`walk click ${v.padEnd(10)} hash=${r.hash.padEnd(11)} active=${JSON.stringify(r.rail.filter(p => p.active).map(p => p.v))} aria=${JSON.stringify(r.rail.filter(p => p.cur).map(p => p.v))}`);
  }
  /* and a workspace click */
  await page.evaluate(() => document.getElementById('toolsLauncher') && document.querySelector('#toolsLauncher a.tool[data-tool="ducats"]').click());
  await sleep(500);
  const r2 = await page.evaluate(READ);
  out.click_walk.push({ clicked: 'tool:ducats', hash: r2.hash, active: r2.rail.filter(p => p.active).map(p => p.v), aria: r2.rail.filter(p => p.cur).map(p => p.v) });
  console.log(`walk click tool:ducats hash=${r2.hash} active=${JSON.stringify(r2.rail.filter(p => p.active).map(p => p.v))} aria=${JSON.stringify(r2.rail.filter(p => p.cur).map(p => p.v))}`);

  /* 3. collection sub-nav */
  for (const u of ['/collection.html', '/collection.html#relics', '/collection.html#mastery', '/collection.html#cards']) {
    await page.goto(BASE + u, { waitUntil: 'networkidle2' });
    await sleep(900);
    const r = await page.evaluate(READ);
    out.subnav[u] = r.sub;
    console.log(`subnav ${u.padEnd(26)} ${r.sub.map(p => p.t + (p.active ? '*' : '') + (p.cur ? '[' + p.cur + ']' : '') + '<' + p.href + '>').join(' ')}`);
  }
  /* keyboard: tab into collection's section row and Enter on Mastery */
  await page.goto(BASE + '/collection.html', { waitUntil: 'networkidle2' });
  await sleep(800);
  const order = [];
  let hit = null;
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab');
    const f = await page.evaluate(() => { const a = document.activeElement; return a ? { tag: a.tagName, v: a.dataset ? a.dataset.v || '' : '', t: (a.innerText || '').trim().slice(0, 18), href: a.getAttribute && (a.getAttribute('href') || '') } : null; });
    order.push(f ? f.tag + (f.v ? '[' + f.v + ']' : '') + (f.href ? '(' + f.href + ')' : '') : 'null');
    if (f && f.v === 'mastery') { hit = i + 1; await page.keyboard.press('Enter'); await sleep(800); break; }
  }
  const after = await page.evaluate(READ);
  out.collection_keyboard = { tabs_to_mastery: hit, order, after_hash: after.hash, after_active: after.rail.filter(p => p.active).map(p => p.v), sub: after.sub };
  console.log(`collection keyboard: tabs to Mastery pill = ${hit}; order=${order.join(' > ')}`);
  console.log(`  after Enter: hash=${after.hash} sub=${after.sub.map(p => p.t + (p.active ? '*' : '')).join(' ')}`);

  fs.writeFileSync(path.join(__dirname, 'nav2.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/nav2.json');
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
