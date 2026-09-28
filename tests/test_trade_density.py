"""Trade view density (Jay 2026-09-27): "trade page needs to be condensed to fit the information
on there better." - re-targeted by stage 4 (2026-09-28: Sell / Buy / History + one Advanced layer).

Source-level pins for the layout the QA probe measures headlessly (design/_stage4/qa_trade.js):
the plan table and the held-back list share one row from 1500px, the Advanced panel's three short
cards go 3-across from 1200px, every data row stays inside its <=28px budget, and every id/control
other tests and the probe hook onto is still on the page. Nothing here removes a row, a column or
a button - only the air between them.

2026-09-27 layout pass ("really bad layout. needs to look clean and have proper placement"):
two pins here were legitimately replaced and both are cross-pinned in tests/test_trade_layout.py
for the new placement - the run-queue row template (three columns -> five fixed columns) and the
plan grid (notes capped at 240px -> notes flexible, >= 232px).

Stage 4 re-targeted two more, exactly as design/_stage4/trade-spec.md §4 requires:
  * the three ops cards (Trade limit / Kill switch / Notifications) are now the Advanced panel's
    first band - equal 1fr columns from 1200px, asserted against .adv-cards;
  * "safety controls never sit behind a click" became REACHABILITY: #tt-advanced is one click from
    Sell, #tp-advanced holds every internal id, and the only thing behind a second click is the
    hygiene plan's own disclosure (the kill switch and the trade limit are plain cards).
Everything else in this file is untouched.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


def trade_section(html):
    return html.split('id="view-trade"', 1)[1].split('</section>', 1)[0]


# ------------------------------------------------------------------ the sideways layouts

def test_plan_and_held_back_share_a_row_from_1500px():
    css = read('static/style.css')
    split = '.trade-split { display: grid; grid-template-columns: minmax(0, 1fr);'
    assert split in css, 'single column is the default'
    block = css.split('@media (min-width: 1500px) {', 1)[1].split('\n}', 1)[0]
    assert '.trade-split { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }' in block


def test_the_advanced_cards_go_three_across_from_1200px():
    css = read('static/style.css')
    block = css.split('@media (min-width: 1200px) {', 1)[1].split('\n}', 1)[0]
    assert '.adv-cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }' in block
    assert '.adv-cards { display: grid; grid-template-columns: minmax(0, 1fr);' in css


def test_the_internals_are_one_click_from_sell_and_nothing_is_buried_twice():
    """Stage 4 (the re-target of 'safety controls never hide behind a click'): the kill switch,
    trade limit, notifications, run queue and hygiene plan moved behind ONE Advanced tab. What the
    pin guards now is reachability + honesty of the layer, not that they sit below the panels:

      * #tt-advanced is a real tab in #tradeTabs, and #tp-advanced is the panel it controls;
      * every internal id lives inside #tp-advanced (asserted here and in test_trade_layout.py);
      * the kill switch and the trade limit are plain cards - the ONLY <details> in the layer is
        the hygiene plan (which was always an accordion);
      * the old always-visible ops strip under the panels is gone.
    """
    html = read('static/index.html')
    tabs = trade_section(html).split('<nav id="tradeTabs"', 1)[1].split('</nav>', 1)[0]
    assert 'id="tt-advanced"' in tabs and 'data-tp="tp-advanced"' in tabs
    adv = trade_section(html).split('id="tp-advanced"', 1)[1]
    for frag in ('id="limList"', 'id="killList"', 'id="notifyList"', 'id="killNote"',
                 'id="btnKill"', 'id="btnNotify"', 'id="runqList"', 'id="btnRunq"',
                 'id="hygieneList"', 'id="hygieneMeta"', 'id="btnHygiene"', 'id="hygieneAcc"'):
        assert frag in adv, frag
    assert adv.count('<details') == 1 and 'id="hygieneAcc"' in adv, \
        'the hygiene plan is the only disclosure in the layer'
    for cid, card in (('id="killList"', '<div class="card">'),
                      ('id="limList"', '<div class="card">'),
                      ('id="notifyList"', '<div class="card">')):
        assert '<summary' not in adv.split(cid, 1)[0].rsplit(card, 1)[1], cid
    after = trade_section(html).split('id="tp-history"', 1)[1]
    assert 'trade-ops' not in after and 'trade-ops' not in html, 'the ops strip left the page'


# ------------------------------------------------------------------ the row budget

def test_plan_held_and_run_queue_rows_are_in_the_dense_budget():
    css = read('static/style.css')
    assert '#view-trade .prow { padding: 6px 5px; font-size: 12.5px; line-height: 1.45; }' in css
    assert '#view-trade .heldline { padding: 6px 5px; font-size: 12px; line-height: 1.45; gap: 10px; }' in css
    # the run queue is five fixed columns (item / price / status / buyer / message) on one line:
    # 2026-09-27 layout pass - the inline chip + buyer + price blob became their own columns
    assert '.runrow { grid-template-columns: minmax(0, 1.5fr) 84px 104px minmax(0, 1.1fr) minmax(0, 1.6fr);' in css
    assert '.runwhisper { grid-column: auto; font-size: 11px; line-height: 1.35; }' in css
    assert '.runwhisper { grid-column: 1 / -1;' in css, 'the phone layout keeps the whisper on its own line'


def test_the_notes_column_keeps_its_width_budget_and_the_plan_keeps_six_columns():
    css = read('static/style.css')
    block = css.split('@media (min-width: 901px) {', 1)[1].split('\n}', 1)[0]
    # 2026-09-27 layout pass: the notes were capped at 240px and read as "b... 7... 0..."; the
    # item column now stops widening and the notes take the flexible share (>= 232px measured).
    assert '22px minmax(168px, 1fr) 44px 62px 74px minmax(232px, 1.35fr); gap: 8px;' in block
    js = read('static/app.js')
    for cell in ('class="dim"', 'class="l-name"', 'p-qty', 'p-price', 'p-est', 'p-note'):
        assert cell in js, cell


def test_card_heads_wrap_so_a_narrow_column_never_clips_a_button():
    css = read('static/style.css')
    head = css.split('#view-trade .card-head { padding: 10px 14px 6px; gap: 10px;', 1)[1].split('}', 1)[0]
    assert 'flex-wrap: wrap' in head


def test_phones_keep_the_single_column_layout():
    css = read('static/style.css')
    assert '.trade-split { display: grid; grid-template-columns: minmax(0, 1fr);' in css
    assert '.adv-cards { display: grid; grid-template-columns: minmax(0, 1fr);' in css, \
        'the Advanced band stacks below 1200px (the Advanced panel is in them too)'
    # <=560px: the plan grid keeps its own phone columns and the note is hidden by the 900px block
    assert '.plan-head, .prow { grid-template-columns: 18px minmax(0, 1fr) 30px 52px 62px; gap: 8px; }' in css


# ------------------------------------------------------------------ the hooks other tests pin

def test_every_trade_id_and_control_is_still_on_the_page():
    """Reachability, not placement: every id is asserted somewhere in index.html (the stage-1
    snapshot's 47 trade ids + view-trade + the stage-4 additions)."""
    html = read('static/index.html')
    for frag in ('id="planList"', 'id="heldList"', 'id="attnList"', 'id="hygieneList"',
                 'id="runqList"', 'id="killList"', 'id="notifyList"', 'id="limList"',
                 'id="planMeta"', 'id="heldMeta"', 'id="attnMeta"', 'id="hygieneMeta"',
                 'id="runqMeta"', 'id="killMeta"', 'id="notifyMeta"', 'id="limMeta"',
                 'id="btnPlan"', 'id="btnCycle"', 'id="btnWatch"', 'id="btnHygiene"',
                 'id="btnRunq"', 'id="btnKill"', 'id="btnNotify"', 'id="killNote"',
                 'id="tradeTabs"', 'id="tp-sell"', 'id="tp-buy"', 'id="tp-history"',
                 'id="tt-advanced"', 'id="tp-advanced"', 'id="postMode"'):
        assert frag in html, frag
