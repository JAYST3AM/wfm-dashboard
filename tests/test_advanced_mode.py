"""The Advanced switch (Jay 2026-09-26).

  "take out the explanations by adding a button in settings, that says advanced, so the extra
   explanations can appear if advanced active."

One dashboard knob (config.py `advanced`, default false) governs every extra explanation: the
Trade card's posting note, the kill-switch footnote, the settings page intro and per-row hints.
static/adv.js reads the knob and sets <html data-adv="on|off">; style.css hides .explain unless it
is on. Tests below pin the knob, the plumbing, the CSS rule and the wrappers.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


def test_knob_exists_and_defaults_off():
    out = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'config.py'), '--schema'],
                         capture_output=True, text=True, cwd=ROOT, timeout=60)
    rows = json.loads(out.stdout or '[]')
    row = [r for r in rows if r['key'] == 'advanced'][0]
    assert row['type'] == 'bool'
    assert row['default'] is False, 'the dashboard ships clean, not verbose'
    assert 'adv.js' in row['consumed_by'], 'the schema names its consumer'
    assert row['help']


def test_adv_js_reads_the_knob_and_sets_the_dataset():
    js = read('static/adv.js')
    assert "fetch('/api/config')" in js
    assert 'values.advanced' in js, 'it reads the knob the server serves'
    assert "document.documentElement.dataset.adv" in js
    assert "on ? 'on' : 'off'" in js
    assert 'window.wfmAdv' in js, 'the page can flip it live'
    assert 'wfm-adv' in js, 'pages get an event to re-render'
    assert 'apply(false)' in js, 'clean until the config answers'


def test_every_page_loads_adv_js_first():
    for page in ('index.html', 'settings.html', 'collection.html', 'cards.html', 'item.html'):
        html = read('static/' + page)
        assert '/adv.js' in html, page + ' must load the switch'
        assert html.index('/adv.js') < html.index('/sfx.js'), page + ' loads it before the page scripts'


def test_css_hides_explanations_until_the_switch_is_on():
    css = read('static/style.css')
    assert '.explain { display: none !important; }' in css
    assert 'html[data-adv="on"] .explain { display: revert !important; }' in css


def test_explanations_stay_behind_the_switch_where_they_remain():
    """2026-09-27: the trader internals (engine status / detector / flipper / raw output) were
    retired, taking the Trade card's posting note with them. The switch still governs every
    explanation that is left - the kill-switch footnote, the settings intro and the row hints."""
    js = read('static/app.js')
    assert "line('Posting mode'" not in js, 'the retired posting row must not come back'
    assert 'class="dim small explain"' in js, 'the kill-switch footnote is still an explanation'
    assert 'Advanced trading' not in read('static/index.html'), 'the accordion is retired'
    settings = read('static/settings.js')
    assert "el('div', 'cfg-help' + (meta.hint ? ' explain' : ''))" in settings, 'row hints'
    assert '<p class="st-lead explain">' in read('static/settings.html'), 'the page intro'


def test_settings_group_flips_it_live():
    js = read('static/settings.js')
    assert "id: 'verbose', title: 'Advanced'" in js, 'the Advanced group is its own group'
    assert "{ key: 'advanced', label: 'Advanced', apply: 1," in js
    assert 'window.wfmAdv.set(ctl.checked)' in js, 'toggling applies immediately, Save persists'
    assert "el('div', 'cfg-help' + (meta.hint ? ' explain' : ''))" in js, 'row hints are explanations'
    html = read('static/settings.html')
    assert '<p class="st-lead explain">' in html, 'the page intro is an explanation'


def test_no_stale_dry_run_wording_in_user_visible_copy():
    for rel in ('static/app.js', 'static/settings.js', 'static/home.js', 'static/drawer.js',
                'static/item.js', 'static/collection.js', 'server.py'):
        src = read(rel)
        # drop block comments and line comments first - only rendered copy matters here
        code = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
        code = re.sub(r'^\s*[#].*$', '', code, flags=re.M)
        code = re.sub(r'//.*$', '', code, flags=re.M)
        for line in code.splitlines():
            if re.search(r'dry[ -]?run', line, re.I):
                raise AssertionError(rel + ': user-visible dry-run wording -> ' + line.strip()[:90])
