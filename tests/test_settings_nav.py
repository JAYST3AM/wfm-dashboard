"""Settings navigation (Jay, 2026-09-28): "Settings: one category at a time with a settings sidebar
(General, Trading, Appearance, Accounts, Notifications, Advanced)."

Source-level contracts for the layout the headless pass click-tested. `static/settings.html` no
longer stacks five cards: the page's own section nav (`.mainnav.subnav`, the one that already held
the Tools | Settings pills) IS the category list now, and exactly one category panel is in the flow
at a time. `/settings.html#trading` deep-links a category, General is the default, and an unknown
hash falls back to General - nothing lands blank.

Every card, row, control, Save button and id from the stacked layout travelled with its category,
so the ids are asserted *inside their panel*, not page-wide: a row cannot quietly move out of the
card whose Save button saves it. The Notifications category carries the one link row the stage plan
allows (the webhook surface lives on Trade) and no invented controls.

The Save buttons are pinned presence-and-handler only. This file never clicks one: a click posts
real config.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO, 'static')
NODE = shutil.which('node')

CATS = ['general', 'trading', 'appearance', 'accounts', 'notifications', 'advanced']

# category -> the ids its panel must still carry (the ids travel with the card, never drop)
PANEL_IDS = {
    'general': ['h-updates', 'btnSave-updates', 'list-updates', 'status-updates'],
    'trading': ['h-trading', 'btnSave-trading', 'list-trading', 'status-trading'],
    'appearance': ['h-appearance', 'btnSave-appearance', 'list-appearance', 'status-appearance'],
    'accounts': ['h-accounts', 'acctName', 'acctCreate', 'list-accounts', 'acctPlan',
                 'status-accounts'],
    'notifications': ['h-notifications', 'list-notifications', 'notifyLink'],
    'advanced': ['h-verbose', 'btnSave-verbose', 'list-verbose', 'status-verbose',
                 'advBtn', 'advPanel', 'btnSave-advanced', 'list-advanced', 'status-advanced',
                 'rawRows', 'advErr'],
}

PANEL_OPEN = re.compile(r'<div class="st-cat( hidden)?" id="cat-([a-z]+)" data-cat="[a-z]+">')


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


def nav_block(html):
    """The page's section nav - the category list itself."""
    return html.split('<nav class="mainnav subnav" id="settingsCats"', 1)[1].split('</nav>', 1)[0]


def panels(html):
    """{category: (is_hidden_in_the_shipped_markup, panel html)} for all six panels."""
    opens = list(PANEL_OPEN.finditer(html))
    out = {}
    for i, m in enumerate(opens):
        end = opens[i + 1].start() if i + 1 < len(opens) else html.index('</main>')
        out[m.group(2)] = (bool(m.group(1)), html[m.end():end])
    return out


# ------------------------------------------------------------------ the category list

def test_the_page_has_one_nav_and_it_is_the_category_list_in_order():
    html = read('settings.html')
    # one section nav, the same object that always lived here: still a .mainnav.subnav, still
    # inside .shellcol, and still carrying the Tools | Settings pills it shipped with
    assert html.count('<nav ') == 1, 'the category list replaces the stacked-card section nav'
    assert '<nav class="mainnav subnav" id="settingsCats"' in html
    assert html.index('class="shellcol"') < html.index('id="settingsCats"')
    nav = nav_block(html)
    assert re.findall(r'data-cat="([a-z]+)"', nav) == CATS
    assert 'href="/#tools" class="navpill"' in nav
    assert 'href="/settings.html" class="navpill active" aria-current="page"' in nav
    # the pill order in the nav is the panel order on the page
    assert list(panels(html)) == CATS
    # the six category pills are page-local (the shell's own cap on a page's .navpill hosts is
    # tests/test_app_shell.py's; here the two page pills stay the only .navpill on the page)
    assert html.count('class="navpill') == 2
    assert nav.count('class="st-catpill"') == len(CATS)


def test_exactly_one_category_panel_is_in_the_flow_at_a_time():
    html = read('settings.html')
    shown = [c for c, (hidden, _body) in panels(html).items() if not hidden]
    hidden = [c for c, (is_hidden, _body) in panels(html).items() if is_hidden]
    assert shown == ['general'], 'General is the default category'
    assert hidden == CATS[1:]
    # the switch is one class toggle per panel, driven off the CATS table
    js = read('settings.js')
    assert "const CATS = ['general', 'trading', 'appearance', 'accounts', 'notifications', 'advanced'];" in js
    assert 'const panel = document.getElementById(\'cat-\' + c);' in js
    assert "panel.classList.toggle('hidden', c !== on)" in js
    assert "nav.querySelectorAll('[data-cat]')" in js, 'the switch paints the pills it finds'
    assert '.st-cat.hidden { display: none; }' in html, 'the panel hide rule ships with the page'


