/* design/_session/home_buyer_gate.js - does HOME show a buyer the row's lane does not have?

   The regression (2026-09-29): renderNextAction() read `sessionAskedBy(r) || who[0]`, so a top plan
   row for rank 6 - a lane with no buyer - displayed the rank-0 buyer for the same slug, complete with
   a Whisper button. The rule was right and the render undid it.

   This drives the REAL Home page against a seeded throwaway store and reads what was painted:
     A  top row rank 6, run queue holds only a rank-0 buyer for that slug
        -> no whisper button, no wrong-lane name, and the head says "See buyers in Trade"
     B  top row rank 0, run queue holds that lane's buyer
        -> one whisper button, the right name, the head says "Open Trade", and the session panel's
           suggested row names the same buyer (Home and the session must agree)

   It is driven by design/_session/home_buyer_gate.py, which owns the server and the fixture.
   Usage: node design/_session/home_buyer_gate.js <base-url>   (prints one JSON line per check) */
'use strict';
let puppeteer = null;
for (const cand of [process.env.WFM_PUPPETEER, 'puppeteer-core',
                    'F:/VSC Projects/pb-bench/node_modules/puppeteer-core']) {
  if (!cand) continue;
  try { puppeteer = require(cand); break; } catch (e) { /* next */ }
}
if (!puppeteer) { console.log(JSON.stringify({ fatal: 'no puppeteer-core' })); process.exit(2); }
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PROFILE = path.join(process.env.TEMP || 'C:/Users/jayde/AppData/Local/Temp', 'home-buyer-profile');

const READ = `(() => {
  const txt = el => (el ? (el.textContent || '').replace(/\\s+/g, ' ').trim() : '');
  const card = document.getElementById('homeSellNext');
  const head = card ? card.querySelector('.home-open') : null;
  const rows = card ? Array.from(card.querySelectorAll('.ordrow')) : [];
  const wsp = card ? Array.from(card.querySelectorAll('.ordwsp')) : [];
  const pane = document.getElementById('tp-session');
  const sessRows = pane ? Array.from(pane.querySelectorAll('#sessionQueueList .sessrow')) : [];
  return {
    hasCard: !!card,
    head: txt(head),
    item: txt(card ? card.querySelector('.next-t') : null),
    sub: txt(card ? card.querySelector('.next-sub') : null),
    price: txt(card ? card.querySelector('.next-pr') : null),
    foot: txt(card ? card.querySelector('.next-foot') : null),
    buyers: rows.map(r => txt(r.querySelector('.orduser'))),
    whisperBtn: wsp.length,
    nobuyer: !!card && !!card.querySelector('.next-nobuyer'),
    sessionRows: sessRows.map(r => txt(r)),
  };
})()`;

const out = [];
const check = (title, ok, expected, observed) =>
  out.push({ title: title, ok: !!ok, expected: expected, observed: observed });

(async () => {
  const which = (process.argv[3] || '').toUpperCase();
  if (which !== 'A' && which !== 'B') { console.log(JSON.stringify({ fatal: 'scenario A or B required' })); process.exit(2); }
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new', userDataDir: PROFILE,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,900'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 900 });
  await page.setCacheEnabled(false);
  await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 45000 });
  await new Promise(r => setTimeout(r, 2500));
  const h = await page.evaluate(READ);
  const sessRows = h.sessionRows.filter(r => /Primed Continuity/.test(r));

  if (which === 'A') {
    check('A: Home rendered its Next-action card', h.hasCard, true, h.hasCard);
    check('A: the top row is the rank-6 lane', /rank 6/.test(h.sub), 'sub names rank 6', h.sub);
    check('A: NO whisper button is offered', h.whisperBtn === 0, '0 whisper buttons',
          h.whisperBtn + ' button(s)');
    check('A: NO buyer row is painted', h.buyers.length === 0, 'no buyer row',
          JSON.stringify(h.buyers));
    check('A: the head action says where to look instead', h.head === 'See buyers in Trade',
          'See buyers in Trade', h.head);
    check('A: the honest gap is stated', h.nobuyer && /No buyer/.test(h.foot),
          'a no-buyer line in the footer', h.foot);
    check('A: the wrong-lane name is nowhere on the card',
          !/WrongLane/.test(h.foot + h.sub + h.head), 'WrongLane absent', h.foot);
    check('A: the session panel agrees (no buyer, no whisper)',
          sessRows.length === 1 && /no buyer/.test(sessRows[0]) && !/WrongLane/.test(sessRows[0]),
          'one suggested row saying "no buyer"', sessRows.join(' /// '));
    check('A: the wrong-lane buyer is not in the session payload either',
          !/WrongLane/.test(sessRows.join(' ')), 'WrongLane absent from the queue',
          sessRows.join(' /// '));
  } else {
    check('B: the top row is the rank-0 lane', /rank 0/.test(h.sub), 'sub names rank 0', h.sub);
    check('B: exactly one whisper button', h.whisperBtn === 1, '1 whisper button',
          h.whisperBtn + ' button(s)');
    check('B: it is the right lane’s buyer', h.buyers.length === 1 && h.buyers[0] === 'RightLane',
          'RightLane', JSON.stringify(h.buyers));
    check('B: the head action opens the plan', h.head === 'Open Trade', 'Open Trade', h.head);
    check('B: the session panel names the same buyer',
          sessRows.length === 1 && /RightLane/.test(sessRows[0]),
          'the session row names RightLane', sessRows.join(' /// '));
  }

  await browser.close();
  out.forEach(c => console.log(JSON.stringify(c)));
  const failed = out.filter(c => !c.ok).length;
  console.log(JSON.stringify({ summary: true, total: out.length, failed: failed, scenario: which }));
  process.exit(0);
})().catch(e => {
  console.log(JSON.stringify({ fatal: String((e && e.message) || e).slice(0, 300) }));
  process.exit(1);
});
