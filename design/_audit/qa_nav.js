/* Audit-1 check 3: NAVIGATION.
 *   rail entries -> destination + active pill + aria-current
 *   legacy hashes (#more #market #player #mastery #history #trader)
 *   browser back/forward sanity
 *   keyboard-only: tab order through the rail into a workspace, Enter opens a launcher entry
 *   workspace headings + back links
 *   node design/_audit/qa_nav.js   ->  design/_audit/nav.json
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const STATE = `(() => {
  const vis = [...document.querySelectorAll('main > section')].filter(s => !s.classList.contains('hidden')).map(s => s.id);
  const ws = [...document.querySelectorAll('#toolsWs .tws')].filter(w => !w.classList.contains('hidden')).map(w => w.dataset.tool);
  const launcher = document.getElementById('toolsLauncher');
  const active = [...document.querySelectorAll('#mainnav .navpill.active')].map(p => p.dataset.v);
  const aria = [...document.querySelectorAll('#mainnav .navpill[aria-current]')].map(p => p.dataset.v);
  const main = document.querySelector('main');
  const mr = main ? main.getBoundingClientRect() : null;
  return { href: location.href, path: location.pathname, hash: location.hash,
    visibleSections: vis, visibleWorkspaces: ws, launcherHidden: launcher ? launcher.classList.contains('hidden') : null,
    active, aria, mainTextLen: main ? main.innerText.trim().length : null,
    mainWidth: mr ? Math.round(mr.width) : null, mainTop: mr ? Math.round(mr.top) : null,
    activePillCount: document.querySelectorAll('#mainnav .navpill.active').length,
    pillCount: document.querySelectorAll('#mainnav .navpill').length,
    heading: (() => { const h = document.querySelector('#view-tools .tws:not(.hidden) .tws-name'); return h ? h.textContent : null; })(),
    viewPlayersVisible: (() => { const p = document.getElementById('view-player'); return p ? !p.classList.contains('hidden') : null; })(),
    pcText: (() => { const p = document.getElementById('view-player'); return p ? p.innerText.trim().length : 0; })(),
    mhVisible: (() => { const m = document.getElementById('view-mastery'); return m ? !m.classList.contains('hidden') : null; })(),
    mhText: (() => { const m = document.getElementById('view-mastery'); return m ? m.innerText.trim().length : 0; })(),
    collTab: (() => { const t = document.querySelector('#collSections .navpill.active, #sectionRow .navpill.active, #mainnav.subnav .navpill.active'); return t ? t.textContent.trim() : null; })() };
})();`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const out = { rail: {}, legacy: {}, history: {}, keyboard: {}, headings: {}, subnav: {} };
  await page.goto(BASE + '/#home', { waitUntil: 'networkidle2' });
  await sleep(600);

  /* ---- 1. every rail entry: click it for real, record where it lands ---- */
  for (const v of ['home', 'trade', 'inventory', 'collection', 'tools', 'settings']) {
    await page.goto(BASE + '/#home', { waitUntil: 'networkidle2' });
    await sleep(300);
    const clicked = await page.evaluate(v => { const a = document.querySelector('#mainnav .navpill[data-v="' + v + '"]');
      if (!a) return null; const h = a.getAttribute('href'); a.click(); return h; }, v);
    await sleep(700);
    const st = await page.evaluate(STATE);
    out.rail[v] = { href_attr: clicked, landed: st.href, path: st.path, hash: st.hash, visibleSections: st.visibleSections,
      visibleWorkspaces: st.visibleWorkspaces, launcherHidden: st.launcherHidden, active: st.active, aria: st.aria,
      activePillCount: st.activePillCount, mainTextLen: st.mainTextLen, mainWidth: st.mainWidth, collTab: st.collTab,
      viewPlayersVisible: st.viewPlayersVisible, pcText: st.pcText };
    console.log(`rail ${v.padEnd(11)} href=${clicked} -> ${st.path}${st.hash} sections=${JSON.stringify(st.visibleSections)} ws=${JSON.stringify(st.visibleWorkspaces)} ` +
      `launcherHidden=${st.launcherHidden} active=${st.active} aria=${st.aria} pills=${st.pillCount} activeCount=${st.activePillCount} textLen=${st.mainTextLen}`);
  }

  /* ---- 2. legacy hashes ---- */
  for (const h of ['#more', '#market', '#player', '#mastery', '#history', '#trader', '#search?q=forma']) {
    await page.goto(BASE + '/' + h, { waitUntil: 'networkidle2' });
    await sleep(900);
    const st = await page.evaluate(STATE);
    out.legacy[h] = { landed: st.href, path: st.path, hash: st.hash, visibleSections: st.visibleSections,
      visibleWorkspaces: st.visibleWorkspaces, launcherHidden: st.launcherHidden, active: st.active, aria: st.aria,
      mainTextLen: st.mainTextLen, mainWidth: st.mainWidth, heading: st.heading, pcText: st.pcText, mhText: st.mhText,
      blank: st.mainTextLen < 50 || st.mainWidth < 100 };
    console.log(`legacy ${h.padEnd(14)} -> ${st.path}${st.hash} sections=${JSON.stringify(st.visibleSections)} ws=${JSON.stringify(st.visibleWorkspaces)} ` +
      `heading=${st.heading} active=${st.active} aria=${st.aria} textLen=${st.mainTextLen} blank=${out.legacy[h].blank}`);
  }

  /* ---- 3. back / forward ---- */
  await page.goto(BASE + '/#home', { waitUntil: 'networkidle2' }); await sleep(400);
  const seq = [];
  for (const v of ['trade', 'inventory', 'tools']) {
    await page.evaluate(v => document.querySelector('#mainnav .navpill[data-v="' + v + '"]').click(), v);
    await sleep(450);
    seq.push(await page.evaluate(() => location.hash));
  }
  /* open a workspace, then walk back twice, then forward once */
  await page.evaluate(() => document.querySelector('#toolsLauncher a.tool[data-tool="deals"]').click());
  await sleep(500);
  seq.push(await page.evaluate(() => location.hash));
  const fw = [];
  const backSteps = [];
  for (let k = 0; k < 2; k++) {
    await page.evaluate(() => history.back());
    await sleep(600);
    const st = await page.evaluate(STATE);
    backSteps.push({ hash: st.hash, visibleSections: st.visibleSections, visibleWorkspaces: st.visibleWorkspaces, launcherHidden: st.launcherHidden, textLen: st.mainTextLen });
  }
  await page.evaluate(() => history.forward());
  await sleep(600);
  const fwdSt = await page.evaluate(STATE);
  fw.push({ hash: fwdSt.hash, visibleSections: fwdSt.visibleSections, visibleWorkspaces: fwdSt.visibleWorkspaces, launcherHidden: fwdSt.launcherHidden, textLen: fwdSt.mainTextLen });
  /* cross-page back: index -> settings -> back */
  await page.goto(BASE + '/#home', { waitUntil: 'networkidle2' }); await sleep(300);
  await page.evaluate(() => document.querySelector('#mainnav .navpill[data-v="settings"]').click());
  await sleep(1200);
  const afterSettings = await page.evaluate(STATE);
  await page.goBack({ waitUntil: 'networkidle2' }); await sleep(700);
  const afterBack = await page.evaluate(STATE);
  out.history = { clicked_seq: seq, back_steps: backSteps, forward: fw, settings_landing: afterSettings.path + afterSettings.hash,
    settings_pills: { active: afterSettings.active, aria: afterSettings.aria }, cross_page_back: afterBack.path + afterBack.hash,
    cross_page_back_sections: afterBack.visibleSections, cross_page_back_textLen: afterBack.mainTextLen };
  console.log('history seq:', seq.join(' -> '));
  backSteps.forEach((b, i) => console.log(`  back${i + 1} -> ${b.hash} sections=${JSON.stringify(b.visibleSections)} ws=${JSON.stringify(b.visibleWorkspaces)} launcherHidden=${b.launcherHidden} text=${b.textLen}`));
  fw.forEach(f => console.log(`  forward -> ${f.hash} sections=${JSON.stringify(f.visibleSections)} ws=${JSON.stringify(f.visibleWorkspaces)} text=${f.textLen}`));
  console.log(`  settings: ${out.history.settings_landing} active=${afterSettings.active} aria=${afterSettings.aria} | back -> ${out.history.cross_page_back} sections=${JSON.stringify(afterBack.visibleSections)} text=${afterBack.mainTextLen}`);

  /* ---- 4. keyboard-only: tab order into the rail, Enter on Tools, Enter on a launcher entry ---- */
  await page.goto(BASE + '/#home', { waitUntil: 'networkidle2' }); await sleep(400);
  const tabOrder = [];
  let reachedRail = null, toolFocusBeforeEnter = null;
  for (let i = 0; i < 60; i++) {
    await page.keyboard.press('Tab');
    const f = await page.evaluate(() => { const a = document.activeElement; if (!a) return null;
      const cs = getComputedStyle(a);
      return { tag: a.tagName, id: a.id || '', cls: typeof a.className === 'string' ? a.className.slice(0, 40) : '', v: a.dataset ? a.dataset.v || '' : '',
        text: (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 24), outline: cs.outlineStyle + ' ' + cs.outlineWidth };
    });
    tabOrder.push(f);
    if (f && f.v === 'tools' && reachedRail === null) {
      reachedRail = i + 1;
      await page.keyboard.press('Enter');
      await sleep(600);
      const st = await page.evaluate(STATE);
      if (st.hash !== '#tools') break;
      continue;
    }
    if (f && reachedRail !== null && f.cls && f.cls.indexOf('tool') >= 0 && f.tag === 'A') { toolFocusBeforeEnter = f; break; }
  }
  const preEnter = await page.evaluate(STATE);
  if (toolFocusBeforeEnter) { await page.keyboard.press('Enter'); await sleep(700); }
  const postEnter = await page.evaluate(STATE);
  out.keyboard = { tabs_to_rail: reachedRail, order: tabOrder.map(f => f ? (f.tag + (f.id ? '#' + f.id : '') + (f.cls ? '.' + f.cls.split(' ')[0] : '') + (f.v ? '[' + f.v + ']' : '')) : 'null'),
    rail_focus_outline: (tabOrder.find(f => f && f.v === 'tools') || {}).outline,
    tool_entry_focused: toolFocusBeforeEnter,
    pre_enter: { hash: preEnter.hash, launcherHidden: preEnter.launcherHidden, active: preEnter.active },
    post_enter: { hash: postEnter.hash, visibleWorkspaces: postEnter.visibleWorkspaces, launcherHidden: postEnter.launcherHidden,
      heading: postEnter.heading, textLen: postEnter.mainTextLen, active: postEnter.active, aria: postEnter.aria } };
  console.log(`keyboard: tabs to reach rail Tools = ${reachedRail}; order = ${out.keyboard.order.join(' > ')}`);
  console.log(`keyboard: rail focus outline = ${out.keyboard.rail_focus_outline}`);
  console.log(`keyboard: focused entry = ${JSON.stringify(toolFocusBeforeEnter)}`);
  console.log(`keyboard: pre-Enter ${preEnter.hash} launcherHidden=${preEnter.launcherHidden} | post-Enter ${postEnter.hash} ws=${JSON.stringify(postEnter.visibleWorkspaces)} heading=${postEnter.heading} text=${postEnter.mainTextLen}`);

  /* ---- 5. workspace headings + back links (all slugs) ---- */
  for (const slug of ['deals', 'trends', 'rivens', 'wl', 'ducats', 'craft', 'relicev', 'sets', 'baro', 'meta', 'news', 'player']) {
    await page.goto(BASE + '/#tools/' + slug, { waitUntil: 'networkidle2' });
    await sleep(500);
    const r = await page.evaluate(() => { const w = document.querySelector('#toolsWs .tws:not(.hidden)');
      if (!w) return { missing: true };
      const bar = w.querySelector('.tws-bar');
      const heads = [...w.querySelectorAll('h1,h2,h3,.card-title')].map(h => h.textContent.replace(/\s+/g, ' ').trim().slice(0, 48));
      return { name: bar ? bar.querySelector('.tws-name').textContent : null, back: bar ? bar.querySelector('a.tws-back').getAttribute('href') : null,
        heads, region: w.getAttribute('role'), label: w.getAttribute('aria-label'), firstFocusable: w.querySelector('a,button') ? w.querySelector('a,button').textContent.trim().slice(0, 24) : null,
        aria_live: !!w.getAttribute('aria-live') };
    });
    out.headings[slug] = r;
    console.log(`ws ${slug.padEnd(8)} name=${r.name} back=${r.back} role=${r.region} label=${r.label} h1h2h3=${r.heads.filter(h => /^[A-Z]/.test(h)).length} heads=${JSON.stringify(r.heads.slice(0, 3))}`);
  }
  /* collection section row + mastery tab */
  for (const u of ['/collection.html', '/collection.html#mastery', '/collection.html#relics', '/collection.html#cards']) {
    await page.goto(BASE + u, { waitUntil: 'networkidle2' });
    await sleep(800);
    const st = await page.evaluate(() => ({ active: [...document.querySelectorAll('#mainnav .navpill.active')].map(p => p.dataset.v),
      aria: [...document.querySelectorAll('#mainnav .navpill[aria-current]')].map(p => p.dataset.v),
      pills: [...document.querySelectorAll('#mainnav .navpill')].map(p => ({ t: p.textContent.trim(), h: p.getAttribute('href'), a: p.classList.contains('active'), cur: p.getAttribute('aria-current') })),
      mhVisible: (() => { const m = document.getElementById('view-mastery'); return m ? !m.classList.contains('hidden') : null; })(),
      textLen: document.querySelector('main').innerText.trim().length,
      headings: [...document.querySelectorAll('main h1,main h2')].map(h => h.textContent.trim().slice(0, 40)) }));
    out.subnav[u] = st;
    console.log(`coll ${u.padEnd(26)} active=${st.active} aria=${st.aria} mhVisible=${st.mhVisible} textLen=${st.textLen} subs=${JSON.stringify(st.pills.map(p => p.t + (p.a ? '*' : '') + '(' + p.h + ')'))}`);
  }

  fs.writeFileSync(path.join(__dirname, 'nav.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/nav.json');
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
