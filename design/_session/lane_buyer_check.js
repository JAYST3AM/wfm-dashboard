/* design/_session/lane_buyer_check.js - the lane rule Home and the session panel both read.

   Session 2026-09-29: Home's Next action had a slug-wide fallback (`sessionAskedBy(r) || who[0]`),
   which handed the wrong lane's buyer back whenever the row's own lane had none: the top plan row
   can be rank 6 while only rank 0 has a buyer. The fallback is gone, and this checks the rule that
   replaced it - by EVALUATING static/session.js's own sessionAskedBy, not a copy of it, so a change
   to the rule cannot pass here and fail in the browser.

   Usage: node design/_session/lane_buyer_check.js      (exit 0 = every case holds) */
'use strict';
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..', '..');
const SESS = fs.readFileSync(path.join(REPO, 'static', 'session.js'), 'utf8');

const START = 'function sessionAskedBy(row)';
if (SESS.indexOf(START) < 0) {
  console.error('lane_buyer_check: sessionAskedBy is gone from static/session.js');
  process.exit(2);
}
/* the function's own text, brace-matched, so the harness never re-implements the rule */
const from = SESS.indexOf(START);
let depth = 0, to = -1;
for (let i = SESS.indexOf('{', from); i < SESS.length; i++) {
  if (SESS[i] === '{') depth++;
  else if (SESS[i] === '}') { depth--; if (depth === 0) { to = i + 1; break; } }
}
const source = SESS.slice(from, to);
if (!source.includes('if (!mine && theirs) continue;')) {
  console.error('lane_buyer_check: the rule no longer refuses a laned buyer for an unlaned row');
  process.exit(2);
}
const askedBy = new Function('FEAT', source + '; return sessionAskedBy;');

const CASES = [
  {
    name: 'a rank-6 row with only a rank-0 buyer shows NOTHING (the reported regression)',
    row: { slug: 'primed_continuity', name: 'Primed Continuity', lane: 'rank 6', rank: null },
    queue: [{ slug: 'primed_continuity', lane: 'rank 0', rank: 0, buyer: 'WrongLane', buy_price: 48 }],
    want: null,
  },
  {
    name: 'the same row with its OWN lane buyer shows that buyer',
    row: { slug: 'primed_continuity', name: 'Primed Continuity', lane: 'rank 6', rank: null },
    queue: [{ slug: 'primed_continuity', lane: 'rank 0', rank: 0, buyer: 'WrongLane', buy_price: 48 },
            { slug: 'primed_continuity', lane: 'rank 6', rank: 6, buyer: 'RightLane', buy_price: 49 }],
    want: 'RightLane',
  },
  {
    name: 'rank 0 is a lane, not a missing one (a falsy-zero trap)',
    row: { slug: 'vitality', lane: 'rank 0', rank: 0 },
    queue: [{ slug: 'vitality', lane: 'rank 0', rank: 0, buyer: 'Zero', buy_price: 3 }],
    want: 'Zero',
  },
  {
    name: 'an intact relic row never takes the radiant buyer',
    row: { slug: 'meso_i1_relic', lane: 'intact', rank: null },
    queue: [{ slug: 'meso_i1_relic', lane: 'radiant', rank: null, buyer: 'Radiant', buy_price: 35 }],
    want: null,
  },
  {
    name: 'and the radiant row takes its own',
    row: { slug: 'meso_i1_relic', lane: 'radiant', rank: null },
    queue: [{ slug: 'meso_i1_relic', lane: 'radiant', rank: null, buyer: 'Radiant', buy_price: 35 }],
    want: 'Radiant',
  },
  {
    name: 'the plain item (no lane at all) still gets its lane-less buyer',
    row: { slug: 'organ_shatter', lane: '', rank: null },
    queue: [{ slug: 'organ_shatter', lane: '', rank: null, buyer: 'Plain', buy_price: 9 }],
    want: 'Plain',
  },
  {
    name: 'an unlaned row refuses a laned buyer rather than borrowing one',
    row: { slug: 'organ_shatter', lane: '', rank: null },
    queue: [{ slug: 'organ_shatter', lane: 'rank 0', rank: 0, buyer: 'Laned', buy_price: 9 }],
    want: null,
  },
  {
    name: 'another item entirely is never this row\u2019s buyer',
    row: { slug: 'maul', lane: 'rank 0', rank: 0 },
    queue: [{ slug: 'vitality', lane: 'rank 0', rank: 0, buyer: 'Other', buy_price: 3 }],
    want: null,
  },
  {
    name: 'a queue row with no buyer is not a buyer',
    row: { slug: 'maul', lane: 'rank 0', rank: 0 },
    queue: [{ slug: 'maul', lane: 'rank 0', rank: 0, buyer: '', buy_price: 7 }],
    want: null,
  },
  {
    name: 'an empty run queue answers nothing',
    row: { slug: 'maul', lane: 'rank 0', rank: 0 },
    queue: [],
    want: null,
  },
];

let failed = 0;
for (const c of CASES) {
  const got = askedBy({ runqueue: { queue: c.queue } })(c.row);
  const name = got ? got.buyer : null;
  const ok = name === c.want;
  if (!ok) failed++;
  console.log((ok ? '  ok   ' : '  FAIL ') + c.name + ' -> ' + (name === null ? 'no buyer' : name)
    + (ok ? '' : ' (expected ' + (c.want === null ? 'no buyer' : c.want) + ')'));
}
console.log((failed ? 'LANE BUYER FAIL - ' : 'LANE BUYER PASS - ') + (CASES.length - failed) + ' of '
  + CASES.length + ' cases');
process.exit(failed ? 1 : 0);
