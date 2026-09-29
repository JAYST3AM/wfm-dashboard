/* ============================================================================================
 * design/_session/workflow_gate.js — the Trading Session WORKFLOW acceptance driver.
 *
 *   node design/_session/workflow_gate.js        (normally run through: python
 *                                                 design/_session/workflow_gate.py)
 *
 * It drives the LIVE app through the one path the workflow spec calls the loop:
 *
 *   Whisper  ->  CONTACTED  ->  the reconcile check  ->  Confirm
 *
 * and records, for every step, what it expected and what it actually saw. Nothing is inferred
 * from a payload the UI did not produce: each claim is read back from the DOM the panel painted,
 * from the app's own HTTP answer, and from the store files on disk.
 *
 * WHAT IS REAL HERE
 *   - the app itself: the same /#trade/session panel, the same session.js, the same
 *     POST /api/session/start | /api/whisper | /api/session/confirm on the real server.py.
 *   - the click on the buyer's "Whisper" button goes through ordWhisper's real funnel
 *     (static/app.js) and the server's real whisper_post -> trade_session.contact().
 *   - the reconcile check is the panel's own Checks card, fed by the payload GET /api/session
 *     already carries (no second ask, no timer in the panel).
 *   - Confirm is the one canonical completion path (POST /api/session/confirm -> trade_log.json).
 *
 * WHAT IS NOT REAL, AND IS LABELLED AS SUCH IN THE OUTPUT
 *   - the whisper TRANSPORT. scripts/whisper.py types the line into a running Warframe window
 *     with the Windows keyboard. There is no game window in a gate run, and a gate must never
 *     send a real whisper to a real player, so the launcher's boot script replaces ONLY
 *     whisper.send() with a stub that reports the same success the real keyboard path reports
 *     (True, R_SENT). message()/line()/copy() and everything after them are the real code.
 *   - the GAME's side of reconciliation. The change a sale makes (one stack shorter, platinum
 *     higher) is written by this driver straight into the throwaway report.json / plat_history.json
 *     that scripts/report.py and scripts/snapshot_plat.py would normally write. Everything the app
 *     does with those numbers - snapshot at contact, propose(), the check's evidence, the confirm -
 *     is the real code, unmodified.
 *
 * INPUTS (env, all set by workflow_gate.py)
 *   WFM_BASE    the running dashboard (http://127.0.0.1:<port>)
 *   WFM_DATA    the throwaway data dir the server was booted against
 *   WFM_RAW     where to write the machine-readable result (JSON)
 *   WFM_CHROME  chrome.exe (optional)
 *   WFM_PROFILE chrome user-data dir (optional)
 *   WFM_SLUG    the seeded item slug (optional, default primed_continuity)
 * ============================================================================================ */
'use strict';

/* puppeteer-core: the repo has no node_modules of its own, so resolve the shared copy the other
   harnesses use (same list as design/_stage10/gate.js). */
let puppeteer = null, PUPPETEER_FROM = null;
for (const cand of [process.env.WFM_PUPPETEER, 'puppeteer-core', 'puppeteer',
                    'F:/VSC Projects/pb-bench/node_modules/puppeteer-core']) {
  if (!cand) continue;
  try { puppeteer = require(cand); PUPPETEER_FROM = cand; break; } catch (e) { /* next */ }
}
if (!puppeteer) {
  console.error('workflow_gate.js: no puppeteer-core found (tried WFM_PUPPETEER, node_modules, pb-bench)');
  process.exit(2);
}
const fs = require('fs');
const path = require('path');

const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const DATA = process.env.WFM_DATA;
const RAW = process.env.WFM_RAW || 'workflow-raw.json';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PROFILE = process.env.WFM_PROFILE || null;
const SLUG = process.env.WFM_SLUG || 'primed_continuity';

/* the documented blocked-CDN class (card / warframe art that is not in the local cache): a missing
   image is not a workflow failure and is counted separately, never hidden. */
const BLOCKED_HOSTS = ['warframe.market', 'cdn.warframestat.us', 'wfcdn.com', 'wiki.warframe.com',
                       'raw.githubusercontent.com'];
const isBlocked = (url) => {
  try { const h = new URL(url).host; return BLOCKED_HOSTS.some((b) => h === b || h.endsWith('.' + b)); }
  catch (e) { return false; }
};

/* what this run drives, spelled out so the report can state the intent before the result */
const SEED = { slug: SLUG, rank: 0, qty: 3, price: 48, copies_before: 4, plat_before: 1220,
               copies_after: 1, plat_after: 1220 + 3 * 48 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jread = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { return null; } };