def test_every_category_deep_links_and_general_is_the_default():
    html = read('settings.html')
    nav = nav_block(html)
    for cat in CATS:
        assert 'href="/settings.html#%s" class="st-catpill" data-cat="%s"' % (cat, cat) in nav, cat
    js = read('settings.js')
    # the hash parser takes the same shape the pills write (#cat, tolerant of ? and /)
    assert "String(location.hash || '').replace(/^#/, '').split('?')[0].split('/')[0]" in js
    assert 'return CATS.indexOf(raw) >= 0 ? raw : CATS[0];' in js
    assert "window.addEventListener('hashchange'" in js, 'Back/Forward repaint the category'
    assert 'initCats();' in js
    # the current category announces itself the way the collection section row does
    assert "p.classList.toggle('active', here)" in js
    assert "p.setAttribute('aria-current', 'page')" in js


@pytest.mark.skipif(NODE is None, reason='node is not installed - the source pins still run')
def test_the_hash_maps_to_a_category_and_junk_falls_back_to_general():
    js = read('settings.js')
    cats = re.search(r'const CATS = \[[^\]]+\];', js)
    assert cats, 'the CATS table moved - update this test first'
    body = js.split('function catFromHash() {', 1)[1].split('\n}', 1)[0]
    hashes = ['', '#', '#general', '#trading', '#appearance', '#accounts', '#notifications',
              '#advanced', '#nope', '#trading?x=1', '#tools']
    script = ("const location = { hash: '' };\n" + cats.group(0) +
              '\nfunction catFromHash() {' + body + '}\n'
              'const out = [];\n'
              'for (const h of ' + json.dumps(hashes) + ') { location.hash = h; out.push(catFromHash()); }\n'
              'console.log(JSON.stringify(out));\n')
    proc = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert json.loads(proc.stdout) == ['general', 'general', 'general', 'trading', 'appearance',
                                       'accounts', 'notifications', 'advanced', 'general',
                                       'trading', 'general']


# ------------------------------------------------------------------ nothing left behind

def test_every_panel_keeps_the_ids_its_card_had():
    got = panels(read('settings.html'))
    assert set(got) == set(CATS)
    missing = []
    for cat, ids in PANEL_IDS.items():
        body = got[cat][1]
        for i in ids:
            if 'id="%s"' % i not in body:
                missing.append((cat, i))
    assert not missing, 'ids left their panel: %s' % missing
    # and they exist exactly once on the page (no duplicated control)
    html = read('settings.html')
    for ids in PANEL_IDS.values():
        for i in ids:
            assert html.count('id="%s"' % i) == 1, i


def test_save_buttons_are_still_wired_to_their_groups():
    html = read('settings.html')
    js = read('settings.js')
    got = panels(html)
    # the five save groups settings.js knows (GROUPS + ADV_GROUP), each with its button in its panel
    groups = re.findall(r"\n    id: '([a-z]+)', title:", js)
    assert groups == ['verbose', 'trading', 'appearance', 'updates'], groups
    assert "\n  id: 'advanced', title:" in js
    for gid in groups + ['advanced']:
        assert 'id="btnSave-%s"' % gid in html, gid
        panel = {'verbose': 'advanced', 'trading': 'trading', 'appearance': 'appearance',
                 'updates': 'general', 'advanced': 'advanced'}[gid]
        assert 'id="btnSave-%s"' % gid in got[panel][1], (gid, panel)
    # the handler itself is unchanged: SAVE_GROUPS -> saveGroup -> POST the changed pairs only
    assert "document.getElementById('btnSave-' + g.id)" in js
    assert "btn.addEventListener('click', () => saveGroup(g))" in js
    assert 'SAVE_GROUPS.forEach(g => {' in js
    assert "await fetch(url, {" in js and "body: JSON.stringify({ pairs })" in js


def test_notifications_is_a_pointer_not_invented_controls():
    body = panels(read('settings.html'))['notifications'][1]
    assert 'id="notifyLink"' in body and 'href="/#trade"' in body, \
        'the webhook surface lives on Trade - this category links to it'
    for tag in ('<input', '<button', '<select', '<textarea', 'data-k'):
        assert tag not in body, 'the Notifications category must not invent a control: ' + tag
    assert 'id="list-notifications"' in body, 'the category keeps its row list hook'


def test_the_safety_wording_survives_the_category_split():
    """The Live / Not-live gate is data (dry_run) and copy (Not live) at once - the split must not
    have touched either, and the JSON/raw-config surface still renders from the schemas."""
    js = read('settings.js')
    assert "dry ? 'Not live' : 'Live'" in js
    assert 'window.wfmAdv.set(ctl.checked)' in js, 'the Advanced switch still applies immediately'
    assert "el('div', 'cfg-help' + (meta.hint ? ' explain' : ''))" in js
    adv = panels(read('settings.html'))['advanced'][1]
    for hook in ('id="advBtn"', 'id="advPanel"', 'id="rawRows"', 'id="advErr"',
                 'id="list-advanced"', 'id="status-advanced"', 'id="btnSave-advanced"'):
        assert hook in adv, hook
    assert 'function renderRaw()' in js and "document.getElementById('rawRows')" in js
    assert 'function initAccordion()' in js and 'initAccordion();' in js
