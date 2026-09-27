"""Home layout (Jay 2026-09-26): chart on top, news under it with Recent activity beside it, and the
"worth doing" card condensed into a tall, narrow column under the news.

  "this you have ### worth doing card, needs to be condensed, and virtically skewed because its
   taking up way too much realestate ... the platinum graph should be on top ... the newsletter
   should be under that, also condensed ... the recent activity can sit next to that, condensed as
   well. then the worth doing card may sit under the newsletter."
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ order

def test_chart_is_the_first_card_on_home():
    html = read('static/index.html')
    home = html.split('id="view-home"', 1)[1].split('</section>', 1)[0]
    for later in ('id="newsCard"', 'id="todayCard"', 'id="recentCard"'):
        assert home.index('id="chartCard"') < home.index(later), later
    # the KPI strip stays above the chart (it is the header summary, not a card)
    assert home.index('id="kpis"') < home.index('id="chartCard"')


def test_news_comes_before_recommendations_in_the_same_column():
    html = read('static/index.html')
    home = html.split('id="view-homs"'.replace('homs', 'home'), 1)[1].split('</section>', 1)[0]
    left = home.split('<div class="h-col">', 1)[1]
    assert left.index('id="newsCard"') < left.index('id="todayCard"')   # worth doing sits under news
    assert home.count('<div class="h-col">') == 2
    assert home.index('id="newsCard"') < home.index('id="recentCard"')  # recent is the other column


def test_home_grid_is_two_columns_and_collapses_on_small_screens():
    css = read('static/home.css')
    block = css.split('.h-cols {', 1)[1]
    assert 'grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)' in block
    assert '@media (max-width: 1040px)' in css
    assert '.h-col {' in css


# ------------------------------------------------------------------ the Today card
# 2026-09-27: the Today card turned into the progress tracker (scripts/progress.py), so these
# pin its label+value rows and the sessions list instead of the advisor rows it replaced.

def test_today_rows_are_label_and_value_with_detail_on_hover():
    js = read('static/home.js')
    assert "const l1 = add(row, 'div', 'h-l1')" in js
    assert "add(l1, 'span', 'h-name', label)" in js
    assert "const cell = add(l1, 'span', 'h-act')" in js
    assert "if (tip) row.setAttribute('title', clip(tip, 220))" in js


def test_today_tracks_the_progress_store_and_never_invents_a_number():
    js = read('static/home.js')
    assert "get('/api/feature/progress')" in js
    assert 'renderToday(today, d.progress)' in js
    assert "const UNKNOWN = '-'" in js                     # a null reading renders '-', not 0
    for field in ('plat_delta', 'credits_delta', 'items_added', 'items_removed',
                  'materials_gained', 'plat_this_week', 'trades_this_week', 'hours_this_week'):
        assert field in js, field
    assert 'noteFor(notes' in js                           # the store's own reason in the title=


def test_today_lists_five_sessions_on_one_line_each():
    js = read('static/home.js')
    assert 'const SESSIONS_SHOWN = 5;' in js
    assert 'const sessionRow = (s) =>' in js
    assert "s.current ? ['live', 'upl'] : null" in js      # live marker for a running session
    assert 'rangeTxt(s.start_ts, s.end_ts)' in js          # short date/time range
    assert "add(row, 'span', 'h-num', sm ? dur(sm) : '')" in js


def test_today_stays_condensed():
    js = read('static/home.js')
    assert 'const MATERIALS_SHOWN = 3;' in js
    assert 'const SESSIONS_SHOWN = 5;' in js


def test_today_degrades_when_the_progress_store_is_missing():
    js = read('static/home.js')
    assert "'Not available yet'" in js


def test_news_card_is_four_rows():
    assert '(n.items || []).slice(0, 4)' in read('static/app.js')


def test_rows_and_cards_are_tightened_in_css():
    css = read('static/home.css')
    assert '.h-row { padding: 5px 2px; gap: 0; }' in css
    assert 'max-width: 560px' in css                  # header action cluster wraps, no overflow
    assert '.h-cols .newsrow { padding: 6px 2px; }' in css


# ------------------------------------------------------------------ chart axis honesty

def test_platinum_axis_never_shows_a_negative_tick():
    js = read('static/chart.js')
    assert 'y0 = Math.max(0, y0 - padY)' in js
    assert "for (var v = Math.ceil(S.y0 / step) * step; v <= S.y1; v += step)" in js  # gridlines start at y0 >= 0
    assert "niceStep" in js                                                          # round gridline steps


def test_long_spans_label_the_year():
    js = read('static/chart.js')
    assert "if (spanS <= 120 * 86400) return d.toLocaleDateString([], { month: 'short', day: 'numeric' });" in js
    assert "String(d.getFullYear()).slice(2)" in js


def test_axis_labels_are_readable_and_cannot_clip():
    js = read('static/chart.js')
    assert "Math.round(v).toLocaleString('en-AU')" in js           # 9,150p not 9150p
    assert "ctx.textAlign = i === 0 ? 'left' : (i === nT - 1 ? 'right' : 'center');" in js  # end ticks anchor inward