const jwrite = (p, o) => fs.writeFileSync(p, JSON.stringify(o, null, 1));

const R = {
  meta: { started: new Date().toISOString(), finished: null, base: BASE, data: DATA, slug: SLUG,
          node: process.version, chrome: CHROME, puppeteer: PUPPETEER_FROM, seed: SEED,
          whisper_transport: 'stubbed (no game window in a gate run; see the header of this file)' },
  steps: [],
  checks: [],
  evidence: {},
  console: [],              /* real console errors / page errors, tagged with the step */
  console_transient: [],    /* the documented net-stack class (see TRANSIENT below) */
  failed_requests: [],
  transient_requests: [],
  blocked_cdn: [],
  observations: [],
  error: null,
};

/* The documented transient class, the same four kernel-level codes the release gate
   (design/_stage10/gate.js) treats as "the single-threaded dev server refused a burst" rather than
   an application failure. Every row here is still reported, with the URL rechecked directly. */
const TRANSIENT = /ERR_NO_BUFFER_SPACE|ERR_INSUFFICIENT_RESOURCES|ERR_NETWORK_CHANGED|ERR_CONNECTION_RESET/;

let CURRENT_STEP = 'boot';
const step = (name, detail) => {
  CURRENT_STEP = name;
  R.steps.push({ name: name, at: new Date().toISOString(), detail: detail || '' });
};
const addCheck = (s, title, ok, expected, observed, note, diagnostic) => {
  R.checks.push({ step: s, title: title, ok: !!ok, expected: String(expected),
                  observed: String(observed), note: note || '', diagnostic: !!diagnostic });
  return !!ok;
};
const str = (v) => (v === null || v === undefined) ? '' : String(v);

/* ------------------------------------------------------------------ page readers --------- */
/* Everything the report says the screen showed is read here, once, as text. */
async function snapshot(page) {
  return await page.evaluate(() => {
    const txt = (sel) => { const el = document.querySelector(sel); if (!el) return null;
      return el.innerText.replace(/\s+/g, ' ').trim(); };
    const q = (sel) => Array.from(document.querySelectorAll(sel));
    return {
      meta: txt('#sessionMeta'),
      focus: txt('#sessionFocus'),
      queue: txt('#sessionQueueList'),
      pending: txt('#sessionPending'),
      checks: txt('#sessionChecks'),
      checks_meta: txt('#sessionChecksMeta'),
      pending_meta: txt('#sessionPendMeta'),
      kpis: txt('#sessionKpis'),
      start_hidden: (() => { const b = document.querySelector('#sessionStart');
        return b ? b.classList.contains('hidden') : null; })(),
      /* the box, by rendered visibility: `classList.add('hidden')` is worthless if an id-scoped rule
         outranks the bare .hidden class, which is exactly how the accent Start button sat through a
         live session (2026-09-29) */
      start_visible: (() => { const b = document.getElementById('sessionStartBox');
        return b ? !!b.offsetParent : null; })(),
      buyer_user: txt('#sessionFocus .orduser'),
      whisper_btns: q('#sessionFocus .ordwsp').length,
      whisper_say: (() => { const r = document.querySelector('#sessionFocus .ordres');
        return r ? r.textContent.trim() : null; })(),
      pending_rows: q('#sessionPending .sessrow').length,
      check_rows: q('#sessionChecks .sesscheck').map((r) => r.innerText.replace(/\s+/g, ' ').trim()),
      confirm_btns: q('#sessionChecks .sessconf').map((b) => b.textContent.trim()),
      queue_rows: q('#sessionQueueList .sessrow').length,
      panel_open: (() => { const p = document.querySelector('#tp-session');
        return p ? !p.classList.contains('hidden') : null; })(),
      hash: location.hash,
    };
  });
}

/* the app's own answer, read through the page so it is the same origin the UI talks to */
async function api(page, p) {
  try {
    return await page.evaluate(async (url) => {
      const r = await fetch(url);
      return { status: r.status, body: await r.json() };
    }, p);
  } catch (e) { return { status: 0, body: null, error: String(e).slice(0, 200) }; }
}

/* the store on disk - the same file the session module writes */
const storeFile = () => path.join(DATA, 'trade_session.json');
const logFile = () => path.join(DATA, 'trade_log.json');

async function clickRetry(page, sel, tries) {
  for (let i = 0; i < (tries || 3); i++) {
    try { await page.click(sel); return true; } catch (e) { await sleep(400); }
  }
  return false;
}

