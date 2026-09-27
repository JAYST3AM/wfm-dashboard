"""Trade view density (Jay 2026-09-27): "trade page needs to be condensed to fit the information
on there better."

Source-level pins for the layout the QA probe measures headlessly (qa_trade_density.js):
the plan table and the held-back list share one row from 1500px, the three short cards go
3-across from 1200px, every data row stays inside its <=28px budget, and every id/control other
tests and the probe hook onto is still on the page. Nothing here removes a row, a column or a
button - only the air between them.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ the sideways layouts

def test_plan_and_held_back_share_a_row_from_1500px():
    css = read('static/style.css')
    split = '.trade-split { display: grid; grid-template-columns: minmax(0, 1fr);'
    assert split in css, 'single column is the default'
    block = css.split('@media (min-width: 1500px) {', 1)[1].split('\n}', 1)[0]
    assert '.trade-split { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }' in block


def test_the_three_short_cards_go_three_across_from_1200px():
    css = read('static/style.css')
    block = css.split('@media (min-width: 1200px) {', 1)[1].split('\n}', 1)[0]
    assert '.trade-ops { grid-template-columns: repeat(3, minmax(0, 1fr)); }' in block
    assert '.trade-ops { display: grid; grid-template-columns: minmax(0, 1fr);' in css


def test_kill_switch_run_queue_and_notifications_stay_plain_cards():
    """Safety controls never hide behind a click: they are cards, not accordions."""
    html = read('static/index.html')
    ops = html.split('<div class="trade-ops">', 1)[1].split('Run queue - best buyers', 1)[0]
    for frag in ('id="limList"', 'id="killList"', 'id="notifyList"', 'id="killNote"',
                 'id="btnKill"', 'id="btnNotify"'):
        assert frag in ops, frag
    assert '<summary' not in ops, 'no safety control sits in a <details>'
    after = html.split('Run queue - best buyers', 1)[1]
    for frag in ('id="runqList"', 'id="btnRunq"'):
        assert frag in after, frag
    assert '<summary' not in after.split('</section>', 1)[0], 'the run queue is a plain card'


# ------------------------------------------------------------------ the row budget

def test_plan_held_and_run_queue_rows_are_in_the_dense_budget():
    css = read('static/style.css')
    assert '#view-trade .prow { padding: 4px 2px; font-size: 12px; line-height: 1.35; }' in css
    assert '#view-trade .heldline { padding: 3px 2px; font-size: 11.5px; line-height: 1.35; gap: 8px; }' in css
    # one line per run-queue row (item+price, buyer, whisper); the phones block reflows it
    assert '.runrow { grid-template-columns: minmax(0, 1.15fr) max-content minmax(0, 1fr);' in css
    assert '.runwhisper { grid-column: auto; font-size: 11px; line-height: 1.35; }' in css
    assert '.runwhisper { grid-column: 1 / -1;' in css, 'the phone layout keeps the whisper on its own line'


def test_the_notes_column_is_capped_and_the_plan_keeps_six_columns():
    css = read('static/style.css')
    block = css.split('@media (min-width: 901px) {', 1)[1].split('\n}', 1)[0]
    assert '22px minmax(120px, 1fr) 44px 62px 74px minmax(84px, 240px); gap: 8px;' in block
    js = read('static/app.js')
    for cell in ('class="dim"', 'class="l-name"', 'p-qty', 'p-price', 'p-est', 'p-note'):
        assert cell in js, cell


def test_card_heads_wrap_so_a_narrow_column_never_clips_a_button():
    css = read('static/style.css')
    head = css.split('#view-trade .card-head { padding: 6px 12px 0; gap: 8px;', 1)[1].split('}', 1)[0]
    assert 'flex-wrap: wrap' in head


def test_phones_keep_the_single_column_layout():
    css = read('static/style.css')
    assert '.trade-split { display: grid; grid-template-columns: minmax(0, 1fr);' in css
    assert '.trade-ops { display: grid; grid-template-columns: minmax(0, 1fr);' in css
    # <=560px: the plan grid keeps its own phone columns and the note is hidden by the 900px block
    assert '.plan-head, .prow { grid-template-columns: 18px minmax(0, 1fr) 30px 52px 62px; gap: 8px; }' in css


# ------------------------------------------------------------------ the hooks other tests pin

def test_every_trade_id_and_control_is_still_on_the_page():
    html = read('static/index.html')
    trade = html.split('id="view-trade"', 1)[1].split('</section>', 1)[0]
    for frag in ('id="planList"', 'id="heldList"', 'id="attnList"', 'id="hygieneList"',
                 'id="runqList"', 'id="killList"', 'id="notifyList"', 'id="limList"',
                 'id="planMeta"', 'id="heldMeta"', 'id="attnMeta"', 'id="hygieneMeta"',
                 'id="runqMeta"', 'id="killMeta"', 'id="notifyMeta"', 'id="limMeta"',
                 'id="btnPlan"', 'id="btnCycle"', 'id="btnWatch"', 'id="btnHygiene"',
                 'id="btnRunq"', 'id="btnKill"', 'id="btnNotify"', 'id="killNote"',
                 'id="tradeTabs"', 'id="tp-sell"', 'id="tp-buy"', 'id="tp-history"'):
        assert frag in trade, frag
