"""Home layout (Jay 2026-09-26, restyled 2026-09-28).

The clean pass kept every id and every card and moved the column into the order the approved V1
mockup uses (design/mockups/desktop-directions.html): page header row, hero number, the alert
surface, one labelled KPI grid, the short sell-next list, then the chart beside it and the three
lists (news / today / recent) sharing the last band.

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

def test_the_chart_comes_before_the_three_lists_on_home():
    html = read('static/index.html')
    home = html.split('id="view-home"', 1)[1].split('</section>', 1)[0]
    for later in ('id="newsCard"', 'id="todayCard"', 'id="recentCard"'):
        assert home.index('id="chartCard"') < home.index(later), later
    # the clean pass: the page header + hero lead, the KPI grid sits above the chart, and every
    # section the old order shipped is still in the column
    for frag in ('id="homeHead"', 'id="heroCard"', 'id="platinumNow"', 'id="alertsCard"',
                 'id="kpiCard"', 'id="homeSellNext"'):
        assert frag in home, frag
    assert home.index('id="homeHead"') < home.index('id="heroCard"') < home.index('id="alertsCard"')
    assert home.index('id="alertsCard"') < home.index('id="kpiCard"') < home.index('id="homeSellNext"')
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


def test_rows_and_cards_carry_one_roomy_anatomy():
    """The clean pass replaced the 3px rows with one anatomy: 9px padding, name + sub on the left
    and the value on the right, a 1px separator between the rows, a 2px gap above a sub line."""
    css = read('static/home.css')
    assert '.h-row {\n  display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px;\n' \
           '  padding: 9px 6px; font-size: 12.5px;' in css            # one row, name above the sub
    assert 'align-items: baseline; padding: 9px 6px;' in css          # .newsrow - date / title / source
    assert 'gap: 10px; align-items: center; padding: 9px 6px; font-size: 12.5px;' in css   # .h-ev
    assert '.h-l1 { display: grid; grid-template-columns: minmax(0, 1fr) max-content;' in css  # name | value
    assert 'max-width: 560px' in css                                  # header action cluster wraps, no overflow


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


# ------------------------------------------------------------------ the honest default range

def test_the_chart_opens_on_a_clean_month_and_never_draws_through_a_gap():
    """Jay 2026-09-28: the widest range flattened the line (175 snapshots since May 2024 with
    month-long holes), so the Home card opens on 30d. Every range button (24h / 7d / 30d / All)
    still overrides it, a stored choice still wins, and the renderer breaks the line where the
    collected data has a real gap instead of drawing a straight line through the hole."""
    chart = read('static/chart.js')
    assert "range: '30d', style: 'area', palette: 'accent', gapS: 172800," in chart   # the Home default
    assert "var pref = prefStore(key, { style: opts.style || 'area'," in chart        # saved choice wins
    assert "range: opts.range || 'all' });" in chart
    assert 'var gapS = Number(opts.gapS) || 0;' in chart                              # opt-in, other charts unchanged
    assert 'var runs = (gapS > 0) ? splitRuns(ps, gapS) : [ps];' in chart             # the line stops at a gap
    assert 'var lp = ps[ps.length - 1]' in chart                                      # the end dot follows the last run
