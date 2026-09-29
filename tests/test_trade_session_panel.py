"""Trade > Session (stage 3, 2026-09-29): the trading loop gets its own panel, first in the strip.

Source of truth: docs/trading-session-workflow.md sections 1-8 + 12. design/_session/audit-frontend.md
section 6 gives the cheapest slot-in order and design/_session/implementation-map.md the backend
contract (GET /api/session, also /api/feature/session).

What is held in place here:
  * the strip is Session / Orders / Sell / Buy / History / Advanced, Session is the first button and
    #tp-session is the panel it controls, shipping hidden with Sell still the surface a fresh load
    opens (the two pins in tests/test_trade_orders_tab.py and tests/test_trade_layout.py were
    re-targeted deliberately for the new order);
  * #trade/session resolves through the router's own sub-tab rule ('tp-' + sub) and lands on the
    session panel - NOT the tp-sell fallback the audit flagged as the silent bug;
  * the renderer lives in static/session.js (app.js does not grow a second renderer), reads
    FEAT.session from the shared feature fan-out in load(), never fetches its own endpoint and adds
    no timer - a refresh rides the existing load() cadence only;
  * the panel drives the loop through the endpoints that exist - start / focus / state / end - and
    sends a whisper through the order book's own ordWhisper funnel: no second send path, and no
    POST /api/session/contact, because a sent whisper is already recorded server-side;
  * Start trading rides Home's Next-action footer (never a seventh Home card) at the quiet button
    weight, so the card keeps its one accent action;
  * the panel ships no Confirm control: there is no reconcile/confirm route yet, so the hook is a
    comment where the control will go, not a button that would call nothing;
  * every why fact is one span, a fact the payload does not carry prints nothing, and every string
    the new surface adds stays inside the copy diet (8 words / 90 chars / one period).
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()

INDEX = read('static/index.html')
APP = read('static/app.js')
SESS = read('static/session.js')
CSS = read('static/session.css')

SESSION_IDS = ('sessionMeta', 'sessionStart', 'sessionNext', 'sessionSkip', 'sessionHold',
               'sessionEnd', 'sessionKpis', 'sessionFocus', 'sessionSay', 'sessionQueueMeta',
               'sessionQueueList', 'sessionPendMeta', 'sessionPending')


def trade_section(html):
    return html.split('id="view-trade"', 1)[1].split('</section>', 1)[0]


def tab_strip(html):
    return trade_section(html).split('<nav id="tradeTabs"', 1)[1].split('</nav>', 1)[0]


def session_panel(html):
    """the panel's own markup: from its wrapper to the Orders panel that follows it"""
    return trade_section(html).split('id="tp-session"', 1)[1].split('id="tp-orders"', 1)[0]


# ------------------------------------------------------------------ 1. the tab and the panel

def test_the_session_tab_is_first_and_its_panel_ships_hidden():
    nav = tab_strip(INDEX)
    assert 'id="tt-session"' in nav.split('<button', 2)[1], 'Session is the first button in the strip'
    assert ('<button role="tab" id="tt-session" data-tp="tp-session" aria-selected="false" '
            'aria-controls="tp-session">Session</button>') in nav
    sec = trade_section(INDEX)
    assert ('<div id="tp-session" class="tpanel hidden" role="tabpanel" aria-labelledby="tt-session">'
            ) in sec
    assert sec.index('id="tp-session"') < sec.index('id="tp-orders"') < sec.index('id="tp-sell"')
    assert sec.count('class="tpanel" role="tabpanel"') == 1, 'Sell is still the one visible panel'
    panel = session_panel(INDEX)
    for sid in SESSION_IDS:
        assert 'id="%s"' % sid in panel, sid
    assert 'id="sessionStart"' in panel and 'id="sessionNext"' in panel
    assert 'id="ordSell"' not in panel and 'id="ordValues"' not in panel, \
        'the panel borrows the book classes, never the book ids (ids are unique page-wide)'


