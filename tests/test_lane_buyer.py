"""The lane rule, and the render that has to obey it (regression, 2026-09-29).

Home's Next action read `sessionAskedBy(r) || who[0]`: the rule answered null for a lane with no
buyer, and the slug-wide fallback immediately handed back another lane's buyer - a rank-6 top row
showing the rank-0 buyer's name, price and Whisper button. The rule was right; the render undid it.

Three layers of pin, cheapest first:

  1. the rule itself, evaluated in node from static/session.js (not a copy of it) - so a change to
     the rule cannot pass here and differ in the browser. Skips when node is absent (the CI runner
     has no node; the rule is also mirrored server-side in tests/test_trade_round3.py).
  2. the render's call site: one buyer, from the rule, with no fallback and no slug-wide helper left
     behind (a source pin - this is the half that actually regressed).
  3. the rendered proof: design/_session/home_buyer_gate.py boots the real server against a seeded
     throwaway store and drives the real Home page (rank-6-without-buyer vs the rank-0 inverse).
     Skipped when node, Chrome or puppeteer-core is missing.
"""
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = open(os.path.join(REPO, 'static', 'app.js'), encoding='utf-8').read()
SESS = open(os.path.join(REPO, 'static', 'session.js'), encoding='utf-8').read()
CHECK = os.path.join(REPO, 'design', '_session', 'lane_buyer_check.js')
GATE = os.path.join(REPO, 'design', '_session', 'home_buyer_gate.py')
CHROME = os.environ.get('WFM_CHROME') or 'C:/Program Files/Google/Chrome/Application/chrome.exe'
PUPPETEER = os.environ.get('WFM_PUPPETEER') or 'F:/VSC Projects/pb-bench/node_modules/puppeteer-core'

needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
needs_browser = pytest.mark.skipif(
    shutil.which('node') is None or not os.path.isfile(CHROME) or not os.path.isdir(PUPPETEER),
    reason='node, Chrome or puppeteer-core is missing on this machine')


# ------------------------------------------------------------------ 1. the rule, executed
@needs_node
def test_the_lane_rule_answers_only_for_its_own_lane():
    """Ran, not read: the harness evaluates static/session.js's own sessionAskedBy with a stubbed run
    queue and asserts Jay's case (a rank-6 row, only a rank-0 buyer -> nothing), its inverse (the
    rank-6 buyer exists -> that buyer), the relic refinements, rank 0 as a real lane, and the
    lane-less item that must never borrow a laned buyer."""
    run = subprocess.run(['node', CHECK], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'LANE BUYER PASS' in run.stdout
    assert '10 of 10' in run.stdout


# ------------------------------------------------------------------ 2. the render's call site
def test_home_takes_its_buyer_from_the_rule_alone():
    """The regression was the fallback, not the rule: `sessionAskedBy(r) || who[0]` looked defensive
    and put another lane's buyer back on screen. One call, no fallback, nothing slug-wide left."""
    assert 'const b = sessionAskedBy(r);' in APP
    assert 'sessionAskedBy(r) ||' not in APP, 'the slug-wide fallback is back - it is the bug'
    assert 'who[0]' not in APP
    assert 'homeBuyers' not in APP, 'the slug-wide buyer helper went with the fallback'
    assert 'RUNQ_WHOM' not in APP, 'the hover title that listed slug-wide buyers went too'


def test_the_head_action_states_the_gap_instead_of_pretending():
    """With no buyer for its lane, the card sends the user to the buyers surface - it does not offer a
    whisper. This is the text the gate reads back from the browser."""
    assert "open.textContent = b ? 'Open Trade' : 'See buyers in Trade';" in APP
    assert "no buyer for this lane" in APP
    assert "const q = sessionAskedBy(top);" in SESS, 'the whisper row asks the same rule'
    assert "if (!q || !q.buyer) return '';" in SESS, 'no buyer, no row, no button'


# ------------------------------------------------------------------ 3. the rendered proof
@needs_browser
def test_home_never_paints_a_buyer_from_another_lane():
    """14 checks against the real UI on a throwaway store: scenario A (rank-6 row, only a rank-0
    buyer) must offer no whisper button and name no buyer; scenario B (that lane's buyer) must offer
    exactly one, and the session panel must agree with Home."""
    run = subprocess.run([sys.executable, GATE], cwd=REPO, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-600:]
    assert 'HOME BUYER PASS - 14 of 14 checks' in run.stdout
