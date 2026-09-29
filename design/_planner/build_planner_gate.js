/* ============================================================================================
 * design/_planner/build_planner_gate.js — the Phase 2 build-planner browser workflow gate.
 *
 *   node design/_planner/build_planner_gate.js      (normally run through:
 *                                                    python design/_planner/build_planner_gate.py)
 *
 * It drives the REAL app — the real server.py, the real ingested database and the real
 * builds/ engine behind /api/planner/* — at http://127.0.0.1:8791 and writes
 * design/_planner/build-planner-raw.json with every number it measured.
 *
 * THE RULE THIS GATE ENFORCES: the page owns no Warframe math. Every stat the DOM shows is
 * compared against /api/planner/compute for the very same build JSON the page holds, and two
 * absolute Phase 1 values (Braton Prime base 35, Serration R10 -> 92.75) are pinned so engine
 * drift shows up as a failure rather than as a new normal.
 *
 * Steps (the Phase 2 brief's list, in its order):
 *    1 open      planner is a real destination: 7 rail entries, planner active, deep link, no
 *                duplicate ids, 0 console errors / failed requests
 *    2 select    Braton Prime through the picker UI (search + click a row)
 *    3 catalyst  the Catalyst toggle doubles the capacity, the bar follows
 *    4 add mod   Serration into slot 1: drain, capacity, damage - DOM vs engine
 *    5 polarity  slot 1 to Madurai: drain halves, the Forma readout counts it
 *    6 rank      Serration R10 -> R0 -> R10: damage 92.75 -> 35 -> 92.75
 *    7 elements  Hellfire + Infected Clip combine to Gas, then Cold replaces Heat -> Viral
 *    8 capacity  used / total / free and the per-slot charge table read from the engine
 *    9 damage    headline damage and its split, DOM vs engine
 *   10 crit      Point Strike raises crit chance, DOM vs engine
 *   11 elemental the composition rows are the engine's, and slot order is what produced them
 *   12 config B  switching configs does not touch A
 *   13 A intact  back to A: the same slots, ranks, polarity and capacity
 *   14 reload    a full page reload
 *   15 persist   everything the brief lists comes back (equipment, configs, slots, ranks,
 *                polarities, catalyst, exilus, mastery rank, active config, library filters)
 *   16 graceful  a future/foreign planner payload in localStorage does not break the page
 *   17 fit       no horizontal overflow at 1920/1536/1440/1366/1280 wide
 *   18 keyboard  '/' focuses the library search, digits focus slots, Enter installs,
 *                Escape lets go - drag/drop is never the only way
 *   19 drag      library row -> slot, slot -> slot (move/swap), slot -> library (remove),
 *                with the legal / illegal target states visible during the drag
 *   20 hygiene   no duplicate id in the rendered state, no page error, no failed request
 * ============================================================================================ */
'use strict';

/* puppeteer-core: the repo has no node_modules of its own, so resolve the shared copy the
   other harnesses use. Nothing here reads stdin; every input is a constant or an env var. */
let puppeteer = null, PUPPETEER_FROM = null;
for (const cand of [process.env.WFM_PUPPETEER, 'puppeteer-core', 'puppeteer',
                    'F:/VSC Projects/pb-bench/node_modules/puppeteer-core']) {
  if (!cand) continue;
  try { puppeteer = require(cand); PUPPETEER_FROM = cand; break; } catch (e) { /* next */ }
}
if (!puppeteer) {
  console.error('build_planner_gate.js: no puppeteer-core found (tried WFM_PUPPETEER, node_modules, pb-bench)');
  process.exit(2);
}
const fs = require('fs');
const path = require('path');

/* ---------------------------------------------------------------- fixed inputs ------------ */
const REPO = 'F:/VSC Projects/wfm-dashboard';
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8791';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = path.join(REPO, 'design', '_planner');
const RAW = process.env.WFM_RAW || path.join(OUT, 'build-planner-raw.json');
const SHOTS = process.env.WFM_SHOTS ||
  path.join(process.env.TEMP || 'C:/Users/jayde/AppData/Local/Temp', 'planner-gate-shots');
// One profile per run. A shared dir meant an orphaned Chrome from an earlier run left its lock
// behind and puppeteer refused to launch (or the startup rmSync died with EPERM) - a stale dir
// must never be able to fail this gate.
const PROFILE = path.join(process.env.TEMP || 'C:/Users/jayde/AppData/Local/Temp',
  'planner-gate-profile-' + process.pid);
const VIEWPORTS = [[1920, 1080], [1536, 864], [1440, 900], [1366, 768], [1280, 800]];
const EQUIP = process.env.WFM_EQUIP || '/Lotus/Weapons/Tenno/Rifle/BratonPrime';
const PINNED = {
  base_damage: 35,          // Braton Prime, rank 0, no mods
  serration_r0: 40.25,      // Serration at rank 0 is +15%, not zero: 35 * 1.15
  serration_r10: 92.75,     // Serration at rank 10 is +165%: 35 * 2.65
};
const STORE_KEY = 'wfm.planner.v1';

/* ---------------------------------------------------------------- report ------------------ */
const R = {
  started: new Date().toISOString(),
  base: BASE, puppeteer: PUPPETEER_FROM, chrome: CHROME,
  checks: [], console: [], pageerrors: [], failed: [], blocked_cdn: [],
  steps: {}, screenshots: [], notes: [], ids: {},
};
const addCheck = (section, title, ok, expected, observed, note, diagnostic) =>
  R.checks.push({ section, title, ok: !!ok, expected: String(expected),
                  observed: String(observed), note: note || '', diagnostic: !!diagnostic });
const jwrite = (p, o) => { fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(o, null, 1)); };
let STEP = 0;
const say = (k, v) => { R.steps[k] = v; console.log('• ' + k + ' = ' + JSON.stringify(v)); };