def test_the_panels_ids_are_lower_camel_and_unique_on_the_page():
    panel = session_panel(INDEX)
    ids = re.findall(r'id="([A-Za-z0-9_-]+)"', panel)
    assert ids, 'the panel declares its own ids'
    for i in ids:
        assert re.fullmatch(r'[a-z]+[A-Za-z0-9]*', i), i
    assert len(ids) == len(set(ids)), 'no duplicate id inside the panel'
    whole = re.findall(r'id="([A-Za-z0-9_-]+)"', INDEX)
    for i in ids:
        assert whole.count(i) == 1, i + ' exists once on the page'


# ------------------------------------------------------------------ 2. the route

def test_the_hash_route_reaches_the_session_panel_not_the_sell_fallback():
    """The audit's risk 1: without the tab/panel pair, #trade/session silently rendered Sell."""
    tps = re.findall(r'data-tp="([a-z-]+)"', tab_strip(INDEX))
    assert tps[0] == 'tp-session', tps
    panel = 'tp-' + 'session'                      # applyHash's own rule, verbatim below
    assert panel in tps, 'the router output is a known panel: switchTradeTab cannot fall back'
    assert 'tp-' + 'nope' not in tps, 'the fallback exists for a panel the strip does not know'
    assert "switchTradeTab(v === 'history' ? 'tp-history' : (sub ? 'tp-' + sub : 'tp-sell'));" in APP
    assert "if (!ok) panelId = 'tp-sell';" in APP
    # the strip writes the hash on click, so the tab is deep-linkable both ways
    assert "history.replaceState(null, '', '#trade/' + t.dataset.tp.replace('tp-', ''));" in APP
    # and opening the panel paints it - read on open, never on a timer
    assert "if (panelId === 'tp-session') renderSession();" in APP


# ------------------------------------------------------------------ 3. the renderer and its data

def test_the_renderer_paints_from_the_shared_fan_out_and_polls_nothing():
    assert 'function renderSession()' in SESS
    assert 'function renderSession(' not in APP, 'app.js must not grow a second renderer'
    assert "'advisor', 'session']" in APP, 'the payload rides load() one feature fan-out'
    assert 'FEAT.session' in SESS, 'the renderer reads the payload it is handed'
    assert "fetch('/api/feature/session')" not in SESS
    assert "fetch('/api/session')" not in SESS, 'a bare GET would be a second read of the same store'
    assert 'setInterval' not in SESS and 'setTimeout' not in SESS, 'no timer in the session panel'
    assert 'renderSession();' in APP, 'load() paints it with every other renderer'
    assert '"/session.js"' in INDEX and INDEX.index('"/session.js"') < INDEX.index('"/app.js"'), \
        'load() and the router call it during app.js parse, so it loads first (like home.js)'
    assert '"/session.css"' in INDEX


def test_the_loop_actions_use_the_endpoints_that_exist():
    assert "sessionPost('start', {})" in SESS
    assert "sessionPost('focus', { index:" in SESS
    assert "const body = { slug: f.slug, rank: f.rank ?? null, state }" in SESS
    assert "if (f.lane) body.lane = f.lane" in SESS, \
        'two lanes of one item share a slug: the state change has to name its lane'
    assert "? 'start' : 'end'" in SESS
    assert "'SKIPPED'" in SESS and "'HELD'" in SESS, 'the two states the panel sets'
    assert "fetch('/api/session/' + action" in SESS and "method: 'POST'" in SESS
    assert "await load()" in SESS, 'every action re-reads through the one refresh'
    # one new endpoint, used exactly once, and no session-only poll
    assert "sessionPost('confirm', { trade: draft })" in SESS
    # one route, two call sites, both of them a human saying this trade completed: the check that
    # came from the save, and the focus card Mark sold control (spec sections 1 and 5)
    assert SESS.count("sessionPost('confirm'") == 2
    assert "sessionMarkSold" in SESS and 'class="btn sesssold"' in SESS
    assert 'api/session/reconcile' not in SESS, 'the check rides the payload, never a second ask'


