/* Audit-1 check 2 (shared shell: themes, first-paint flash, theme escapes, persistence)
 *      + check 6 (console errors / failed requests per nav page).
 *   node design/_audit/qa_shell.js
 * Writes design/_audit/shell.json
 *
 * Probe notes: the flash sampler runs at document-start and samples in requestAnimationFrame
 * (a frame samples the style state it is about to paint), guarding for a not-yet-existing
 * documentElement. Theme colour reads wait for the 0.22s CSS transition, so a mid-transition
 * value is never mistaken for an escape.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PAGES = [
  ['index', '/#home'], ['collection', '/collection.html'], ['cards', '/cards.html'],
  ['settings', '/settings.html'], ['item', '/item.html'],
];
const SAMPLE = [0, 5, 13, 14, 28, 34, 47, 59];   // 3 dark + 5 light, spanning the palette
const sleep = ms => new Promise(r => setTimeout(r, ms));

const PROBE = `(() => {
  window.__probe = { frames: [], paints: null, saved: null };
  try { window.__probe.saved = localStorage.getItem('wfm.theme'); } catch (e) {}
  function step(n) {
    const de = document.documentElement;
    if (!de) { requestAnimationFrame(() => step(n)); return; }
    const cs = getComputedStyle(de);
    window.__probe.frames.push({ n: n, t: Math.round(performance.now()),
      bg: cs.getPropertyValue('--bg').trim(), inline: de.style.getPropertyValue('--bg') || '',
      rs: document.readyState });
    if (n < 40) requestAnimationFrame(() => step(n + 1));
    else setTimeout(() => {
      window.__probe.paints = performance.getEntriesByType('paint').map(p => ({ name: p.name, t: Math.round(p.startTime) }));
      window.__probe.nav = Math.round(performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd || 0);
    }, 200);
  }
  requestAnimationFrame(() => step(0));
})();`;

const ESCAPE_SCAN = `(() => {
  const grid = document.getElementById('themeGrid');
  const i = +(document.documentElement.style.getPropertyValue('--__i') || 0);
  const t = window.WFM_THEMES[i] || [];
  const mode = window.wfmThemeMode(t);
  const esc = { white_bg_on_dark: [], black_bg_on_light: [], white_text_on_light: [],
    dark_text_on_dark: [], transparent_card: 0, transparent_header: 0, transparent_rail: 0 };
  const push = (arr, el) => { const c = el.className && typeof el.className === 'string' ? el.className.split(' ')[0] : '';
    const k = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (c ? '.' + c : '');
    if (arr.indexOf(k) < 0) arr.push(k); };
  document.querySelectorAll('body *').forEach(el => {
    if (grid && grid.contains(el)) return;
    if (el.closest('.theme-item')) return;
    const tag = el.tagName.toLowerCase();
    if (tag === 'img' || tag === 'svg' || tag === 'canvas' || tag === 'i') return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    const cs = getComputedStyle(el), bg = cs.backgroundColor, col = cs.color;
    if (mode === 'dark' && bg === 'rgb(255, 255, 255)') push(esc.white_bg_on_dark, el);
    if (mode === 'light' && bg === 'rgb(0, 0, 0)') push(esc.black_bg_on_light, el);
    if (mode === 'light' && col === 'rgb(255, 255, 255)') push(esc.white_text_on_light, el);
    if (mode === 'dark' && col === 'rgb(0, 0, 0)') push(esc.dark_text_on_dark, el);
  });
  document.querySelectorAll('.card').forEach(c => { if (getComputedStyle(c).backgroundColor === 'rgba(0, 0, 0, 0)') esc.transparent_card++; });
  const h = document.querySelector('body > header'), s = document.querySelector('.side');
  if (h && getComputedStyle(h).backgroundColor === 'rgba(0, 0, 0, 0)') esc.transparent_header = 1;
  if (s && getComputedStyle(s).backgroundColor === 'rgba(0, 0, 0, 0)') esc.transparent_rail = 1;
  return esc;
})();`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  await page.evaluateOnNewDocument(PROBE);          /* once: it applies to every later document */
  const out = { themes_total: null, mode_counts: {}, pages: {}, persistence: {} };
  let errs = [], failed = [], respErr = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 240)); });
  page.on('pageerror', e => errs.push('pageerror: ' + String(e.message || e).slice(0, 240)));
  page.on('requestfailed', r => failed.push({ url: r.url().slice(0, 160), err: (r.failure() || {}).errorText }));
  page.on('response', r => { if (r.status() >= 400) respErr.push({ url: r.url().slice(0, 160), status: r.status() }); });

  for (const [name, url] of PAGES) {
    errs = []; failed = []; respErr = [];
    await page.goto(BASE + url, { waitUntil: 'networkidle2', timeout: 40000 });
    await sleep(1000);
    const probe = await page.evaluate(() => window.__probe);
    const info = await page.evaluate(() => {
      const th = window.WFM_THEMES || [];
      const counts = { dark: 0, light: 0 };
      th.forEach(t => { counts[window.wfmThemeMode(t)]++; });
      return { themes: th.length, counts,
        stylesheets: [...document.styleSheets].map(s => { let n = -1; try { n = s.cssRules.length; } catch (e) {} return (s.href || 'inline').split('/').pop() + ':' + n; }),
        shell: !!window.wfmShell, mountedAt: window.wfmShell && window.wfmShell.mountedAt,
        rail: [...document.querySelectorAll('#mainnav .navpill')].map(p => p.dataset.v),
        active: [...document.querySelectorAll('#mainnav .navpill.active')].map(p => p.dataset.v),
        aria: [...document.querySelectorAll('#mainnav .navpill[aria-current]')].map(p => p.dataset.v),
        headerFirst: document.body.firstElementChild && document.body.firstElementChild.tagName,
        railFirst: (() => { const h = document.querySelector('.shellbody'); return h ? h.firstElementChild.tagName + '.' + h.firstElementChild.className : null; })(),
        themeSaved: (() => { try { return localStorage.getItem('wfm.theme'); } catch (e) { return null; } })(),
        themeName: (() => { const n = document.getElementById('themeName'); return n ? n.textContent : null; })(),
        inlineBg: document.documentElement.style.getPropertyValue('--bg').trim(),
        bodyBg: getComputedStyle(document.body).backgroundColor,
        themeBtnWired: !!window.wfmThemeUI, sfx: !!window.sfx };
    });
    out.themes_total = info.themes; out.mode_counts = info.counts;
    const saved = probe.saved == null ? 0 : +probe.saved;
    const theme = await page.evaluate(i => window.WFM_THEMES[i] && { name: window.WFM_THEMES[i][0], bg: window.WFM_THEMES[i][1], mode: window.wfmThemeMode(window.WFM_THEMES[i]) }, saved);
    const flashFrames = theme ? probe.frames.filter(f => f.bg !== theme.bg) : [];
    const firstInline = (probe.frames.find(f => f.inline) || {}).t || null;
    const cycle = [];
    for (const i of SAMPLE) {
      await page.evaluate(i => { document.documentElement.style.setProperty('--__i', String(i)); window.wfmApplyTheme(i); }, i);
      await sleep(380);                                          /* let the 0.22s transition settle */
      const r = await page.evaluate((i, ESCAPE_SCAN) => {
        const t = window.WFM_THEMES[i], mode = window.wfmThemeMode(t);
        const esc = eval(ESCAPE_SCAN);
        const header = document.querySelector('body > header'), rail = document.querySelector('.side');
        return { i, name: t[0], mode, want_bg: t[1], bodyBg: getComputedStyle(document.body).backgroundColor,
          headerBg: header ? getComputedStyle(header).backgroundColor : null,
          railBg: rail ? getComputedStyle(rail).backgroundColor : null,
          pillActiveBg: (() => { const a = document.querySelector('#mainnav .navpill.active'); return a ? getComputedStyle(a).backgroundColor : null; })(),
          cardBg: (() => { const c = document.querySelector('.card'); return c ? getComputedStyle(c).backgroundColor : null; })(),
          textColor: getComputedStyle(document.body).color, esc };
      }, i, ESCAPE_SCAN);
      cycle.push(r);
    }
    await page.evaluate(() => window.wfmApplyTheme(0));
    out.pages[name] = { url, info, saved_theme: saved, saved_theme_name: theme,
      flash_frames: flashFrames.length, flash_sample: flashFrames.slice(0, 4),
      frames_total: probe.frames.length, first_inline_theme_ms: firstInline, paints: probe.paints, domReady_ms: probe.nav,
      cycle, console_errors: errs.slice(0, 10), failed: failed.slice(0, 10), http_errors: respErr.slice(0, 10) };
    const escW = cycle.reduce((a, c) => a + c.esc.white_bg_on_dark.length, 0);
    const escB = cycle.reduce((a, c) => a + c.esc.black_bg_on_light.length, 0);
    const escT = cycle.reduce((a, c) => a + c.esc.white_text_on_light.length, 0);
    const escD = cycle.reduce((a, c) => a + c.esc.dark_text_on_dark.length, 0);
    console.log(`${name.padEnd(11)} themes=${info.themes} (${info.counts.dark}d/${info.counts.light}l) rail=${info.rail.length} active=${info.active} aria=${info.aria} ` +
      `shell=${info.shell}@${info.mountedAt} headerFirst=${info.headerFirst} railFirst=${info.railFirst} ` +
      `flash=${flashFrames.length}/${probe.frames.length} inlineAt=${firstInline}ms paints=${JSON.stringify(probe.paints)} ` +
      `escW=${escW} escB=${escB} escT=${escT} escD=${escD} errs=${errs.length} failed=${failed.length} http=${respErr.length}`);
    cycle.forEach(c => console.log(`   theme ${String(c.i).padStart(2)} ${c.name.padEnd(20)} ${c.mode} body=${c.bodyBg}(want ${c.want_bg}) ` +
      `hdr=${c.headerBg} rail=${c.railBg} card=${c.cardBg} pill=${c.pillActiveBg} escW=${c.esc.white_bg_on_dark.length}${c.esc.white_bg_on_dark.length ? ' ' + JSON.stringify(c.esc.white_bg_on_dark.slice(0, 5)) : ''}`));
    if (errs.length) console.log('   errs:', errs.slice(0, 6));
    if (failed.length) console.log('   failed:', failed.slice(0, 4));
  }

  /* ---- persistence across pages: light theme 14 + muted sound, set through the real UI ---- */
  await page.goto(BASE + '/#home', { waitUntil: 'networkidle2' });
  const clickTheme = await page.evaluate(() => {
    const btn = document.getElementById('themeBtn');
    if (!btn) return { err: 'no themeBtn' };
    btn.click();
    window.wfmBuildThemeGrid();
    const item = document.querySelector('.theme-item[data-i="14"]');
    if (!item) return { err: 'no .theme-item[data-i=14]' };
    item.click();
    return { panelHidden: document.getElementById('themePanel').classList.contains('hidden'),
      inlineBg: document.documentElement.style.getPropertyValue('--bg').trim(),
      saved: localStorage.getItem('wfm.theme'), name: document.getElementById('themeName').textContent };
  });
  const sound1 = await page.evaluate(() => { document.getElementById('soundBtn').click();
    return { saved: localStorage.getItem('wfm_sound'), pressed: document.getElementById('soundBtn').getAttribute('aria-pressed'), sfx: window.sfx && window.sfx.enabled }; });
  out.persistence.click_theme = clickTheme; out.persistence.sound_after_click = sound1;
  for (const [name, url] of PAGES) {
    await page.goto(BASE + url, { waitUntil: 'networkidle2' });
    await sleep(500);
    out.persistence[name] = await page.evaluate(() => ({
      saved: (() => { try { return localStorage.getItem('wfm.theme'); } catch (e) { return null; } })(),
      inlineBg: document.documentElement.style.getPropertyValue('--bg').trim(),
      bodyBg: getComputedStyle(document.body).backgroundColor,
      name: (() => { const n = document.getElementById('themeName'); return n ? n.textContent : null; })(),
      soundSaved: (() => { try { return localStorage.getItem('wfm_sound'); } catch (e) { return null; } })(),
      soundPressed: (() => { const b = document.getElementById('soundBtn'); return b ? b.getAttribute('aria-pressed') : null; })(),
      soundClass: (() => { const b = document.getElementById('soundBtn'); return b ? b.className : null; })(),
      sfxEnabled: window.sfx ? window.sfx.enabled : 'no-sfx', themeBtnWired: !!window.wfmThemeUI }));
    const p = out.persistence[name];
    console.log(`persist ${name.padEnd(11)} theme=${p.saved} bg=${p.inlineBg} name=${p.name} sound=${p.soundSaved} pressed=${p.soundPressed} sfx=${p.sfxEnabled} wired=${p.themeBtnWired}`);
  }
  await page.goto(BASE + '/#home', { waitUntil: 'networkidle2' });
  await page.evaluate(() => { window.wfmApplyTheme(0); const b = document.getElementById('soundBtn'); if (b.getAttribute('aria-pressed') === 'false') b.click(); });
  out.persistence.restored = await page.evaluate(() => ({ theme: localStorage.getItem('wfm.theme'), sound: localStorage.getItem('wfm_sound') }));
  console.log('restored:', JSON.stringify(out.persistence.restored));
  fs.writeFileSync(path.join(__dirname, 'shell.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/shell.json');
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