/* ------------------------------------------------------------------ the run -------------- */
async function main() {
  if (!DATA) { throw new Error('WFM_DATA is required (the throwaway data dir)'); }
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new', userDataDir: PROFILE || undefined,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,900'],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });
    page.on('console', (m) => {
      if (m.type() !== 'error') return;
      const text = m.text().slice(0, 300);
      (TRANSIENT.test(text) ? R.console_transient : R.console).push({ step: CURRENT_STEP, text: text });
    });
    page.on('pageerror', (e) => {
      const text = ('pageerror: ' + String(e)).slice(0, 300);
      /* a failed fetch rejects inside load()'s Promise.all, so the page reports an uncaught
         TypeError right after the net stack refuses a burst. It is recorded either way; whether it
         counts is decided below by the same rule the release gate uses (a direct recheck). */
      R.pending_page_errors = (R.pending_page_errors || []).concat([{ step: CURRENT_STEP, text: text }]);
    });
    page.on('requestfailed', (r) => {
      const why = str(((r.failure() || {}).errorText));
      const row = { step: CURRENT_STEP, url: r.url().slice(0, 240), why: why };
      if (isBlocked(r.url())) R.blocked_cdn.push(row);
      else if (TRANSIENT.test(why)) R.transient_requests.push(row);
      else R.failed_requests.push(row);
    });
    /* the app's own HTTP answer to the whisper, captured at the socket, not read off the screen */
    page.on('response', async (r) => {
      if (r.url().indexOf('/api/whisper') === -1) return;
      try { R.evidence.whisper_response = { status: r.status(), body: await r.json() }; }
      catch (e) { /* non-JSON */ }
    });

    /* ---- 1. load the Session panel ------------------------------------------------------ */
    step('load', 'GET ' + BASE + '/#trade/session, wait for the panel and its first payload');
    await page.goto(BASE + '/#trade/session', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForFunction(() => {
      const f = document.querySelector('#sessionFocus');
      const s = document.querySelector('#sessionStart');
      return !!(f && f.innerText.trim() && s);
    }, { timeout: 60000, polling: 300 });
    let dom = await snapshot(page);
    R.evidence.load = dom;
    addCheck('load', 'the Session panel renders and paints from GET /api/session',
             dom.panel_open === true && dom.focus !== null && dom.start_visible === true,
             'panel open, Start rendered, the panel painted a state',
             'panel_open=' + dom.panel_open + ' start_visible=' + dom.start_visible +
             ' focus="' + str(dom.focus).slice(0, 80) + '"');
    addCheck('load', 'no console errors on the Session surface',
             R.console.filter((c) => c.step === 'load').length === 0,
             '0 console errors while the panel loaded',
             R.console.filter((c) => c.step === 'load').length + ' console error(s) at load, ' +
             R.console_transient.filter((c) => c.step === 'load').length + ' transient net-stack row(s)',
             R.console.filter((c) => c.step === 'load').length
               ? JSON.stringify(R.console.filter((c) => c.step === 'load').slice(0, 3)) : '');
    addCheck('load', 'no failed request outside the documented blocked-CDN class',
             R.failed_requests.length === 0, '0 failed requests',
             R.failed_requests.length + ' failed (' + R.blocked_cdn.length + ' blocked-CDN excluded)',
             R.failed_requests.length ? JSON.stringify(R.failed_requests.slice(0, 3)) : '');

    /* ---- 2. Start the session ----------------------------------------------------------- */
    step('start', 'click #sessionStart (the panel\'s own Start trading control)');
    if (!await clickRetry(page, '#sessionStart')) throw new Error('could not click #sessionStart');
    await page.waitForFunction(() => {
      const m = document.querySelector('#sessionMeta');
      const b = document.querySelector('#sessionFocus .ordwsp');
      return !!(m && /\btrades\b/.test(m.textContent) && b);
    }, { timeout: 45000, polling: 300 });
    dom = await snapshot(page);
    const s1 = await api(page, '/api/session');
    const queue = (s1.body && s1.body.queue) || [];
    R.evidence.start = { dom: dom, session: s1.body && s1.body.session,
                         queue: queue.map((r) => ({ slug: r.slug, rank: r.rank, qty: r.qty,
                                                    price: r.price, state: r.state,
                                                    buyer: (r.buyer || {}).user || null })) };
    addCheck('start', 'the Start control steps aside once a session is live',
             dom.start_visible === false,
             'the start box is out of the flow while the loop owns the panel',
             'start_visible=' + dom.start_visible + ' start_hidden=' + dom.start_hidden);
    addCheck('start', 'Start opened a real session with a queue', !!(s1.body && s1.body.session) && queue.length > 0,
             'a session with at least one queue row', 'session=' + str(s1.body && s1.body.session && s1.body.session.id) +
             ' queue_rows=' + queue.length + ' (dom rows ' + dom.queue_rows + ')');
    addCheck('start', 'the focus card is on the seeded item and offers a buyer to whisper',
             !!dom.buyer_user && dom.whisper_btns === 1,
             'one buyer row with one Whisper button on the focus item',
             'buyer="' + str(dom.buyer_user) + '" whisper_btns=' + dom.whisper_btns +
             ' focus="' + str(dom.focus).slice(0, 120) + '"');

    /* ---- 3. Whisper -> CONTACTED -------------------------------------------------------- */
    step('whisper', 'click the focus card\'s Whisper button (ordWhisper -> POST /api/whisper, mode send)');
    if (!await clickRetry(page, '#sessionFocus .ordwsp')) throw new Error('could not click the Whisper button');
    /* the row's own answer is the app's verdict on the send; read it before the next repaint
       clears SESSION_SAY (the panel shows it once, in the freshest paint) */
    let say = null;
    try {
      await page.waitForFunction(() => {
        const r = document.querySelector('#sessionFocus .ordres');
        return !!(r && r.textContent.trim());
      }, { timeout: 20000, polling: 200 });
      say = await page.evaluate(() => {
        const r = document.querySelector('#sessionFocus .ordres');
        return r ? r.textContent.trim() : null;
      });
    } catch (e) { /* left null: reported as a failure below */ }
    /* the pending list is painted by the load() the whisper triggers: wait for it, so the save
       change we make next cannot be mistaken for this refresh */
    await page.waitForFunction(() => document.querySelectorAll('#sessionPending .sessrow').length > 0,
                               { timeout: 45000, polling: 300 });
    dom = await snapshot(page);
    const s2 = await api(page, '/api/session');
    const pend = (s2.body && s2.body.pending) || [];
    const p0 = pend[0] || {};
    R.evidence.whisper = { dom_whisper_say: say, dom_whisper_response: R.evidence.whisper_response || null,
                           pending: pend, queue_row_state: (queue[0] || {}).state || null,
                           session_after: s2.body && s2.body.session };
    addCheck('whisper', 'the app reports the whisper as SENT (not merely copied)', say === 'Sent to game',
             'the row says "Sent to game"', 'row answer: "' + str(say) + '"',
             'ordWhisper prints "Sent to game" only for a response with sent=true');
    addCheck('whisper', 'the sent whisper opened a CONTACTED pending trade',
             p0.state === 'CONTACTED' && !!p0.id, 'state=CONTACTED with an id',
             'state=' + str(p0.state) + ' id=' + str(p0.id) + ' slug=' + str(p0.slug));
    addCheck('whisper', 'the contact snapshotted the stack and the platinum it went out at',
             p0.inv_before === SEED.copies_before && p0.plat_before === SEED.plat_before &&
             p0.expected_plat === SEED.price && p0.qty === SEED.qty,
             'copies=' + SEED.copies_before + ' plat=' + SEED.plat_before + ' asked=' + SEED.price +
             'p x' + SEED.qty,
             'copies=' + str(p0.inv_before) + ' plat=' + str(p0.plat_before) + ' asked=' +
             str(p0.expected_plat) + 'p x' + str(p0.qty) + ' basis=' + str(p0.inv_basis) +
             ' buyer=' + str(p0.buyer));
    addCheck('whisper', 'the pending trade is on screen (Waiting on a confirmation)',
             dom.pending_rows > 0, 'at least one pending row',
             dom.pending_rows + ' row(s): "' + str(dom.pending).slice(0, 140) + '"');

    /* ---- 4. reconcile check ------------------------------------------------------------- */
    step('reconcile', 'the game-saved numbers change, then wait for the app\'s OWN refresh to raise the check');
    const before = jread(storeFile());
    const pending_before = ((before || {}).pending || [])[0] || {};
    const t0 = Math.floor(Date.now() / 1000);
    /* what scripts/report.py + scripts/snapshot_plat.py see after a sale: one stack shorter, the
       platinum the trade paid. Written into the throwaway dir only. */
    jwrite(path.join(DATA, 'report.json'),
           { sell_now: [{ slug: SLUG, name: 'Primed Continuity', cat: 'mod', lane_rank: SEED.rank,
                          sellable_count: SEED.copies_after, wts: 70, wtb: 45, n_buy: 5, vol48: 110,
                          lane_ask: 60 }] });
    jwrite(path.join(DATA, 'plat_history.json'),
           [{ ts: t0 - 3600, plat: SEED.plat_before }, { ts: t0, plat: SEED.plat_after }]);
    const saved = { report: jread(path.join(DATA, 'report.json')),
                    plat_history: jread(path.join(DATA, 'plat_history.json')) };
    const wrote = saved.report.sell_now[0].sellable_count === SEED.copies_after &&
                  saved.plat_history[saved.plat_history.length - 1].plat === SEED.plat_after;
    R.evidence.reconcile = { save_written: saved, pending_before: pending_before,
                             expected_delta: SEED.qty * SEED.price };
    addCheck('reconcile', 'the simulated game save landed in the throwaway data dir', wrote,
             'report sellable_count=' + SEED.copies_after + ', plat=' + SEED.plat_after,
             'report=' + str(saved.report && saved.report.sell_now[0].sellable_count) +
             ' plat=' + str(saved.plat_history && saved.plat_history.slice(-1)[0].plat));

    /* The panel has no timer of its own: the check rides the load() the app already runs on its
       own cadence (static/app.js syncAutoRefresh, capped at 60s). Waiting for that is the honest
       demonstration. If it never comes we reload the page the way a user would - and whichever
       path produced what we then saw is stated, never assumed. */
    const checkOnScreen = async (ms) => {
      try {
        await page.waitForFunction(() => !!document.querySelector('#sessionChecks .sessconf'),
                                   { timeout: ms, polling: 500 });
        return true;
      } catch (e) { return false; }
    };
    let on_screen = await checkOnScreen(45000);
    let refresh_mode;
    if (on_screen) {
      refresh_mode = "app-cadence (no interaction: the check rode the app's own refresh)";
    } else {
      step('reconcile', 'no check appeared on the app cadence - reloading the page as a user would');
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForFunction(() => {
        const f = document.querySelector('#sessionFocus');
        return !!(f && f.innerText.trim());
      }, { timeout: 60000, polling: 300 });
      on_screen = await checkOnScreen(25000);
      refresh_mode = on_screen
        ? 'reload-fallback (the app cadence did not raise it in 45s)'
        : 'NEVER (45s on the app cadence, then a reload and 25s more)';
    }
    dom = await snapshot(page);
    const s3 = await api(page, '/api/session');
    const prop = ((s3.body && s3.body.proposals) || [])[0] || {};
    /* When the payload carries a proposal but nothing reached the screen, read the panel's own
       reader instead of guessing: FEAT.session.proposals is what the server sent, and what
       sessionPayload() hands the renderer is what the Checks card paints from. */
    const probe = await page.evaluate(() => {
      const out = {};
      try {
        out.feat_proposals = (((typeof FEAT !== 'undefined' ? FEAT : {}) || {}).session || {}).proposals || [];
      } catch (e) { out.feat_proposals = 'n/a'; }
      try { out.panel = sessionPayload(); } catch (e) { out.panel_error = String(e); }
      try { out.checks_text = (document.querySelector('#sessionChecks') || {}).innerText; } catch (e) { /* gone */ }
      try { out.meta_text = (document.querySelector('#sessionChecksMeta') || {}).innerText; } catch (e) { /* gone */ }
      return out;
    });
    Object.assign(R.evidence.reconcile, {
      dom: { checks: dom.checks, checks_meta: dom.checks_meta, check_rows: dom.check_rows,
             confirm_btns: dom.confirm_btns, meta: dom.meta },
      proposal: prop, refresh_mode: refresh_mode,
      panel_probe: {
        feat_session_proposals: Array.isArray(probe.feat_proposals) ? probe.feat_proposals.length : probe.feat_proposals,
        session_payload_proposals: probe.panel ? (probe.panel.proposals === undefined ? 'undefined' : probe.panel.proposals.length) : 'n/a',
        session_payload_source: 'static/session.js sessionPayload()',
        checks_card_text: probe.checks_text, checks_meta_text: probe.meta_text,
      },
    });
    addCheck('reconcile', 'the check is an EXACT match on copies left and platinum arrived',
             prop.verdict === 'exact' && prop.copies_left === SEED.qty &&
             prop.plat_delta === SEED.qty * SEED.price,
             'verdict=exact copies_left=' + SEED.qty + ' platinum=+' + (SEED.qty * SEED.price),
             'verdict=' + str(prop.verdict) + ' copies_left=' + str(prop.copies_left) +
             ' platinum=+' + str(prop.plat_delta) + ' asked=' + str(prop.total_plat) +
             ' evidence=' + JSON.stringify(prop.evidence));
    addCheck('reconcile', 'the check reached the screen and offers the Confirm click',
             on_screen && dom.check_rows.length > 0 && dom.confirm_btns.length > 0,
             'a check row with a Confirm button, from the panel the user is looking at',
             refresh_mode + '; rows=' + dom.check_rows.length + ' buttons=' +
             JSON.stringify(dom.confirm_btns) + ' card="' + str(dom.checks).slice(0, 120) + '"',
             'the server computed the proposal correctly either way (the check above), so this is ' +
             'about the panel showing it, not about the reconcile logic');
    addCheck('reconcile', 'the check writes nothing on its own (a proposal, never a trade)',
             !fs.existsSync(logFile()),
             'no trade_log.json before the Confirm click',
             fs.existsSync(logFile()) ? 'trade_log.json already exists' : 'trade_log.json absent');

    /* ---- 5. Confirm -------------------------------------------------------------------- */
    /* One click, one transaction - the same function the shipped button calls. If the check is
       not on screen there is no button to click, so the run switches to a LABELLED diagnostic:
       the payload key the renderer asks for is forwarded by a shim (nothing else about the panel
       changes), the real renderer repaints, and the real Confirm path is then driven so the rest
       of the chain can be reported separately from the defect that hides it. */
    const diag = !on_screen;
    const stepName = diag ? 'confirm-probe' : 'confirm';
    step(stepName, diag
      ? 'DIAGNOSTIC: forward the payload key static/session.js reads (sessionPayload()), repaint ' +
        'with the real renderer, then drive the real Confirm click'
      : "click the check's Confirm button (POST /api/session/confirm)");
    if (diag) {
      const patched = await page.evaluate(() => {
        if (typeof window.sessionPayload !== 'function') return 'no global sessionPayload';
        const orig = window.sessionPayload;
        window.sessionPayload = function () {
          const P = orig();
          const S = (typeof FEAT !== 'undefined' && FEAT && FEAT.session) || {};
          P.proposals = S.proposals || [];     /* the only change: the key the renderer already reads */
          P.needs_you = S.needs_you || 0;
          return P;
        };
        renderSession();                        /* the panel's own painter, unmodified */
        return 'forwarded';
      });
      R.evidence.reconcile.diagnostic_shim = { sessionPayload_forwarding: patched };
      addCheck(stepName, 'with the payload key forwarded, the real renderer paints the check',
               patched === 'forwarded' && await checkOnScreen(20000),
               'the Checks card paints one check with a Confirm button',
               'shim=' + patched + '; card="' + str((await snapshot(page)).checks).slice(0, 140) + '"',
               'DIAGNOSTIC - this is not a pass for the shipped panel; it isolates the defect to ' +
               'the one key the renderer is not given', true);
    }
    if (!await clickRetry(page, '#sessionChecks .sessconf')) throw new Error('could not click Confirm');
    await page.waitForFunction(() => {
      const m = document.querySelector('#sessionMeta');
      return !!(m && /\b1 trade\b/.test(m.textContent));
    }, { timeout: 45000, polling: 300 });
    dom = await snapshot(page);
    const s4 = await api(page, '/api/session');
    const log = jread(logFile());
    const after = jread(storeFile());
    const entry = (log || [])[0] || {};
    const qrow = (((after || {}).session || {}).queue || [])[0] || {};
    const prow = (((after || {}).pending || [])[0]) || {};
    const done0 = ((((after || {}).session || {}).done || [])[0]) || {};
    R.evidence[diag ? 'confirm_probe' : 'confirm'] = {
      diagnostic: diag,
      dom: { meta: dom.meta, kpis: dom.kpis, focus: dom.focus, checks: dom.checks,
             confirm_btns: dom.confirm_btns },
      summary: (s4.body || {}).summary || null,
      trade_log: log, store_queue_row_state: qrow.state, store_pending_state: prow.state,
      store_confirmed: (after || {}).confirmed || null,
    };
    const where = diag ? ' DIAGNOSTIC (payload key forwarded).' : '';
    addCheck(stepName, 'one trade was written to trade_log.json',
             Array.isArray(log) && log.length === 1 && !!entry.id && entry.slug === SLUG,
             'exactly one record for ' + SLUG + ' with an id',
             'records=' + (Array.isArray(log) ? log.length : 'none') + ' id=' + str(entry.id) +
             ' slug=' + str(entry.slug) + ' qty=' + str(entry.qty) + ' plat=' + str(entry.plat) +
             ' total=' + str(entry.total) + ' source=' + str(entry.source), where, diag);
    addCheck(stepName, 'the money recorded for the trade is what the check asked for',
             entry.total === SEED.price * SEED.qty,
             'total=' + (SEED.price * SEED.qty) + 'p (3 x 48p, the "asked: 144" the check showed)',
             'total=' + str(entry.total) + 'p', where, diag);
    addCheck(stepName, 'the record\'s plat is the price per copy, the shape confirm() documents',
             entry.plat === SEED.price,
             'plat=' + SEED.price + 'p (the per-copy price the row showed: "3 @ 48p each")',
             'plat=' + str(entry.plat) + 'p',
             'the draft propose() offers (trade_draft(plat=expected_plat x qty)) carries the sum in ' +
             '`plat`, and confirm() then multiplies it again into `total`; the comment above ' +
             'confirm() says "`plat` is the price per copy and `total` is the money for the trade ... ' +
             'one with `plat` holding the sum double counted it"', diag);
    addCheck(stepName, 'the session credited exactly the money the trade paid',
             ((s4.body || {}).summary || {}).earned_plat === SEED.qty * SEED.price,
             'earned_plat=' + (SEED.qty * SEED.price) + 'p (' + SEED.qty + ' x ' + SEED.price + 'p)',
             'earned_plat=' + str(((s4.body || {}).summary || {}).earned_plat) + 'p', where, diag);
    addCheck(stepName, 'the session counted the trade and closed the pending row',
             ((s4.body || {}).summary || {}).trades === 1 && (((s4.body || {}).pending) || []).length === 0,
             'summary.trades=1 and no pending trade left',
             'trades=' + str(((s4.body || {}).summary || {}).trades) + ' earned=' +
             str(((s4.body || {}).summary || {}).earned_plat) + ' pending=' +
             (((s4.body || {}).pending) || []).length, where, diag);
    addCheck(stepName, 'the store shows the queue row and the pending row completed',
             qrow.state === 'COMPLETED' && prow.state === 'COMPLETED' &&
             !!(after || {}).confirmed && (after || {}).confirmed.indexOf(entry.id) !== -1,
             'queue row COMPLETED, pending COMPLETED, the trade id in confirmed[]',
             'queue=' + str(qrow.state) + ' pending=' + str(prow.state) +
             ' confirmed=' + JSON.stringify((after || {}).confirmed), where, diag);
    const focusText = str(dom.focus);
    R.observations = [];
    const wr = (R.evidence.whisper || {}).dom_whisper_response || {};
    const wbody = wr.body || {};
    if (wbody.line) {
      R.observations.push({ what: 'the exact line the session\'s buyer row whispered (kind "' +
        str(((R.evidence.whisper || {}).pending || [{}])[0].kind) + '", the same kind the Orders tab ' +
        'sends for a buy-book row)',
        where: 'scripts/whisper.py message() verbs, driven through ordWhisper; the gate does not judge ' +
               'the wording, it records it',
        saw: wbody.line });
    }
    if (/\d+pp\b/.test(focusText)) {
      R.observations.push({ what: 'the end-of-session card prints a doubled platinum unit ("+432pp earned", "+432pp average")',
        where: 'static/session.js sessionEndCard(): sessionPlat() already appends "p" and the card appends "p earned"',
        saw: focusText.slice(0, 200) });
    }
    if (done0.plat !== entry.plat) {
      R.observations.push({ what: 'the session\'s done[] entry and the trade_log record use the same "plat" key for different things',
        where: 'session done[0].plat=' + str(done0.plat) + ' (the money for the trade) vs trade_log[0].plat=' +
               str(entry.plat) + ' (the price per copy, with the money in trade_log[0].total=' + str(entry.total) + ')',
        saw: 'same sale, one key, two readings - the session summary reads done[], anything summing the log reads total' });
    }
    addCheck(stepName, 'the screen shows one trade and no check left to confirm',
             /\b1 trade\b/i.test(str(dom.meta)) && dom.confirm_btns.length === 0,
             'the meta line reads 1 trade; the Checks card offers nothing',
             'meta="' + str(dom.meta) + '" confirm_btns=' + JSON.stringify(dom.confirm_btns) +
             ' focus="' + focusText.slice(0, 140) + '"', where, diag);

    /* ---- 6. hygiene: the net stack, rechecked the way the release gate rechecks it ---------- */
    step('hygiene', 're-verify every connection-level failure with a direct fetch from node');
    const rechecks = [];
    for (const row of R.transient_requests) {
      let status = null, rerr = null;
      try { const r = await fetch(row.url); status = r.status; }
      catch (e) { rerr = String(e).slice(0, 120); }
      rechecks.push({ step: row.step, url: row.url, why: row.why, recheck_status: status,
                      recheck_error: rerr });
    }
    /* A pageerror is only counted as the app's when a request really failed. When the net stack
       refused a burst and every refused URL answers on a direct recheck, the uncaught TypeError
       was that refusal landing in load()'s Promise.all - the class the release gate documents. */
    const cleared = rechecks.filter((x) => x.recheck_status && x.recheck_status < 400);
    const consequence = R.transient_requests.length > 0 && R.failed_requests.length === 0 &&
                        cleared.length === rechecks.length;
    for (const pe of (R.pending_page_errors || [])) {
      if (consequence && /Failed to fetch|NetworkError|Load failed/i.test(pe.text)) {
        R.console_transient.push(Object.assign({}, pe, {
          classified: 'a consequence of the net-stack refusal below (every refused URL answered on recheck)' }));
      } else {
        R.console.push(pe);
      }
    }
    R.evidence.hygiene = { transient_requests: R.transient_requests, rechecks: rechecks,
                           console_errors: R.console, console_transient: R.console_transient,
                           failed_requests: R.failed_requests, blocked_cdn: R.blocked_cdn };
    addCheck('hygiene', 'every connection-level failure clears on a direct recheck',
             rechecks.length === 0 || cleared.length === rechecks.length,
             'each refused URL answers when asked again from node',
             rechecks.length + ' refusal(s), ' + cleared.length + ' cleared: ' +
             JSON.stringify(rechecks.slice(0, 4)),
             'the same rule design/_stage10/gate.js uses: a burst refused by the dev server is not ' +
             'a release failure, and saying so requires the recheck');
    addCheck('hygiene', 'no console error or failed request outside that class, over the whole drive',
             R.console.length === 0 && R.failed_requests.length === 0,
             '0 console errors, 0 failed requests',
             R.console.length + ' console error(s), ' + R.failed_requests.length + ' failed request(s)',
             R.console.length ? JSON.stringify(R.console.slice(0, 4)) : '');
  } catch (e) {
    R.error = String((e && e.stack) || e).slice(0, 2000);
  } finally {
    try { await browser.close(); } catch (e) { /* chrome may already be gone */ }
  }
}