def test_the_whisper_goes_through_the_order_books_one_funnel():
    assert 'ordWhisper(btn)' in SESS, 'the app has exactly one send path'
    assert "fetch('/api/whisper'" not in SESS, 'no second whisper call site'
    assert "fetch('/api/session/contact'" not in SESS and "sessionPost('contact'" not in SESS, \
        'a sent whisper is already recorded server-side as CONTACTED - do not POST it again'
    assert 'SESSION_SAY' in SESS, 'the send answer survives the refresh it triggers'
    # the row is the book's own markup, so ordWhisper's own guards apply unchanged
    assert 'class="ordrow" data-kind="buy"' in SESS
    assert 'class="ordwsp" data-item=' in SESS
    assert 'class="ordres" aria-live="polite"' in SESS
    assert "data-kind=\"buy\"" in SESS


# ------------------------------------------------------------------ 4. Home's one action, and no card

def test_start_trading_rides_home_next_action_and_adds_no_seventh_card():
    home = INDEX.split('id="view-home"', 1)[1].split('</section>', 1)[0]
    cards = re.findall(r'<div class="card[^"]*" id="([A-Za-z0-9_-]+)"', home)
    assert cards == ['todayCard', 'homeSellNext', 'alertsCard', 'sellQueueCard', 'recentCard',
                     'chartCard'], 'the Home band list is exactly these six'
    assert '${sessionHomeAction()}' in APP, "Home's Next-action footer renders the control"
    assert 'function sessionHomeAction()' in SESS
    assert 'id="homeStartTrading"' in SESS and '>Start trading</button>' in SESS
    assert 'href="#trade/session"' in SESS, 'a live session links back into the loop'
    assert "btn.id === 'homeStartTrading'" in SESS, 'delegated: the footer is re-rendered'
    # UX pass 2026-09-29: the card's one accent control is the loop action, not the head's link to
    # the plan surface - Home asks "what do I do with this item", and the answer is the session
    # 2026-09-29 (second pass): the third accent is the exact check's Confirm - one accent per
    # decision, and the decision that ends the loop is not a quiet little button any more.
    assert SESS.count('btn primary') == 3, 'Start trading, Open session, and the check Confirm'
    assert 'class="btn primary" id="homeStartTrading"' in SESS
    assert 'class="btn primary" href="#trade/session"' in SESS
    assert 'class="btn primary sessconf"' in SESS, "an exact check is the one action there"


# ------------------------------------------------------------------ 5. one confirmation path

def test_the_panel_confirms_through_the_canonical_route_only():
    """Stage 5 shipped reconciliation and the confirm transaction. What the panel may do is send the
    draft the payload handed it to POST /api/session/confirm - one button per proposal, one call
    site, and nothing that resolves a trade locally."""
    panel = session_panel(INDEX)
    assert 'id="sessionChecks"' in panel and 'id="sessionChecksMeta"' in panel
    assert 'SESSION_DRAFTS' in SESS, 'the draft behind each Confirm comes from the payload'
    assert 'class="btn sessconf" data-pending=' in SESS
    assert SESS.count('sessconf') >= 2, 'exact and ambiguous both offer the click'
    assert "p.verdict === 'exact'" in SESS and "p.verdict === 'ambiguous'" in SESS
    assert 'P.proposals' in SESS, 'the check rides the payload load() already fetched'
    assert "state: 'COMPLETED'" not in SESS, 'the panel never posts a completion'
    assert "state: 'POSSIBLE MATCH'" not in SESS, 'nor a maybe: completion is the server route'
    assert "sessionPost('confirm'" in SESS and SESS.count("sessionPost('confirm'") == 2
    assert 'api/session/reconcile' not in SESS and 'api/session/reconcile' not in panel
    assert 'SESSION_STATE_WORD' in SESS and "'POSSIBLE MATCH'" in SESS, \
        'the state is shown, never resolved'