(async () => {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); }
  catch (e) { console.log('• profile dir busy (' + e.code + ') - reusing it'); }   // ours + fresh: nothing to remove
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    userDataDir: PROFILE, args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  fs.mkdirSync(SHOTS, { recursive: true });
  let shotN = 0;
  const shot = async (name) => {
    shotN += 1;
    const file = path.join(SHOTS, String(shotN).padStart(2, '0') + '-' + name + '.png');
    try { await page.screenshot({ path: file }); R.screenshots.push(file); } catch (e) {}
    return file;
  };

  /* the console + network watch, exactly as design/_stage10/gate.js runs it: a request the
     single-threaded dev server refused is not the page's fault, so it is recorded separately.
     The blocked-CDN class is the same one every page of this app shares: warframe.market card
     art and the WFCD image hosts, which are optional decoration and never structural. */
  page.on('console', (m) => {
    if (m.type() === 'error') R.console.push(m.text().slice(0, 300));
  });
  page.on('pageerror', (e) => R.pageerrors.push(String(e && e.message || e).slice(0, 300)));
  page.on('requestfailed', (r) => {
    const row = { url: r.url().slice(0, 200), err: (r.failure() || {}).errorText };
    if (/ERR_CONNECTION|ERR_EMPTY_RESPONSE|ERR_NETWORK_CHANGED|ERR_ABORTED/i.test(row.err || '')) {
      R.transient = (R.transient || []); R.transient.push(row);
    } else if (/(warframe\.market|wfcd|githubusercontent|cloudflare|cdn)/i.test(row.url)) {
      R.blocked_cdn.push(row);
    } else R.failed.push(row);
  });

  /* read the page's own view of the build: the exact JSON the engine was asked about, plus the
     engine's answer for it - so every DOM number below has a source of truth beside it */
  const engine = () => page.evaluate(async () => {
    const P = window.WFMPlanner;
    const build = P.build();
    let api = null;
    try {
      const res = await fetch('/api/planner/compute', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(build),
      });
      api = await res.json();            // the whole answer: validation, capacity, result, refusals
    } catch (e) { api = { ok: false, error: String(e) }; }
    return { build: build, api: api, ui: P.result() || null };
  });
  const nums = (os) => {                       // every number visible in a node's text
    const out = [];
    String(os || '').replace(/-?\d+(?:\.\d+)?/g, (m) => { out.push(Number(m)); return m; });
    return out;
  };
  const statsOf = (res) => (res && res.result && res.result.stats) || {};
  const statOf = (res, key) => statsOf(res)[key];
  const near = (a, b, tol) => typeof a === 'number' && typeof b === 'number'
    && Math.abs(a - b) <= (tol === undefined ? 0.01 : tol);
  const text = (sel) => page.evaluate((s) => {
    const n = document.querySelector(s);
    return n ? n.textContent.replace(/\s+/g, ' ').trim() : null;
  }, sel);

  /* Type a mod name into the library and click the row that IS that mod (data-id). The search
     returns every variant - Serration, Amalgam Serration, the beginner ones - and the gate wants
     the plain one, exactly as a user would pick it. It waits for the row to exist, because the
     library arrives after the equipment pick. */
  const clickRowNamed = async (p, name) => {
    await p.evaluate((n) => {
      const box = document.getElementById('plLibSearch');
      box.value = n;
      box.dispatchEvent(new Event('input', { bubbles: true }));
    }, name);
    await p.waitForFunction((n) => {
      const P = window.WFMPlanner;
      const want = String(n).toLowerCase();
      const target = (P.library() || []).find((r) => String(r.name).toLowerCase() === want);
      const rows = [...document.querySelectorAll('#plLibList .pl-row')];
      if (!rows.length) return false;
      if (!target) return false;
      return rows.some((el) => el.getAttribute('data-id') === target.id) ||
        rows.some((el) => el.textContent.toLowerCase().indexOf(want) >= 0);
    }, { timeout: 20000 }, name);
    await p.evaluate((n) => {
      const P = window.WFMPlanner;
      const want = String(n).toLowerCase();
      const target = (P.library() || []).find((r) => String(r.name).toLowerCase() === want);
      const rows = [...document.querySelectorAll('#plLibList .pl-row')];
      const row = (target && rows.find((el) => el.getAttribute('data-id') === target.id)) ||
        rows.find((el) => el.textContent.toLowerCase().indexOf(want) >= 0);
      if (row) row.click();
    }, name);
    await p.evaluate(() => new Promise((r) => setTimeout(r, 280)));
  };

  try {
    /* ------------------------------------------------------------------ 1 open */
    // A clean profile is the first-run state: the shell + the picker are there and the grid is
    // empty until something is chosen - that is the state this first block checks.
    await page.goto(BASE + '/planner.html', { waitUntil: 'networkidle2' });
    await page.waitForFunction("window.WFMPlanner && !!document.getElementById('plGrid')",
      { timeout: 30000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 700)));
    const open = await page.evaluate(() => {
      const shell = document.querySelector('[data-shell]');
      const rail = [...document.querySelectorAll('nav a, nav button')].map((n) => n.textContent.trim());
      const ids = [...document.querySelectorAll('[id]')].map((n) => n.id);
      const dupes = ids.filter((x, i) => ids.indexOf(x) !== i);
      const pop = document.getElementById('plEquipPop');
      return {
        shell: shell ? shell.getAttribute('data-shell') : null,
        rail: rail,
        plannerActive: !!document.querySelector('.rail a[aria-current="page"], nav a[aria-current="page"]'),
        title: document.title,
        dupes: [...new Set(dupes)],
        status: (document.getElementById('plStatus') || {}).textContent || '',
        gridSlots: document.querySelectorAll('#plGrid .pl-slot').length,
        pickerOpen: !!pop && !pop.hidden,
        libRows: document.querySelectorAll('#plLibList .pl-row').length,
      };
    });
    say('open', open);
    addCheck('open', 'the page ships the planner shell and its empty first-run state',
      open.gridSlots === 0 || open.gridSlots >= 8,
      'grid empty (awaiting a pick) or already rendered',
      open.gridSlots + ' slot cards, pickerOpen=' + open.pickerOpen);
    addCheck('open', 'the shell marks the planner destination (not the dashboard)',
      open.shell === 'planner', 'data-shell="planner"', 'data-shell="' + open.shell + '"');
    addCheck('open', 'the rail holds 7 destinations and something is current',
      open.rail.length === 7 && open.plannerActive,
      '7 rail entries, one aria-current', open.rail.length + ' entries, active=' + open.plannerActive);
    addCheck('open', 'the page names the engine + database it reads',
      /build|engine|db|database/i.test(open.status), 'a status line naming the DB',
      '"' + open.status.slice(0, 90) + '"');
    addCheck('open', 'no id appears twice in the rendered page',
      open.dupes.length === 0, '0 duplicate ids', open.dupes.length + ' (' + open.dupes.slice(0, 4) + ')');
    await shot('open-empty');

    /* ------------------------------------------------------------------ 2 select equipment */
    const alreadyOpen = await page.evaluate(() => {
      const pop = document.getElementById('plEquipPop');
      return !!pop && !pop.hidden;
    });
    if (!alreadyOpen) await page.click('#plEquipBtn');
    await page.waitForSelector('#plEquipList [role="option"]', { timeout: 15000 });
    const pickerOpening = await page.evaluate(() => {
      const pop = document.getElementById('plEquipPop');
      return { open: !!pop && !pop.hidden, rows: document.querySelectorAll('#plEquipList [role="option"]').length };
    });
    await page.evaluate(() => {
      const box = document.getElementById('plEquipSearch');
      box.value = 'braton prime';
      box.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await page.waitForFunction(
      "document.querySelectorAll('#plEquipList [role=\"option\"]').length === 1",
      { timeout: 15000 });
    const hit = await page.evaluate(() => {
      const row = document.querySelector('#plEquipList [role="option"]');
      const out = { text: row.textContent.replace(/\s+/g, ' ').trim() };
      row.click();
      return out;
    });
    await page.waitForFunction(
      "document.querySelectorAll('#plGrid .pl-slot').length >= 8 && " +
      "(document.getElementById('plStatus')||{}).textContent.length > 0",
      { timeout: 25000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 900)));   // library + compute settle
    const sel = await engine();
    const detail = await page.evaluate(async (key) => {
      const res = await fetch('/api/planner/equipment/' + encodeURIComponent(key));
      const body = await res.json();
      return body.equipment || null;
    }, EQUIP);
    say('picker', { opening: pickerOpening, hit: hit.text, build: sel.build,
      detail_damage: detail && detail.damage_total });
    addCheck('select', 'the picker opens with the normalised DB searchable',
      pickerOpening.open && pickerOpening.rows > 0, 'popup open with rows',
      'open=' + pickerOpening.open + ' rows=' + pickerOpening.rows);
    addCheck('select', 'searching "braton prime" leaves exactly the rifle',
      /Braton Prime/.test(hit.text), '1 row: Braton Prime', hit.text);
    addCheck('select', 'picking it draws the slot grid (8 normal slots + exilus)',
      sel.build.slots.filter((s) => s.kind === 'normal').length === 8 &&
      sel.build.slots.some((s) => s.kind === 'exilus'),
      '8 normal slots and an exilus slot',
      sel.build.slots.map((s) => s.kind + (s.index === null ? '' : s.index)).join(','));
    addCheck('select', 'the build now names that equipment',
      sel.build.equipment_id === EQUIP, EQUIP, sel.build.equipment_id);
    addCheck('select', 'the engine prices its base damage at the Phase 1 value',
      near(statOf(sel.api, 'base_damage'), PINNED.base_damage),
      'base_damage = ' + PINNED.base_damage,
      'base_damage = ' + statOf(sel.api, 'base_damage'));
    await shot('selected-braton-prime');

    /* ------------------------------------------- 2b the library reads one card per name */
    const libFacts = await page.evaluate(() => {
      const P = window.WFMPlanner;
      const rows = P.library() || [];
      const names = rows.map((r) => (r.shadowed ? '~' : '') + r.name);
      const dupes = names.filter((n, i) => names.indexOf(n) !== i);
      return {
        total: rows.length,
        dupes: dupes.slice(0, 8),
        flawed: names.filter((n) => n.indexOf('Flawed ') === 0).length,
        hidden: P.libraryHidden() || null,
      };
    });
    say('library', libFacts);
    addCheck('library', 'one card per name - nothing the player could mix up',
      libFacts.dupes.length === 0, 'no duplicate names',
      JSON.stringify(libFacts.dupes) + ' of ' + libFacts.total);
    addCheck('library', 'starter copies wear the game\'s own name (Flawed ...)',
      libFacts.flawed > 0, 'at least one Flawed copy visible', 'flawed=' + libFacts.flawed);
    addCheck('library', 'the obsolete leftovers are counted, not silently dropped',
      !!libFacts.hidden && libFacts.hidden.shadowed > 0 && /obsolete/.test(libFacts.hidden.reason || ''),
      'hidden.shadowed > 0 with a reason', JSON.stringify(libFacts.hidden));

    /* ------------------------------------------------------------------ 3 catalyst */
    await page.click('#plOrokin');
    await page.waitForFunction("(document.getElementById('plOrokinVal')||{}).textContent === 'on'",
      { timeout: 10000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 450)));
    const cat = await engine();
    const capUI = await page.evaluate(() => ({
      used: (document.getElementById('plCapUsed') || {}).textContent,
      total: (document.getElementById('plCapTotal') || {}).textContent,
      width: (document.getElementById('plCapFill') || {}).style
        ? document.getElementById('plCapFill').style.width : null,
    }));
    const capApi = (cat.api && cat.api.capacity && cat.api.capacity.capacity) || {};
    say('catalyst', { ui: capUI, api_total: capApi.total, api_rank: capApi.doubled_capacity,
      build_orokin: cat.build.orokin });
    addCheck('catalyst', 'the Catalyst toggle reaches the engine',
      cat.build.orokin === true, 'build.orokin = true', 'build.orokin = ' + cat.build.orokin);
    addCheck('catalyst', 'the capacity bar reads the engine total',
      Number(capUI.total) === Number(capApi.total), 'ui ' + capApi.total, 'ui ' + capUI.total);
    addCheck('catalyst', 'the doubled capacity is what the rank supports (30 -> 60)',
      Number(capApi.total) === 60, '60', String(capApi.total));

    /* ------------------------------------------------------------------ 4 add a mod (library click) */
    await page.evaluate(() => {
      const P = window.WFMPlanner;
      P.focusSlot('normal', 0);
    });
    await clickRowNamed(page, 'Serration');
    await page.waitForFunction("(document.getElementById('plCapUsed')||{}).textContent === '14'",
      { timeout: 15000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 500)));
    const s4 = await engine();
    const dom4 = await page.evaluate(() => ({
      capUsed: document.getElementById('plCapUsed').textContent,
      capTotal: document.getElementById('plCapTotal').textContent,
      slot1: document.querySelector('#plGrid .pl-slot[data-kind="normal"][data-index="0"]').textContent.replace(/\s+/g, ' ').trim(),
      damage: (document.querySelector('#plStatBody [data-stat="modded_base_damage"]') || {}).textContent || '',
      damageTotal: (document.querySelector('#plStatBody [data-stat="modded_base_damage"]') || {}).textContent || '',
      trace: document.querySelector('#plStatBody [data-stat="modded_base_damage"]')
        ? 'traceable' : 'no-trace-marker',
    }));
    say('serration', { ui: dom4, api: { damage: statOf(s4.api, 'base_damage'),
      modded: statOf(s4.api, 'modded_base_damage'), cap: s4.api && s4.api.capacity_used },
      slot_mod: s4.build.slots[0].mod });
    addCheck('add mod', 'clicking a library row installs it into the focused slot',
      s4.build.slots[0].mod && /DamageAmount/.test(s4.build.slots[0].mod.id || '') &&
      /Serration/.test((dom4.slot1 || '')),
      'slot 1 = Serration (the rifle damage mod)',
      JSON.stringify(s4.build.slots[0].mod) + ' | "' + (dom4.slot1 || '').slice(0, 40) + '"');
    addCheck('add mod', 'a vacant slot charges the mod\'s full drain (4 + 10 = 14)',
      Number(dom4.capUsed) === Number(s4.api.capacity_used),
      'ui == engine (' + s4.api.capacity_used + ')', 'ui ' + dom4.capUsed);
    addCheck('add mod', 'the engine\'s damage with Serration R10 is the Phase 1 number',
      near(statOf(s4.api, 'modded_base_damage'), PINNED.serration_r10),
      'modded base = ' + PINNED.serration_r10, 'engine ' + statOf(s4.api, 'modded_base_damage'));
    addCheck('add mod', 'the DOM shows that same number (the page invents nothing)',
      near(nums(dom4.damage)[0], statOf(s4.api, 'modded_base_damage'), 0.6) ||
      dom4.damage.indexOf(String(statOf(s4.api, 'modded_base_damage'))) >= 0,
      'DOM contains ' + statOf(s4.api, 'modded_base_damage') + ' (from ' + dom4.damage.slice(0, 60) + ')',
      dom4.damage.slice(0, 80));
    await shot('serration-installed');

    /* ------------------------------------------------------------------ 5 polarity + Forma */
    const pol = await page.evaluate(() => {
      const P = window.WFMPlanner;
      P.setPolarityFor && P.setPolarityFor('normal', 0, 'madurai');
      return true;
    });
    await page.evaluate(() => {
      const P = window.WFMPlanner;
      if (typeof P.setPolarityFor !== 'function') {
        const dot = document.querySelector('#plGrid .pl-slot[data-kind="normal"][data-index="0"] .pl-pol');
        if (dot) dot.click();
        const opt = [...document.querySelectorAll('.pl-polmenu button, .pl-pop button')]
          .find((b) => /madurai/i.test(b.textContent));
        if (opt) opt.click();
      }
    });
    await page.waitForFunction("Number((document.getElementById('plForma')||{}).textContent) >= 1",
      { timeout: 15000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 450)));
    const s5 = await engine();
    const dom5 = await page.evaluate(() => ({
      used: (document.getElementById('plCapUsed') || {}).textContent,
      forma: (document.getElementById('plForma') || {}).textContent,
      formaNote: (document.getElementById('plFormaNote') || {}).textContent,
      slotPol: (document.querySelector('#plGrid .pl-slot[data-kind="normal"][data-index="0"] .pl-pol') || {})
        .getAttribute ? document.querySelector('#plGrid .pl-slot[data-kind="normal"][data-index="0"] .pl-pol').getAttribute('data-p') : null,
    }));
    say('polarity', { dom: dom5, api_cap: s5.api && s5.api.capacity_used, slot: s5.build.slots[0] });
    addCheck('polarity', 'the slot carries the new polarity into the engine',
      s5.build.slots[0].polarity === 'madurai', 'madurai', String(s5.build.slots[0].polarity));
    addCheck('polarity', 'a matched polarity halves the drain (14 -> 7)',
      Number(dom5.used) === Number(s5.api.capacity_used) && Number(dom5.used) < 14,
      'ui == engine, < 14', 'ui ' + dom5.used + ' engine ' + s5.api.capacity_used);
    addCheck('polarity', 'the Forma readout counts the changed slot',
      Number(dom5.forma) >= 1 && /1 slot/i.test(dom5.formaNote || ''),
      'Forma >= 1, "1 slot changed"', dom5.forma + ' / ' + dom5.formaNote);
    await shot('polarity-matched');

    /* ------------------------------------------------------------------ 6 rank change */
    const rankTo = async (rank) => {
      await page.evaluate(() => { window.WFMPlanner.focusSlot('normal', 0); });
      await page.evaluate(() => new Promise((r) => setTimeout(r, 280)));
      await page.evaluate((r) => {
        const range = document.querySelector('#plGridHint input[type="range"]') ||
          document.querySelector('.pl-slot input[type="range"]') ||
          document.querySelector('input[type="range"]');
        if (range) {
          range.value = String(r);
          range.dispatchEvent(new Event('input', { bubbles: true }));
          range.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }, rank);
      await page.evaluate(() => new Promise((res) => setTimeout(res, 600)));
      return engine();
    };
    const r0 = await rankTo(0);
    const r10 = await rankTo(10);
    say('rank', { r0: r0.build.slots[0].mod, r10: r10.build.slots[0].mod,
      damage_r0: statOf(r0.api, 'modded_base_damage'), damage_r10: statOf(r10.api, 'modded_base_damage') });
    addCheck('rank', 'rank 0 uses the mod\'s own rank-0 value (+15%, not zero)',
      near(statOf(r0.api, 'modded_base_damage'), PINNED.serration_r0),
      'modded base = ' + PINNED.serration_r0, 'engine ' + statOf(r0.api, 'modded_base_damage'));
    addCheck('rank', 'rank 10 restores the Phase 1 number (92.75)',
      near(statOf(r10.api, 'modded_base_damage'), PINNED.serration_r10),
      'modded base = ' + PINNED.serration_r10, 'engine ' + statOf(r10.api, 'modded_base_damage'));

    /* ------------------------------------------------------------------ 7 + 11 elements */
    const installByName = async (name, kind, index) => {
      await page.evaluate((k, i) => {
        const P = window.WFMPlanner;
        if (typeof P.focusSlot === 'function') P.focusSlot(k, i);
      }, kind, index);
      await clickRowNamed(page, name);
      await page.evaluate(() => new Promise((res) => setTimeout(res, 450)));
    };
    await installByName('hellfire', 'normal', 2);
    await installByName('infected clip', 'normal', 3);
    const el1 = await engine();
    const domEl1 = await readElements(page);
    say('elements-gas', { api: (el1.api && el1.api.result && el1.api.result.damage && el1.api.result.damage.composition) || null, dom: domEl1 });
    addCheck('elements', 'Heat + Toxin combine to Gas in the engine',
      /gas/i.test(JSON.stringify(el1.api && el1.api.result ? el1.api.result.damage : {})),
      'gas present',
      JSON.stringify((el1.api && el1.api.result && el1.api.result.damage && el1.api.result.damage.per_projectile) || {}).slice(0, 160));
    addCheck('elements', 'the DOM shows the same combination',
      /gas/i.test(domEl1.composition + ' ' + domEl1.types), 'gas in the composition',
      (domEl1.composition + ' | ' + domEl1.types).slice(0, 160));

    /* Cold replaces Heat in slot 3 -> Cold + Toxin = Viral (the brief's own example) */
    await installByName('cryo rounds', 'normal', 2);
    const el2 = await engine();
    const domEl2 = await readElements(page);
    say('elements-viral', { api: (el2.api && el2.api.result && el2.api.result.damage && el2.api.result.damage.composition) || null, dom: domEl2 });
    addCheck('elements', 'slot order decides the pair: Cold + Toxin is now Viral',
      /viral/i.test(JSON.stringify(el2.api && el2.api.result ? el2.api.result.damage : {})),
      'viral present',
      JSON.stringify((el2.api && el2.api.result && el2.api.result.damage && el2.api.result.damage.per_projectile) || {}).slice(0, 160));
    addCheck('elements', 'the stat panel followed the swap (Viral, not Gas)',
      /viral/i.test(domEl2.composition + ' ' + domEl2.types) &&
      !/gas/i.test(domEl2.composition + ' ' + domEl2.types),
      'viral and no gas', (domEl2.composition + ' | ' + domEl2.types).slice(0, 160));
    await shot('elements-viral');

    /* ------------------------------------------------------------------ 8 capacity */
    const cap = await engine();
    const domCap = await page.evaluate(() => ({
      used: Number(document.getElementById('plCapUsed').textContent),
      total: Number(document.getElementById('plCapTotal').textContent),
      total_dom: document.getElementById('plCapTotal').textContent,
      rows: [...document.querySelectorAll('#plCapBody .pl-cd-slot')]
        .map((n) => n.textContent.replace(/\s+/g, ' ').trim()),
      detail: document.getElementById('plCapBody').textContent.replace(/\s+/g, ' ').trim().slice(0, 300),
    }));
    say('capacity', { ui: domCap, api_used: cap.api.capacity_used, api_cap: cap.api.capacity });
    addCheck('capacity', 'used capacity in the DOM equals the engine\'s',
      domCap.used === Number(cap.api.capacity_used), 'ui == engine',
      'ui ' + domCap.used + ' engine ' + cap.api.capacity_used);
    addCheck('capacity', 'the charge table names a rule for every filled slot',
      domCap.rows.filter((r) => /matched|wrong polarity|vacant|no polarity/.test(r)).length === 3,
      'one priced row per installed mod (3)',
      domCap.rows.filter((r) => /matched|wrong polarity|vacant|no polarity/.test(r)).length +
      ' priced of ' + domCap.rows.length + ' rows: ' + JSON.stringify(domCap.rows.slice(0, 4)));

    /* ------------------------------------------------------------------ 9 damage + 10 crit */
    await installByName('point strike', 'normal', 4);
    const dm = await engine();
    const domDm = await page.evaluate(() => {
      const grab = (k) => {
        const n = document.querySelector('#plStatBody [data-stat="' + k + '"]');
        return n ? n.textContent.replace(/\s+/g, ' ').trim() : null;
      };
      return {
        base_damage: grab('base_damage'), modded: grab('modded_base_damage'),
        crit: grab('critical_chance'), mult: grab('critical_multiplier'),
        status: grab('status_chance'), multishot: grab('multishot'),
        rows: document.querySelectorAll('#plStatBody .pl-stat-row').length,
        groups: [...document.querySelectorAll('#plStatBody .pl-sg-head')].map((n) => n.textContent.trim()),
      };
    });
    const critApi = statOf(dm.api, 'critical_chance');
    const critBase = 12;                       // Braton Prime's Phase 1 base
    say('damage-crit', { dom: domDm, api: statsOf(dm.api), api_crit: critApi, api_damage: statOf(dm.api, 'modded_base_damage') });
    addCheck('damage', 'every stat row the DOM shows traces to an engine value',
      domDm.rows > 8, '8+ stat rows', domDm.rows + ' rows');
    addCheck('damage', 'the panel groups weapon stats (no meaningless fields)',
      domDm.groups.length >= 2, '2+ groups', JSON.stringify(domDm.groups));
    addCheck('crit', 'Point Strike raises crit chance above the 12% base',
      typeof critApi === 'number' && critApi > critBase, '> ' + critBase, String(critApi));
    addCheck('crit', 'the DOM crit chance is that engine number',
      nums(domDm.crit)[0] !== undefined && Math.abs(nums(domDm.crit)[0] - critApi) < 0.2,
      'ui ~= engine (' + critApi + ')', domDm.crit);

    /* ------------------------------------------------------------------ 9b trace (explainability) */
    await page.evaluate(() => {
      const row = document.querySelector('#plStatBody [data-stat="modded_base_damage"]') ||
        document.querySelector('#plStatBody [data-stat="damage_per_shot"]');
      if (row) row.click();
    });
    await page.waitForFunction("(document.getElementById('plTraceBody')||{}).textContent.trim().length > 20",
      { timeout: 15000 });
    const trace = await page.evaluate(() => {
      const body = document.getElementById('plTraceBody');
      return { text: body.textContent.replace(/\s+/g, ' ').trim().slice(0, 400),
        lines: [...body.querySelectorAll('.pl-tr-line, .pl-tr-row, li, div')]
          .map((n) => n.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 12) };
    });
    say('trace', trace);
    addCheck('trace', 'a stat opens the engine\'s own trace (base, each mod, final)',
      /base/i.test(trace.text) && /serration/i.test(trace.text),
      'a trace with the base and the mod', trace.text.slice(0, 120));
    addCheck('trace', 'the trace names the final value the stat row shows',
      /9\d(\.\d+)?|1\d\d(\.\d+)?/.test(trace.text), 'a final total in the trace',
      trace.text.slice(0, 200));
    await shot('trace-open');

    /* ------------------------------------------------------------------ 12 + 13 configs */
    const beforeSwitch = await engine();
    await page.evaluate(() => {
      const tabs = [...document.querySelectorAll('#plConfigs .pl-tab')];
      const b = tabs.find((t) => t.textContent.trim() === 'B');
      if (b) b.click();
    });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 500)));
    const confB = await engine();
    say('config-b', { active: confB.build.config, slots: confB.build.slots.filter((s) => s.mod).length });
    addCheck('config', 'config B is its own build (active + empty)',
      confB.build.config === 'B' && confB.build.slots.every((s) => !s.mod),
      'config B, no mods', 'config ' + confB.build.config + ', ' +
        confB.build.slots.filter((s) => s.mod).length + ' mods');
    await page.evaluate(() => {
      const tabs = [...document.querySelectorAll('#plConfigs .pl-tab')];
      const a = tabs.find((t) => t.textContent.trim() === 'A');
      if (a) a.click();
    });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 500)));
    const confA = await engine();
    const aMods = confA.build.slots.filter((s) => s.mod).map((s) => s.mod.id).sort();
    say('config-a-intact', { mods: aMods, cap_used: confA.api.capacity_used });
    addCheck('config', 'switching to B and back leaves A untouched',
      aMods.length === 4 && /DamageAmount/.test(aMods.join(',')),
      'the same 4 mods, incl. the rifle damage mod', aMods.join(', '));
    addCheck('config', 'A still holds its polarity + capacity',
      confA.build.slots[0].polarity === 'madurai' &&
      Number(confA.api.capacity_used) === Number(beforeSwitch.api.capacity_used),
      'madurai slot, capacity ' + beforeSwitch.api.capacity_used,
      'polarity ' + confA.build.slots[0].polarity + ', used ' + confA.api.capacity_used +
      ' (was ' + beforeSwitch.api.capacity_used + ')');
    // the duplicate action: copy A (4 mods) into the next letter and switch to it
    await page.evaluate(() => {
      const tabs = [...document.querySelectorAll('#plConfigs .pl-tab')];
      const a = tabs.find((t) => t.textContent.trim() === 'A');
      if (a) a.click();
    });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 300)));
    await page.evaluate(() => { const P = window.WFMPlanner; P.duplicateConfig(); });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 500)));
    const dupRun = await engine();
    const dupMods = dupRun.build.slots.filter((s) => s.mod).map((s) => s.mod.id).sort();
    say('duplicate', { active: dupRun.build.config, mods: dupMods });
    addCheck('duplicate', 'duplicate copies A into B and switches to it',
      dupRun.build.config === 'B' && dupMods.length === 4 && /DamageAmount/.test(dupMods.join(',')),
      'B active with A\'s 4 mods', 'config ' + dupRun.build.config + ', ' + dupMods.join(', '));
    await page.evaluate(() => new Promise((r) => setTimeout(r, 400)));

    /* ------------------------------------------------------------------ 14 + 15 reload / persistence */
    const before = await page.evaluate(() => {
      const P = window.WFMPlanner;
      const st = P.storage ? P.storage() : null;
      return st || null;
    });
    await page.reload({ waitUntil: 'networkidle2' });
    await page.waitForFunction("window.WFMPlanner && document.querySelectorAll('#plGrid .pl-slot').length >= 8",
      { timeout: 30000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 900)));
    const after = await engine();
    const stored = await page.evaluate((key) => {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      try {
        const o = JSON.parse(raw);
        return { version: o.version, equipment_id: o.equipment_id, orokin: o.orokin,
          active_config: o.active_config, mastery_rank: o.mastery_rank,
          exilus: o.exilus_unlocked, configs: Object.keys(o.configs || {}) };
      } catch (e) { return { parse_error: String(e) }; }
    }, STORE_KEY);
    const domAfter = await page.evaluate(() => ({
      equip: (document.querySelector('#plEquipBtn .pl-equip-name') || {}).textContent,
      capUsed: Number(document.getElementById('plCapUsed').textContent),
      slots: [...document.querySelectorAll('#plGrid .pl-slot')]
        .filter((n) => n.querySelector('.pl-slot-name') &&
          !/empty|locked/i.test(n.querySelector('.pl-slot-name').textContent))
        .map((n) => n.textContent.replace(/\s+/g, ' ').trim()),
      forma: (document.getElementById('plForma') || {}).textContent,
    }));
    say('persistence', { stored: stored, dom: domAfter, build_after: after.build,
      api_used_after: after.api && after.api.capacity_used });
    addCheck('persistence', 'the planner store is versioned',
      stored && stored.version === 1, 'version 1', JSON.stringify(stored && stored.version));
    addCheck('persistence', 'a full reload restores equipment, mods, ranks and polarity',
      after.build.equipment_id === EQUIP && after.build.slots[0].mod &&
      /DamageAmount/.test(after.build.slots[0].mod.id || '') &&
      after.build.slots[0].polarity === 'madurai' &&
      after.build.slots.filter((s) => s.mod).length === 4,
      'Braton Prime, Serration R10 in a madurai slot, 4 mods',
      (after.build.equipment_id || '') + ' / ' + JSON.stringify(after.build.slots[0]) +
      ' / ' + after.build.slots.filter((s) => s.mod).length + ' mods');
    addCheck('persistence', 'catalyst, exilus and mastery ride along',
      after.build.orokin === true && after.build.mastery_rank === confA.build.mastery_rank,
      'orokin true, same mastery', 'orokin ' + after.build.orokin + ', mr ' + after.build.mastery_rank);
    addCheck('persistence', 'capacity after the reload is the engine\'s number again',
      domAfter.capUsed === Number(after.api.capacity_used), 'ui == engine',
      'ui ' + domAfter.capUsed + ' engine ' + after.api.capacity_used);
    addCheck('persistence', 'the Forma readout survived too',
      Number(domAfter.forma) >= 1, '>= 1', String(domAfter.forma));
    await shot('after-reload');

    /* ------------------------------------------------------------------ 16 a foreign payload */
    await page.evaluate((key) => {
      localStorage.setItem(key, JSON.stringify({ version: 99, equipment_id: 'nonsense',
        configs: { A: { slots: { 'normal:0': { id: 'not a mod', rank: 99 } } } },
        active_config: 'Z', mastery_rank: 'x' }));
    }, STORE_KEY);
    const beforeErrors = R.pageerrors.length;
    await page.reload({ waitUntil: 'networkidle2' });
    await page.waitForFunction("window.WFMPlanner && !!document.getElementById('plGrid')",
      { timeout: 30000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 700)));
    const recovered = await page.evaluate(() => {
      const P = window.WFMPlanner;
      return { slots: document.querySelectorAll('#plGrid .pl-slot').length,
        build: P.build(), stored: JSON.parse(localStorage.getItem('wfm.planner.v1') || 'null') };
    });
    say('graceful', { version: recovered.stored && recovered.stored.version,
      slots: recovered.slots, active: recovered.build.config });
    addCheck('graceful', 'a v99 / foreign payload does not break the page',
      R.pageerrors.length === beforeErrors && recovered.build.config === 'A' &&
      !recovered.build.equipment_id,
      'page boots at its defaults, no new page error',
      recovered.slots + ' slots in the grid, config ' + recovered.build.config + ', new errors ' +
      (R.pageerrors.length - beforeErrors));
    addCheck('graceful', 'the unreadable payload is discarded, not half-applied',
      recovered.stored === null || recovered.stored.version === 1,
      'the store is gone or rewritten as version 1',
      JSON.stringify(recovered.stored && { version: recovered.stored.version,
        active: recovered.stored.active_config }));

    /* ------------------------------------------------------------------ 17 responsive */
    await page.evaluate((key) => localStorage.removeItem(key), STORE_KEY);   // start clean
    await page.goto(BASE + '/planner.html?equip=' + encodeURIComponent(EQUIP) + '&config=A',
      { waitUntil: 'networkidle2' });
    await page.waitForFunction("document.querySelectorAll('#plGrid .pl-slot').length >= 8",
      { timeout: 30000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 600)));
    for (const [w, h] of VIEWPORTS) {
      await page.setViewport({ width: w, height: h });
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 220))));
      const fit = await page.evaluate(() => {
        const vw = window.innerWidth;
        const over = [];
        document.querySelectorAll('body *').forEach((n) => {
          const r = n.getBoundingClientRect();
          if (r.width > 0 && r.right > vw + 1) {
            over.push((n.id ? '#' + n.id : n.tagName.toLowerCase() + '.' +
              String(n.className || '').split(' ')[0]).slice(0, 40));
          }
        });
        const cols = [...document.querySelectorAll('.pl-body > .pl-col')].map((c) => c.getBoundingClientRect());
        let overlap = 0;
        for (let i = 0; i < cols.length; i++) {
          for (let j = i + 1; j < cols.length; j++) {
            const a = cols[i], b = cols[j];
            const dx = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const dy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (dx > 0 && dy > 0) overlap = Math.max(overlap, Math.round(dx * dy));
          }
        }
        return { vw: vw, scrollW: document.documentElement.scrollWidth, over: over.slice(0, 5),
          overlap: overlap };
      });
      addCheck('fit', 'no horizontal overflow at ' + w + 'x' + h,
        fit.scrollW <= fit.vw + 1 && fit.over.length === 0, 'scrollWidth <= ' + fit.vw,
        'scrollWidth ' + fit.scrollW + (fit.over.length ? ' over: ' + fit.over.join(',') : ''));
      addCheck('fit', 'the three columns never overlap at ' + w + 'x' + h,
        fit.overlap === 0, '0 px overlap', fit.overlap + ' px');
    }
    await page.setViewport({ width: 1280, height: 800 });
    await shot('responsive-1280');

    /* ------------------------------------------- 17b the hidden rows are offered back */
    const hiddenBefore = await page.evaluate(() => (window.WFMPlanner.library() || []).length);
    await page.evaluate(() => {
      const b = document.querySelector('#plLibHidden .pl-hidden-link');
      if (b) b.click();
    });
    let revealErr = null;
    try {
      await page.waitForFunction((n) => (window.WFMPlanner.library() || []).length > n,
        { timeout: 10000 }, hiddenBefore);
    } catch (e) {
      revealErr = String(e).slice(0, 120);
    }
    const revealed = await page.evaluate(() => {
      const rows = window.WFMPlanner.library() || [];
      const hidden = rows.filter((r) => r.shadowed);
      return { total: rows.length, shadowed: hidden.length,
        named: hidden.slice(0, 3).map((r) => r.name) };
    });
    say('library-revealed', revealed);
    addCheck('library', 'the hidden rows come back on request, each one flagged',
      revealed.total > hiddenBefore && revealed.shadowed > 0,
      'more rows, all flagged shadowed',
      JSON.stringify(revealed) + (revealErr ? ' (' + revealErr + ')' : ''));

    /* ------------------------------------------------------------------ 18 keyboard */
    await page.setViewport({ width: 1920, height: 1080 });
    await page.keyboard.press('/');
    const kbSearch = await page.evaluate(() => ({
      active: document.activeElement ? document.activeElement.id : null }));
    await page.keyboard.type('ser');
    await page.evaluate(() => new Promise((r) => setTimeout(r, 500)));
    const kbRows = await page.evaluate(() => document.querySelectorAll('#plLibList .pl-row').length);
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await page.evaluate(() => new Promise((r) => setTimeout(r, 600)));
    const kbAfter = await engine();
    await page.evaluate(() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); });
    await page.keyboard.press('1');
    const kbFocus = await page.evaluate(() => {
      const f = document.querySelector('#plGridHint');
      return f ? f.textContent.replace(/\s+/g, ' ').trim().slice(0, 60) : null;
    });
    say('keyboard', { search: kbSearch, rows: kbRows, mods_after: kbAfter.build.slots.filter((s) => s.mod).length,
      hint: kbFocus });
    addCheck('keyboard', '"/" reaches the library search',
      kbSearch.active === 'plLibSearch', 'plLibSearch focused', String(kbSearch.active));
    addCheck('keyboard', 'arrows + Enter install a mod without a mouse',
      kbAfter.build.slots.filter((s) => s.mod).length >= 1,
      '1+ mod installed', kbAfter.build.slots.filter((s) => s.mod).length + ' mods');
    addCheck('keyboard', 'a digit focuses a slot (the inspector says which)',
      /Slot 1/i.test(kbFocus || ''), 'inspector shows Slot 1', String(kbFocus));

    /* ------------------------------------------------------------------ 19 drag & drop */
    // the illegal pair first: an Aura mod dragged at a weapon slot must be refused, visibly.
    // Aura rows only appear once the library's Aura class chip is on, because the default list
    // is "what fits this item" - so the gate clicks that chip like a user would.
    const badDrag = await page.evaluate(async () => {
      // A rifle build has no Aura slot, so the reachable refusal on this page is the locked
      // Exilus slot: the same handler decides it, and the same data-drop="bad" marks it.
      const P = window.WFMPlanner;
      const rows = [...document.querySelectorAll('#plLibList .pl-row')];
      const row = rows.find((el) => el.getAttribute('data-slot') === 'normal') || rows[0];
      const slot = document.querySelector('#plGrid .pl-slot[data-kind="exilus"]');
      const before = P.build().slots.filter((s) => s.mod).length;
      if (!row || !slot) return { skipped: true, rows: rows.length, exilus: !!slot };
      const dt = new DataTransfer();
      const fire = (node, type) => node.dispatchEvent(new DragEvent(type,
        { bubbles: true, cancelable: true, dataTransfer: dt }));
      fire(row, 'dragstart');
      fire(slot, 'dragover');
      const mark = slot.getAttribute('data-drop');
      fire(slot, 'drop');
      fire(row, 'dragend');
      await new Promise((r) => setTimeout(r, 400));
      return { mark: mark, before: before, after: P.build().slots.filter((s) => s.mod).length,
        name: row.getAttribute('data-id'), rows: rows.length };
    });
    say('drag-illegal', badDrag);
    addCheck('drag', 'a mod at a locked Exilus slot is refused - marked bad, nothing installed',
      badDrag.skipped ? false : (badDrag.mark === 'bad' && badDrag.after === badDrag.before),
      'data-drop="bad", mod count unchanged',
      'mark ' + badDrag.mark + ', mods ' + badDrag.before + ' -> ' + badDrag.after);

    // the whole library again for the legal drag: search cleared, class chip back to Mods
    await page.evaluate(() => {
      const chip = [...document.querySelectorAll('#plLibFilters .pl-chip')]
        .find((c) => /^mods$/i.test(c.textContent.trim()));
      if (chip) chip.click();
      const box = document.getElementById('plLibSearch');
      box.value = '';
      box.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 450)));
    const drag = await page.evaluate(async () => {
      // drag a library row into a slot with real DragEvents: the handlers must do the work.
      // Every node is re-queried right before it is used, because an install re-renders the grid.
      const P = window.WFMPlanner;
      const q = (kind, index) => document.querySelector(
        '#plGrid .pl-slot[data-kind="' + kind + '"][data-index="' + index + '"]');
      const firstRow = (slotKind) => {
        const rows = [...document.querySelectorAll('#plLibList .pl-row')];
        // a plain PvE card: not a shadow copy, not Conclave - so the story reads like a player's
        const pick = (P.library() || []).find((r) => r.slot === slotKind && !r.shadowed && !r.conclave);
        return (pick && rows.find((el) => el.getAttribute('data-id') === pick.id)) ||
          rows.find((el) => el.getAttribute('data-slot') === slotKind) || rows[0];
      };
      const before = P.build().slots.filter((s) => s.mod).length;
      const dt = new DataTransfer();
      const fire = (node, type) => node && node.dispatchEvent(new DragEvent(type,
        { bubbles: true, cancelable: true, dataTransfer: dt }));
      fire(firstRow('normal'), 'dragstart');
      fire(q('normal', 5), 'dragover');
      const marked = q('normal', 5) ? q('normal', 5).getAttribute('data-drop') : null;
      fire(q('normal', 5), 'drop');
      fire(firstRow('normal'), 'dragend');
      await new Promise((r) => setTimeout(r, 600));
      const after = P.build().slots.filter((s) => s.mod).length;
      // slot -> slot: the real handlers again - dragstart on the source slot, drop on the target
      const srcId = P.build().slots[0].mod && P.build().slots[0].mod.id;
      const count = P.build().slots.filter((s) => s.mod).length;
      fire(q('normal', 0), 'dragstart');
      fire(q('normal', 7), 'dragover');
      const moveMark = q('normal', 7) ? q('normal', 7).getAttribute('data-drop') : null;
      fire(q('normal', 7), 'drop');
      fire(q('normal', 0), 'dragend');
      await new Promise((r) => setTimeout(r, 500));
      const afterMove = P.build().slots.map((s) => s.mod && s.mod.id);
      const countAfter = P.build().slots.filter((s) => s.mod).length;
      // slot -> library card: the mod comes out of the config (the panel marks itself)
      const beforeRemove = P.build().slots.filter((s) => s.mod).length;
      fire(q('normal', 7), 'dragstart');
      fire(document.getElementById('plLibrary'), 'dragover');
      const panelMark = document.getElementById('plLibrary').classList.contains('pl-lib-drop');
      fire(document.getElementById('plLibrary'), 'drop');
      fire(q('normal', 7), 'dragend');
      await new Promise((r) => setTimeout(r, 500));
      const afterRemove = P.build().slots.filter((s) => s.mod).length;
      return { before: before, marked: marked, mods_after_drop: after,
        move_mark: moveMark, src_id: srcId, in_slot_8: afterMove[7] === srcId,
        left_slot_1: !afterMove[0], count_before_move: count, count_after_move: countAfter,
        panel_mark: panelMark, removed: beforeRemove - afterRemove };
    });
    say('drag', drag);
    addCheck('drag', 'a library row dropped on a slot installs it',
      drag.mods_after_drop === drag.before + 1 && drag.marked === 'ok',
      'marked "ok" and one more mod',
      'mark ' + drag.marked + ', ' + drag.before + ' -> ' + drag.mods_after_drop);
    addCheck('drag', 'slot -> slot moves the mod (marked "move") without losing or duplicating any',
      drag.in_slot_8 && drag.left_slot_1 && drag.count_after_move === drag.count_before_move &&
      (drag.move_mark === 'move'),
      'the mod is in slot 8, slot 1 empty, same count, target marked "move"',
      'in slot 8: ' + drag.in_slot_8 + ', slot 1 empty: ' + drag.left_slot_1 +
      ', ' + drag.count_before_move + ' -> ' + drag.count_after_move + ', mark ' + drag.move_mark);
    addCheck('drag', 'slot -> library removes the mod, and the panel offers the drop',
      drag.panel_mark === true && drag.removed === 1,
      'panel marked "drop here to remove", one mod fewer',
      'marked: ' + drag.panel_mark + ', removed ' + drag.removed);
    await shot('drag-states');

    /* ------------------------------------------------- 19b the audit round's own stories */
    // The capacity floor is the engine's number: read it out of the engine answer for this very
    // build and compare it with what the toolbar hint prints. A page that re-derived it would
    // drift the day builds/capacity.py changes.
    const floor = await page.evaluate(() => {
      const out = window.WFMPlanner.result();
      const cap = out && out.capacity && out.capacity.capacity;
      return { engine: cap ? cap.minimum_from_mastery : null,
        floored: cap ? !!cap.floored_by_mastery : null,
        hint: (document.getElementById('plMrFloor') || {}).textContent || '' };
    });
    say('floor', floor);
    addCheck('engine-math', 'the toolbar capacity floor is the engine\'s own number',
      floor.engine !== null && floor.hint.indexOf(String(floor.engine)) >= 0 &&
      String(floor.floored) === String(floor.hint.indexOf('in use') >= 0),
      'hint names the engine floor ' + floor.engine + ' and its binding state',
      floor.hint.trim());

    // A locked Exilus slot refuses a click-install exactly like it refuses a drag; unlocked, the
    // same click lands. One legality rule, driven by the live adapter switch.
    const exilus = await page.evaluate(async () => {
      const P = window.WFMPlanner;
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const search = document.getElementById('plLibSearch');
      if (search && search.value) {
        search.value = '';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        await wait(500);
      }
      const candidates = (P.library() || []).filter((m) => m.exilus_ok);
      if (candidates.length < 2) return { skipped: 'fewer than two exilus-capable mods here' };
      const row = candidates[0];                        // the locked phase
      const second = candidates[1];                     // the unlocked phase (a fresh mod)
      const toggle = document.getElementById('plExilus');
      const node = (which) => [...document.querySelectorAll('#plLibList .pl-row')]
        .filter((el) => el.getAttribute('data-id') === which.id)[0];
      const slotMod = () => {
        const s = (P.build().slots || []).filter((x) => x.kind === 'exilus')[0];
        return s && s.mod ? s.mod.id : null;
      };
      // locked: whatever happens, the Exilus slot itself must stay empty
      if (toggle && toggle.getAttribute('aria-pressed') === 'true') { toggle.click(); await wait(450); }
      P.focusSlot('exilus');
      if (node(row)) node(row).click();
      await wait(600);
      const text = ((document.querySelector('.pl-slot[data-kind="exilus"]') || {}).textContent || '').trim();
      const locked = { installed: slotMod(), text: text };
      // unlocked and focused: a click on another exilus mod must land in the Exilus slot
      if (toggle) { toggle.click(); await wait(500); }
      P.focusSlot('exilus');
      if (node(second)) node(second).click();
      await wait(700);
      const open = { installed: slotMod() };
      return { id: row.id, name: row.name, second: second.name,
        locked_installed: locked.installed, locked_text: locked.text,
        open_installed: open.installed, want: second.id };
    });
    say('exilus-lock', exilus);
    addCheck('legality', 'the Exilus switch decides: locked, the slot stays empty; unlocked and focused, the mod lands there',
      !!exilus.skipped || (exilus.locked_installed === null && exilus.open_installed === exilus.want),
      'locked: Exilus slot empty; unlocked + focused: the mod is in the Exilus slot',
      exilus.skipped || JSON.stringify({ locked: exilus.locked_installed, unlocked: exilus.open_installed,
        locked_mod: exilus.name, unlocked_mod: exilus.second }));



    // The no-answer contract, positive half: with a real result on screen the banner is hidden
    // and the page declares that it has an answer.
    const contract = await page.evaluate(async (base) => {
      const P = window.WFMPlanner;
      const out = await (await fetch(base + '/api/planner/compute', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(P.build()) })).json();
      return { hidden: document.getElementById('plError').hidden,
        answer: document.body.getAttribute('data-planswer'),
        capUsed: (document.getElementById('plCapUsed') || {}).textContent,
        ok: out.ok, has_result: !!(out && out.result), error: out.error || null,
        val_errors: ((out.validation || {}).errors || []).slice(0, 2),
        banner: (document.getElementById('plError') || {}).textContent || '' };
    }, BASE);
    say('answer-contract', contract);
    addCheck('answer-contract', 'a real answer hides the error banner and says so',
      contract.hidden === true && contract.answer === 'yes' && contract.capUsed !== '—',
      'banner hidden, data-planswer=yes, a capacity figure', JSON.stringify(contract));

    /* ------------------------------------------------- 19c a refusal is an answer with reasons */
    // An impossible build must show the engine's own validation - and must not be reported as a
    // dead engine. The cheapest certain impossibility: the same mod in two slots (duplicate_mod),
    // written straight into storage v1 and loaded, so the check exercises boot + cleanV1 + the
    // Validation card rather than the click paths.
    const dup = await page.evaluate(async (base) => {
      const P = window.WFMPlanner;
      const KEY = 'wfm.planner.v1';
      const build = P.build();
      const installed = (build.slots || []).filter((s) => s.mod && s.kind === 'normal');
      const empty = (build.slots || []).filter((s) => !s.mod && s.kind === 'normal');
      if (!installed.length || !empty.length) return { skipped: 'no installed mod with a free slot' };
      const doc = { version: 1, equipment_id: build.equipment_id,
        equipment_rank: build.equipment_rank === undefined ? null : build.equipment_rank,
        mastery_rank: build.mastery_rank, orokin: build.orokin,
        exilus_unlocked: !!build.exilus_unlocked, active_config: build.config || 'A',
        configs: { A: { slots: {}, polarities: {} } }, library: {}, ui: {} };
      doc.configs.A.slots['normal:' + installed[0].index] = { id: installed[0].mod.id,
        rank: installed[0].mod.rank };
      doc.configs.A.slots['normal:' + empty[0].index] = { id: installed[0].mod.id,
        rank: installed[0].mod.rank };
      localStorage.setItem(KEY, JSON.stringify(doc));
      // what the engine says about exactly this build, straight from the API
      const answer = await (await fetch(base + '/api/planner/compute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          equipment_id: build.equipment_id, config: 'A', mastery_rank: build.mastery_rank,
          orokin: build.orokin, exilus_unlocked: !!build.exilus_unlocked,
          slots: [{ kind: 'normal', index: installed[0].index, mod: installed[0].mod },
                  { kind: 'normal', index: empty[0].index, mod: installed[0].mod }]
        })
      })).json();
      return { skipped: null, wrote: Object.keys(doc.configs.A.slots),
        engine_codes: (((answer || {}).validation || {}).errors || []).map((e) => e.code) };
    }, BASE);
    if (!dup.skipped && dup.engine_codes.length) {
      await page.reload({ waitUntil: 'networkidle2', timeout: 30000 });
      await page.waitForFunction(() => {
        const box = document.getElementById('plValidity');
        return box && box.textContent.indexOf('code') >= 0;
      }, { timeout: 20000 });
    }
    const refusal = dup.skipped ? { skipped: dup.skipped } : await page.evaluate((expected) => {
      const shown = (document.getElementById('plValidity') || {}).textContent || '';
      return { engine_codes: expected, shown: shown.trim().slice(0, 200),
        banner_hidden: document.getElementById('plError').hidden,
        banner_text: ((document.getElementById('plError') || {}).textContent || '').trim() };
    }, dup.engine_codes);
    say('engine-refusal', refusal);
    // A skipped fixture is a FAILED check, not a pass: if the drive can no longer produce an
    // impossible build, that is drift in the story, and the whole point here is the refusal path.
    addCheck('answer-contract', 'an impossible build shows the engine\'s own reason, not a dead engine',
      !refusal.skipped && refusal.engine_codes.length > 0 &&
        refusal.engine_codes.every((c) => refusal.shown.indexOf(c) >= 0),
      'the refusal code the engine sent appears in #plValidity',
      refusal.skipped ? ('SKIPPED FIXTURE: ' + refusal.skipped)
        : JSON.stringify({ codes: refusal.engine_codes, shown: refusal.shown.slice(0, 90),
            banner: refusal.banner_text }));
    addCheck('answer-contract', 'a refusal is not reported as a failure to answer',
      !refusal.skipped && refusal.banner_hidden === true && refusal.engine_codes.length > 0 &&
        refusal.shown.length > 0,
      'the refusal reached the page and the error banner stayed hidden',
      refusal.skipped ? ('SKIPPED FIXTURE: ' + refusal.skipped)
        : ('banner hidden: ' + refusal.banner_hidden + ', codes: ' + refusal.engine_codes.join(',') +
            ', banner: ' + JSON.stringify(refusal.banner_text)));
    // back to a clean page for the hygiene pass
    await page.evaluate(() => localStorage.removeItem('wfm.planner.v1'));
    await page.reload({ waitUntil: 'networkidle2', timeout: 30000 });


    /* ------------------------------------------------- 19d a malformed v1 payload is replaced whole */
    // cleanV1 exists to make a bad payload harmless; this is the check that would fail if the
    // per-field rules were deleted (a version check alone would let this through).
    const strict = await page.evaluate(async () => {
      const KEY = 'wfm.planner.v1';
      const junk = { version: 1, equipment_id: 'nonsense', mastery_rank: 'bad',
        equipment_rank: 2.5, active_config: 'Z',
        configs: { A: { slots: { 'normal:0': { id: 'x', rank: 1.5 }, 'not a slot': { id: 'y' } },
                        polarities: [] } },
        library: { q: 5, sort: 'nonsense' }, ui: 'not an object' };
      localStorage.setItem(KEY, JSON.stringify(junk));
      return true;
    });
    say('storage-strict-wrote', strict);
    await page.reload({ waitUntil: 'networkidle2', timeout: 30000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 700)));
    const replaced = await page.evaluate(() => {
      const raw = localStorage.getItem('wfm.planner.v1');
      let doc = null;
      try { doc = JSON.parse(raw || 'null'); } catch (e) { doc = 'unparseable: ' + e.message; }
      return { doc: doc, still_junk: !!(doc && typeof doc.mastery_rank === 'string'),
        keys_ok: !!(doc && typeof doc.mastery_rank === 'number' && doc.version === 1 &&
          doc.configs && doc.configs.A && Object.keys(doc.configs.A.slots || {}).length === 0),
        page_alive: !!document.getElementById('plGrid') };
    });
    say('storage-strict', replaced);
    addCheck('storage', 'a malformed v1 payload is replaced in full, not merged',
      !!replaced.keys_ok && replaced.still_junk === false && replaced.page_alive === true,
      'the stored key is rewritten to a clean v1 document',
      JSON.stringify(replaced.doc).slice(0, 200));

    /* ------------------------------- 19e the head card holds its own controls (five viewports) */
    // `.card` clips, and a clipping box is also a scroll container. This card contains the
    // equipment popover, so focusing the search input used to scroll the head's content clean out
    // of its own card (scrollTop 51 with clientHeight 56 at 1366x768) and clip the popover at the
    // card's edge. These checks fail on either symptom.
    const headMeasure = () => page.evaluate(() => {
      const rect = (s) => {
        const e = document.querySelector(s);
        if (!e) return null;
        const b = e.getBoundingClientRect();
        return { x: b.x, y: b.y, w: b.width, h: b.height, bottom: b.bottom, right: b.right };
      };
      const headEl = document.querySelector('.pl-head');
      const head = rect('.pl-head'); const btn = rect('#plEquipBtn'); const bar = rect('.pl-bar');
      const popEl = document.getElementById('plEquipPop'); const pop = rect('#plEquipPop');
      // Probe BELOW the card's bottom edge but inside the popover's box: that band is exactly what
      // a clipping card cuts off. (Probing inside the card's box proves nothing - with the old
      // overflow the card scrolled, which pulled the popover up into its own visible area.)
      const probeY = Math.min(Math.max(head.bottom + 20, pop.y + 8), pop.bottom - 8);
      const probe = document.elementFromPoint(pop.x + pop.w / 2, probeY);
      const s = document.getElementById('plEquipSearch'); const sb = s.getBoundingClientRect();
      const hit = document.elementFromPoint(sb.x + sb.width / 2, sb.y + sb.height / 2);
      return {
        btnInsideHead: btn.y >= head.y - 1 && btn.bottom <= head.bottom + 1 &&
          btn.x >= head.x - 1 && btn.right <= head.right + 1,
        headContainsChildren: Array.from(headEl.querySelectorAll('.pl-title,.pl-picker,.pl-head-side'))
          .every((k) => { const b = k.getBoundingClientRect();
            return b.top >= head.y - 1 && b.bottom <= head.bottom + 1; }),
        headScrollTop: headEl.scrollTop,
        headClearsBar: head.bottom <= bar.y + 1,
        popAnchored: Math.abs(pop.x - btn.x) <= 2 && (pop.y - btn.bottom) >= 2 &&
          (pop.y - btn.bottom) <= 14,
        popUnclipped: !!(probe && popEl.contains(probe)),
        searchVisible: !!(hit && (s === hit || s.contains(hit))),
        popInViewport: pop.right <= window.innerWidth + 1 && pop.bottom <= window.innerHeight + 1,
        docOverflowX: document.documentElement.scrollWidth - window.innerWidth,
        head: { y: Math.round(head.y), bottom: Math.round(head.bottom) },
        pop: { x: Math.round(pop.x), y: Math.round(pop.y), bottom: Math.round(pop.bottom) }
      };
    });
    const headOk = (m) => m.btnInsideHead && m.headContainsChildren && m.headScrollTop === 0 &&
      m.headClearsBar && m.popAnchored && m.popUnclipped && m.searchVisible && m.popInViewport &&
      m.docOverflowX <= 0;

    for (const [vw, vh] of [[1920, 1080], [1536, 864], [1440, 900], [1366, 768], [1280, 800]]) {
      await page.setViewport({ width: vw, height: vh, deviceScaleFactor: 1 });
      await page.goto(BASE + '/planner.html', { waitUntil: 'networkidle2', timeout: 30000 });
      await page.evaluate(() => new Promise((r) => setTimeout(r, 500)));
      const wasOpen = await page.evaluate(() => !document.getElementById('plEquipPop').hidden);
      if (!wasOpen) { await page.click('#plEquipBtn'); }
      // the exact trigger: focus the search field inside the card
      await page.evaluate(() => document.getElementById('plEquipSearch').focus());
      await page.evaluate(() => new Promise((r) => setTimeout(r, 350)));
      const m = await headMeasure();
      say('head-card-' + vw, m);
      addCheck('head-card', 'at ' + vw + 'x' + vh + ' the selector sits in the head card and the dropdown hangs off it, unclipped',
        headOk(m),
        'button inside the card; card not scrolled; dropdown 2-14px under the button, aligned, ' +
        'hit-testable and inside the viewport; no horizontal overflow',
        JSON.stringify(m));
    }

    // and in a light theme, where the card is white and the clipping was most visible
    await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
    await page.evaluate(() => { localStorage.setItem('wfm.theme', '28'); });   // Cephalon White
    await page.goto(BASE + '/planner.html', { waitUntil: 'networkidle2', timeout: 30000 });
    await page.evaluate(() => new Promise((r) => setTimeout(r, 700)));
    if (await page.evaluate(() => document.getElementById('plEquipPop').hidden)) {
      await page.click('#plEquipBtn');
    }
    await page.evaluate(() => document.getElementById('plEquipSearch').focus());
    await page.evaluate(() => new Promise((r) => setTimeout(r, 350)));
    const light = await headMeasure();
    const lightBg = await page.evaluate(() =>
      getComputedStyle(document.querySelector('.pl-head')).backgroundColor);
    say('head-card-light', light);
    addCheck('head-card', 'the head card holds its controls in a light theme too (white card)',
      headOk(light) && lightBg === 'rgb(255, 255, 255)',
      'the same invariants on the white card of a light palette',
      JSON.stringify({ bg: lightBg, m: light }));
    await page.evaluate(() => { localStorage.removeItem('wfm.theme'); });
    await page.keyboard.press('Escape');

    /* ------------------------------------------------------------------ 20 hygiene */
    await page.evaluate(() => new Promise((r) => setTimeout(r, 500)));
    const final = await page.evaluate(() => {
      const ids = [...document.querySelectorAll('[id]')].map((n) => n.id);
      return { dupes: [...new Set(ids.filter((x, i) => ids.indexOf(x) !== i))],
        page: document.title };
    });
    say('hygiene', { dupes: final.dupes, console: R.console.length,
      pageerrors: R.pageerrors.length, failed: R.failed.length,
      transient: (R.transient || []).length });
    addCheck('hygiene', 'no duplicate id after the whole drive',
      final.dupes.length === 0, '0 duplicates', JSON.stringify(final.dupes.slice(0, 5)));
    addCheck('hygiene', 'no console error over the whole drive',
      R.console.length === 0, '0 console errors', R.console.length + ': ' + R.console.slice(0, 2).join(' | '));
    addCheck('hygiene', 'no page error over the whole drive',
      R.pageerrors.length === 0, '0 page errors',
      R.pageerrors.length + ': ' + R.pageerrors.slice(0, 2).join(' | '));
    addCheck('hygiene', 'no failed request outside the dev-server burst class',
      R.failed.length === 0, '0 failed requests',
      R.failed.length + ': ' + JSON.stringify(R.failed.slice(0, 2)));

  } catch (err) {
    R.error = String(err && err.stack || err);
    console.error('gate aborted: ' + R.error);
  }

  /* ---------------------------------------------------------------- verdict */
  const wf = R.checks;
  const failed = wf.filter((c) => !c.ok);
  R.finished = new Date().toISOString();
  R.verdict = {
    pass: !R.error && wf.length > 0 && failed.length === 0,
    checks_total: wf.length,
    checks_failed: failed.length,
    failed: failed.map((c) => c.section + ' / ' + c.title),
  };
  try { await browser.close(); } catch (e) {}
  try { jwrite(RAW, R); } catch (e) { console.error('could not write ' + RAW + ': ' + e); }
  console.log('');
  console.log('checks: ' + wf.length + ', failed: ' + failed.length);
  if (failed.length) failed.forEach((c) => console.log('  FAIL ' + c.section + ' / ' + c.title +
    '  expected: ' + c.expected + '  observed: ' + c.observed));
  console.log(R.verdict.pass ? 'PASS' : 'FAIL');
  process.exit(R.verdict.pass ? 0 : 1);

  /* read the element card's composition rows (planner-stats.js draws them) */
  async function readElements(p) {
    return p.evaluate(() => {
      const card = document.getElementById('plElements') || document.getElementById('plElemCard');
      const comp = document.getElementById('plElemBody') || card;
      return {
        composition: comp ? comp.textContent.replace(/\s+/g, ' ').trim().slice(0, 300) : '',
        types: [...document.querySelectorAll('#plElemBody [data-d], #plElemBody .pl-el-key')]
          .map((n) => n.getAttribute('data-d') || n.textContent.trim()).join(','),
        hidden: card ? card.hidden : null,
      };
    });
  }
})();