main().then(async () => {
  R.meta.finished = new Date().toISOString();
  const wf = R.checks.filter((c) => !c.diagnostic);
  const dx = R.checks.filter((c) => c.diagnostic);
  const failed = wf.filter((c) => !c.ok);
  R.verdict = { pass: !R.error && wf.length > 0 && failed.length === 0,
                checks_total: wf.length, checks_failed: failed.length,
                diagnostics_total: dx.length, diagnostics_failed: dx.filter((c) => !c.ok).length,
                crashed: R.error };
  jwrite(RAW, R);
  for (const c of R.checks) {
    console.log((c.ok ? '  ok   ' : '  FAIL ') + '[' + c.step + ']' + (c.diagnostic ? ' (diagnostic)' : '') +
                ' ' + c.title);
    if (!c.ok) console.log('         expected: ' + c.expected + '\n         observed: ' + c.observed);
  }
  if (R.error) console.log('  CRASH ' + R.error.split('\n')[0]);
  console.log('WORKFLOW ' + (R.verdict.pass ? 'PASS' : 'FAIL') + ' - ' +
              (wf.length - failed.length) + '/' + wf.length + ' checks, ' +
              (dx.length - R.verdict.diagnostics_failed) + '/' + dx.length + ' diagnostics');
  process.exit(R.verdict.pass ? 0 : 1);
}).catch((e) => {
  try { R.error = String((e && e.stack) || e).slice(0, 2000); R.meta.finished = new Date().toISOString();
    R.verdict = { pass: false, checks_total: R.checks.length, checks_failed: R.checks.length, crashed: R.error };
    jwrite(RAW, R); } catch (e2) { /* nowhere to write */ }
  console.error('workflow_gate.js crashed: ' + e);
  process.exit(1);
});