def test_no_proposal_ever_confirms_itself():
    """Nothing in the panel fires a confirm without a click: the only caller is the delegated
    listener, and a proposal with no verdict word offers no button at all."""
    assert SESS.count('sessionConfirm(') == 2, 'defined once, called once (delegated listener)'
    assert SESS.count('sessionMarkSold(') == 2, 'the manual completion is a click away, never a loop'
    assert "t.closest('.sessconf')" in SESS
    assert ": '';" in SESS, 'nothing/none proposals render without a confirm button'


# ------------------------------------------------------------------ 6. copy

MAX_WORDS, MAX_CHARS, MAX_PERIODS = 8, 90, 1
CANDS = re.compile(r"'([^'\n]{16,})'|\"([^\"\n]{16,})\"|>([^<>{}\n]{16,})<")
CODEY = re.compile(r'[{}<>$]|://|\bpx\b|\bvar\b|url\(|\.js\b|\.json\b|\.css\b|function|=>|\\u|'
                   r'data-|class=|id=|/[a-z_]+/|\+|\?|\bnoopener\b|\bnoreferrer\b|\bpx\b')


def offenders(src):
    """the same rule tests/test_copy_diet.py enforces on static/*.js|html, applied to the new
    surface's own source (its scanner walks every file in static/, so this is a second look at the
    exact strings this stage added rather than a second rule)"""
    bad = []
    for m in CANDS.finditer(src):
        x = next(g for g in m.groups() if g)
        if not (re.search(r'[a-z]', x) and ' ' in x):
            continue
        if CODEY.search(x):
            continue
        words = len(x.split())
        periods = x.count('. ') + (1 if x.rstrip().endswith('.') else 0)
        if words > MAX_WORDS or len(x) > MAX_CHARS or periods > MAX_PERIODS:
            bad.append((words, len(x), x.strip()))
    return bad


def test_every_string_the_new_surface_adds_is_copy_diet_clean():
    for src, name in ((SESS, 'static/session.js'), (session_panel(INDEX), 'index.html #tp-session')):
        bad = offenders(src)
        assert not bad, '%s: %s' % (name, bad[:6])


# ------------------------------------------------------------------ 7. honesty of the facts

def test_the_why_facts_omit_what_the_payload_does_not_carry():
    block = SESS.split('function sessionWhyBits', 1)[1].split('\n}', 1)[0]
    assert '\u2014' not in block, 'a fact the payload lacks prints nothing, never a placeholder dash'
    for key in ('safe_copies', 'sales_48h', 'buyers_online', 'median', 'week_pct', 'liquidity',
                'buy_orders'):
        assert 'w.' + key in block, key
    assert "bits.map(x => '<span>'" in SESS, 'one span per fact: the sbits anatomy'
    assert 'conf.reasons' in SESS, 'the full confidence line rides the title'
    assert 'rank_mismatch' in SESS, \
        'a dropped buyer says why (the rank it belongs to) instead of a blanket no-buyer line'


def test_the_empty_states_use_the_shared_pattern():
    assert 'EMPTY_ICON' in SESS and "'<div class=\"empty\">'" in SESS
    for line in ('No session open yet.', 'Nothing queued yet.', 'Nothing waiting on a confirmation.'):
        assert line in SESS, line


def test_the_panel_marks_stale_pending_trades_without_resolving_them():
    """A pending trade is a whisper that went out: the panel shows it (and marks the old ones) so the
    user can find it again. The only way it ever closes is the canonical confirm, on a click."""
    assert 'stale_pending' in SESS and 'class="chip">old</span>' in SESS
    assert 'sessionPendingRows(P.pending, P.stale)' in SESS
    assert 'api/session/reconcile' not in SESS, 'the check rides the payload'
    assert SESS.count("sessionPost('confirm'") == 2, 'and a trade closes only through confirm'
    assert "sessionPost('state'" in SESS, 'the only states the panel sets are Skip and Hold'
    assert "state: 'COMPLETED'" not in SESS, 'a trade closes through confirm, not a state POST'


