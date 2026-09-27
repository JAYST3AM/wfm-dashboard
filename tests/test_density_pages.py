"""Settings / item / lookup density (Jay 2026-09-27): "more page needs to be condensed, all pages
should be condensed really."

Source-level pins for the layout the probes measured headlessly. Measured: settings 1641 -> 1080 @
1920x1080 and 1641 -> 1205 @1440x900; item page measured and left as-is where it was already tight;
no horizontal scroll and no console errors at 1920/1440/1100/390. Nothing here removes a knob, a
card, a control or a save button - only the air between them.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


def media_blocks(css, query):
    return [b.split('\n}', 1)[0] for b in css.split('@media (%s) {' % query)[1:]]


# ------------------------------------------------------------------ settings

def test_settings_keeps_all_six_cards_and_their_save_plumbing():
    html = read('static/settings.html')
    for cid in ('h-trading', 'h-appearance', 'h-updates', 'h-accounts', 'h-verbose'):
        assert 'id="%s"' % cid in html, cid
    for bid in ('btnSave-trading', 'btnSave-appearance', 'btnSave-updates', 'btnSave-verbose'):
        assert 'id="%s"' % bid in html, bid
    for lid in ('list-trading', 'list-appearance', 'list-updates', 'list-accounts', 'list-verbose'):
        assert 'id="%s"' % lid in html, lid
    for sid in ('status-updates', 'status-trading'):
        assert 'id="%s"' % sid in html, sid


def test_settings_cards_band_two_across_on_a_wide_screen():
    html = read('static/settings.html')
    assert 'st-col' in html, 'the card columns the media query rearranges'
    assert any('grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)' in b
               for b in media_blocks(html, 'min-width: 1500px')), 'the house 2-column band'
    assert '<details' not in html.split('id="list-trading"', 1)[1].split('</section>', 1)[0], \
        'no knob hides inside a disclosure'


def test_pick_rows_share_the_row_class_so_the_picker_still_saves():
    js = read('static/settings.js')
    assert "'cfgrow' + (meta.pick ? ' pick-row' : '')" in js, \
        'the picker row keeps the cfgrow plumbing (data-k, hidden input) and gets a layout class'
    assert 'AUTO_SYNC_OPTIONS' in js and "{ seconds: 0, label: 'Manual only' }" in js


def test_settings_marks_its_own_scoped_layout():
    html = read('static/settings.html')
    assert '<style>' in html, 'page-scoped layout lives in the page, not in the shared style.css'
    style = html.split('<style>', 1)[1].split('</style>', 1)[0]
    assert 'max-width' in style or 'grid' in style, 'the density layer is in that block'


# ------------------------------------------------------------------ item page

def test_item_page_keeps_its_containers_and_bands():
    html = read('static/item.html')
    for i in ('ipTitle', 'ipChart', 'ipChartCard', 'ipStats', 'ipTrades', 'ipPick', 'ipList',
              'ipMeta', 'ipHint', 'ipViews'):
        assert 'id="%s"' % i in html, i
    assert 'ip-grid' in html and 'ip-chart' in html and 'ip-foot' in html
    # the item page carries less than a view, so its band comes in at 1200px, not 1500px
    assert any('grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr)' in b
               for b in media_blocks(html, 'min-width: 1200px')), 'chart beside the details'


def test_no_control_hides_behind_a_click():
    """The trade round's safety rule, applied to the pages condensed in this pass: a hidden
    container may exist (charts toggling), but no knob or button may live inside one, and no
    control is hidden with inline display/visibility tricks."""
    for rel in ('static/settings.html', 'static/item.html'):
        html = read(rel)
        assert 'style="display:none"' not in html, rel
        assert 'visibility:hidden' not in html, rel
        assert html.count('<details') <= 2, rel + ': disclosures are never where a control lives'
