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


# ------------------------------------------------------------------ condensed rows

def test_today_rows_are_two_lines_with_detail_on_hover():
    js = read('static/home.js')
    assert 'const l2 = [ownLineShort(r), whyLineShort(r)].filter(Boolean).join' in js
    assert "const tip = [tipText(r), ownLine(r), whyLine(r)].filter(Boolean).join('\\n\\n')" in js
    assert 'ownLineShort' in js and 'whyLineShort' in js
    assert 'window ' in js and ' sold / 48h' in js


def test_today_headline_is_one_line_plus_a_breakdown():
    js = read('static/home.js')
    assert "add(lead, 'span', 'h-pot-n', plat(potential) + ' potential')" in js
    assert "bits.push(sells.length + ' sell')" in js
    assert "' to burn for ducats'" not in js          # the long labels are gone
    assert 'Potential platinum: ' not in js


def test_fewer_straight_away_recommendations():
    js = read('static/home.js')
    assert 'const TOP_SELL = 5;' in js


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
    assert "const nice = step >= 200 ? Math.round(v / 50) * 50 : Math.round(v);" in js


def test_long_spans_label_the_year():
    js = read('static/chart.js')
    assert "const multiYear = (range === 'all' || (x1 - x0) > 120 * 86400);" in js
    assert "String(d.getFullYear()).slice(2)" in js


def test_axis_labels_are_readable_and_cannot_clip():
    js = read('static/chart.js')
    assert "n.toLocaleString('en-AU')" in js                      # 9,150p not 9150p
    assert "ctx.textAlign = i === 0 ? 'left' : (i === 4 ? 'right' : 'center');" in js