def test_the_panel_reuses_the_trade_vocabulary():
    panel = session_panel(INDEX)
    for cls in ('tpanel', 'card', 'card-head', 'card-title', 'actions', 'btn', 'kpis', 'picks',
                'status', 'dim small'):
        assert 'class="%s' % cls in panel, cls
    for cls in ('ordrow', 'ordwsp', 'ordres', 'sessrow', 'l-name', 'empty', 'chip', 'kpi', 'sessrow sesspend'):
        assert cls in SESS, cls
    assert '#tp-session' in CSS, 'the panel own rules are scoped to it'
    assert 'setInterval' not in CSS


# ------------------------------------------------------------------ 7. summary, Why?, and the buyer

def test_the_why_control_is_a_disclosure_not_a_wall():
    """Spec section 7: a small Why? control, facts only when the payload carries them."""
    assert 'sessionWhyBits(why)' in SESS
    assert 'Why this trade?' in SESS
    assert 'class="acc sub sess-whyacc"' in SESS, 'the app own disclosure pattern'
    assert "'· ' + w.safe_copies" in SESS and 'safe copies' in SESS
    assert 'lowest sell' in SESS and 'highest buy' in SESS, 'the price block the decision needs'
    assert "'· ' + w.sales_48h" in SESS and 'median ' in SESS
    # a fact the payload omits prints nothing: every branch is guarded, none prints a dash
    assert SESS.count('!== undefined && w.') >= 3


def test_the_end_of_session_card_counts_only_what_happened():
    """Spec section 6: trades, platinum, duration, average, highest sale - and skipped/held when
    there are any."""
    assert 'function sessionEndCard(' in SESS and 'Session complete' in SESS
    assert 'function sessionDur(' in SESS and "'h ' + rest + 'm'" in SESS
    assert 'sum.average_plat' in SESS and 'sum.best' in SESS and 'highest sale' in SESS
    assert 'sum.skipped' in SESS and 'sum.held' in SESS
    assert 'P.session.ended_ts || sum.complete' in SESS, 'ended OR nothing left to work'
    assert 'sessionEndCard(sum)' in SESS


def test_home_offers_the_buyer_not_just_the_price():
    """Spec section 8: the Next action ends at a buyer. It reuses the book whisper row, and when the
    run queue has no buyer for the top row it renders nothing rather than a dead button."""
    assert 'function sessionHomeWhisper(' in SESS
    assert 'Whisper buyer' in SESS
    assert 'class="ordwsp" data-item=' in SESS
    assert 'class="ordrow" data-kind="buy"' in SESS
    assert 'class="ordres" aria-live="polite"' in SESS
    assert 'FEAT.runqueue' in SESS, 'the buyer comes from the payload already fetched'
    assert "if (!q || !q.buyer) return '';" in SESS, 'no buyer, no button'
    assert 'sessionHomeAction()' in APP and 'sessionHomeAction()' in SESS


def test_the_focus_card_carries_the_full_action_set():
    """Spec section 1: Whisper, Open live orders, Skip, Hold - plus a manual completion. The manual
    one goes through the same confirm route as a checkpoint does (section 5: one path)."""
    assert 'class="btn sessorders"' in SESS and 'Open live orders' in SESS
    assert 'class="btn sesssold"' in SESS and 'Mark sold' in SESS
    assert "'sessionSkip'" in SESS and "'sessionHold'" in SESS
    assert "location.hash = '#trade/orders'" in SESS, 'the live book is one click away'
    assert 'ORD.slug = slug' in SESS, 'and it opens on this item'
    assert "source: 'manual'" in SESS, 'the manual completion is labelled as one'
    assert SESS.count('function sessionMarkSold(') == 1


# ------------------------------------------- the view model is the renderer's whole input
def test_the_view_model_carries_every_key_the_renderers_read():
    """sessionPayload() is what every renderer in this file reads as `P`, and it is hand-written:
    the proposals the server decided on were missing from it, so the Checks card rendered empty for
    ever - the API answered EXACT and the panel showed nothing. This pins the mapping: any new
    `P.<key>` a renderer reads must be carried here. Only a real browser run finds the gaps this
    cannot see, which is what design/_session/workflow_gate.py is for."""
    import re
    body = re.search(r'function sessionPayload\(\)\s*\{(.*?)\n\}', SESS, re.S)
    assert body, 'sessionPayload() not found'
    mapping = body.group(1)
    read = sorted({m for m in re.findall(r'\bP\.([a-z_]+)', SESS)})
    assert read, 'no P.<key> reads found - the regex would be silently useless'
    missing = [k for k in read if (k + ':') not in mapping]
    assert not missing, 'sessionPayload() does not carry %s' % missing
    for key in ('proposals', 'needs_you'):
        assert (key + ':') in mapping, key


def test_the_check_card_renders_what_the_payload_decided():
    """The renderer paints the proposals it is given, with the one confirm path per row."""
    assert 'SESSION_DRAFTS[p.pending_id] = p.trade' in SESS
    assert 'ck.innerHTML = sessionCheckRows(props)' in SESS
    assert 'function sessionCheckRows(' in SESS
    assert "class=\"btn sessconf\"" in SESS

# ------------------------------------------------------------------ 2. the next action and the lane rule
# Jay's UX pass (2026-09-29): "make the next action unmistakable - what to sell, for how much, who
# wants it, and what to do next". Three pins: the start control sits with the empty state, the
# suggested queue answers "who wants it" instead of repeating one state word down the list, and Home
# carries one action plus the whisper row rather than the same buyer facts twice.

def test_the_start_action_sits_with_the_empty_state_it_belongs_to():
    panel = session_panel(INDEX)
    box = panel.split('id="sessionStartBox"', 1)[1]
    assert 'id="sessionStart"' in box, 'the start control lives in the box that hides with it'
    assert 'class="btn primary"' in box.split('id="sessionStart"', 1)[0] +         box.split('id="sessionStart"', 1)[1][:200], 'one accent action, so it reads as the next step'
    head = panel.split('id="sessionNext"', 1)[0]
    assert 'id="sessionStart"' not in head, 'not up in the card head next to the live controls'
    assert "getElementById('sessionStartBox')" in SESS, 'renderSession hides the box, not the button'
    assert "'hidden', !!P.live" in SESS


def test_the_suggested_queue_says_who_wants_each_row_and_never_a_state_word():
    assert 'function sessionAskedBy(row)' in SESS, 'the run queue is read through one rule'
    assert 'const who = live ? null : sessionAskedBy(r);' in SESS, 'the suggested rows ask it'
    assert 'no buyer' in SESS, "a row with no buyer says so rather than naming another lane's"
    live_first = SESS.split('const first = live', 1)[1].split(';', 1)[0]
    assert 'sessionStateWord(r)' in live_first, 'a live queue keeps the state chip, which changes'
    rest = SESS.split('const first = live', 1)[1]
    suggested = rest.split(': (who', 1)[1].split('${first}', 1)[0]
    assert 'sessionStateWord' not in suggested,         'the suggested list never prints the same state word on every row'
    # the lane rule itself: a buyer for another lane is not this row's buyer
    body = SESS.split('function sessionAskedBy', 1)[1].split(chr(10) + '}', 1)[0]
    assert 'if (mine && theirs !== mine) continue;' in body
    assert 'if (!mine && theirs) continue;' in body, 'a lane-less row takes only a lane-less buyer'


def test_home_next_action_shows_one_action_and_the_whisper_row():
    foot = APP.split('class="next-foot"', 1)[1].split('</div>`;', 1)[0]
    assert 'next-buyer' not in foot, 'the whisper row already names the buyer, price and status'
    assert foot.index('next-nobuyer') < foot.index('sessionHomeAction()'),         'the honest gap first, then the one action'
    # this pin used to assert the fallback itself (`|| who[0]`), which is what broke Home: it looked
    # defensive and handed back the wrong lane's buyer. The rule alone is the pin now.
    assert 'const b = sessionAskedBy(r);' in APP and 'who[0]' not in APP

def test_the_first_run_view_hides_the_two_cards_that_have_nothing_to_say():
    """Before a session exists, "Nothing waiting on a confirmation" and "Nothing to check yet" are two
    empty panels stacked under an empty state. They say nothing about the next action, so they step
    aside; a live session keeps them, where "nothing waiting" is an answer."""
    panel = session_panel(INDEX)
    for cid in ('sessionPendingCard', 'sessionChecksCard'):
        assert 'id="%s"' % cid in panel, cid
        assert panel.index('id="%s"' % cid) > panel.index('id="sessionFocus"'), 'the loop leads'
    assert "['sessionPendingCard', 'sessionChecksCard'].forEach" in SESS
    assert "el.classList.toggle('hidden', !P.session)" in SESS,         'the cards hide only when there is no session at all'


def test_the_buyer_column_separates_a_name_from_an_absence():
    """A buyer is a value; "no buyer" is a state. Same column, different weight - a plain dim string
    reads as another username."""
    assert 'class="chip dim" title="no buyer' in SESS
    assert 'class="sesswho" title=' in SESS, 'a named buyer stays a value, not a pill'


# ----------------------------------------------- the second UX pass (2026-09-29, live-session view)
# What the live-session review found that the fresh-load screens never showed: the accent Start
# trading button survived a whole live session (a specificity bug, not a logic one), the loop's only
# real action - Confirm - sat below two other cards at the quiet weight, and the focus card kept
# offering a first whisper after the whisper had already gone out.

def test_the_start_box_really_hides_when_a_session_is_live():
    """`#tp-session .sess-start` carries an id, so it outranks the bare `.hidden` class: the toggle
    ran and the loudest button in the panel kept advertising "Start trading" through a live session,
    beside the loop's own next action. The hidden state has to be declared at the matching weight."""
    assert '#tp-session .sess-start.hidden { display: none; }' in CSS
    assert "getElementById('sessionStartBox')" in SESS


def test_the_check_comes_up_when_it_is_the_only_action():
    assert 'id="sessionQueueCard"' in session_panel(INDEX)
    body = SESS.split('const loopPane', 1)[1].split('const focus =', 1)[0]
    assert "getElementById('sessionChecksCard')" in body
    assert "getElementById('sessionQueueCard')" in body
    assert 'if ((P.proposals || []).length) loopPane.insertBefore(cCard, qCard)' in body
    assert 'loopPane.appendChild(cCard)' in body, 'and goes back to the end when nothing is waiting'


def test_an_exact_check_is_the_one_accent_action_and_an_ambiguous_one_stays_quiet():
    """The check is the loop's last decision: an exact match is a confirm, so it takes the accent
    weight - once, and only there. An ambiguous one is a judgement call, not a confirmation."""
    assert SESS.count('btn primary sessconf') == 1
    assert "title=\"Log this sale\">Confirm' + total + '</button>'" in SESS,         'the button says the money the click logs, not just "Confirm"'
    assert "(p.trade && p.trade.total)" in SESS, 'the canonical total is the amount shown'
    assert 'class="btn sessconf" data-pending=' in SESS, 'ambiguous keeps the quiet weight'
    assert 'title="Log it as your sale">Looks right</button>' in SESS


def test_the_focus_card_says_when_it_already_whispered_this_buyer():
    """The row's own state is the answer to "did I send it?": a CONTACTED row offers a second send
    with the word for it, instead of the identical button it offered the first time."""
    assert "String(f.state || '').toUpperCase() === 'CONTACTED'" in SESS
    assert "${sent ? 'Whisper again' : 'Whisper'}" in SESS
    assert "data-sent=\"${sent ? '1' : '0'}\"" in SESS
