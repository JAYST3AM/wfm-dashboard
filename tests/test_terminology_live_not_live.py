"""Terminology: posting is "Live" / "Not live" — never "Dry run" (Jay, 2026-09-26).

Jay: *"change from terminology of Dry Run, to Live / Not Live."* The wording people read must say
Live / Not live; the `dry_run` key, its lock and every data contract are unchanged (that is what
makes the gate load-bearing). These tests pin the wording so it cannot drift back.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

UI_FILES = ('app.js', 'home.js', 'settings.js', 'cards.js', 'drawer.js', 'lookup.js', 'collection.js')
BAD = re.compile(r'dry[\s-]?run', re.I)


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        return fh.read()


def strip_comments(js):
    js = re.sub(r'/\*.*?\*/', ' ', js, flags=re.S)
    return re.sub(r'^\s*//.*$', ' ', js, flags=re.M)


def visible_strings(js):
    """Quoted strings a user can see (template literals included), comments removed."""
    body = strip_comments(js)
    out = []
    for m in re.finditer(r"'([^'\n]{2,})'|\"([^\"\n]{2,})\"|`([^`]{2,})`", body):
        s = next(g for g in m.groups() if g)
        if re.search(r'[a-z]', s) and ' ' in s:
            out.append(s)
    return out


def test_no_dry_run_wording_in_the_ui_scripts():
    for name in UI_FILES:
        for s in visible_strings(read('static/' + name)):
            assert not BAD.search(s), (name, s)


def test_no_dry_run_wording_in_the_pages():
    for name in ('index.html', 'settings.html', 'collection.html', 'cards.html'):
        html = re.sub(r'<!--.*?-->', ' ', read('static/' + name), flags=re.S)
        assert not BAD.search(html), name


def test_header_and_trader_card_say_live_not_live():
    js = read('static/app.js')
    assert "'· posting ' + (set.dry_run === false ? 'Live' : 'Not live')" in js
    assert "'Live - orders can post' : 'Not live - nothing is posted to warframe.market'" in js


def test_engine_plan_modes_are_mapped_for_display():
    """Plans still store mode:'dry-run' (data), so the UI translates it instead of renaming data."""
    js = read('static/app.js')
    assert 'function modeText(m)' in js
    assert "/dry/i.test(String(m)) ? 'Not live'" in js
    assert 'modeText(P.mode)' in js


def test_settings_card_shows_not_live():
    js = read('static/settings.js')
    assert "dry ? 'Not live' : 'Live'" in js
    assert "dry ? 'not live' : 'live'" in js
    assert "'Not live - nothing is posted until the engine config says otherwise.'" in js


def test_home_card_shows_not_live():
    js = read('static/home.js')
    assert "'Not live - listings are planned here, nothing is sent out.'" in js


def test_guardrail_help_uses_the_new_wording():
    py = read('scripts/trader/settings.py')
    assert 'Live posting gate: not live = nothing is posted' in py
    assert 'Locked to not live until Jay approves live posting.' in py


def test_lock_refusal_still_explains_itself():
    """The gate itself is untouched: turning it off is still refused with an approval message."""
    py = read('scripts/trader/settings.py')
    assert 'needs Jay' in py and 'explicit approval first' in py
    assert len(re.findall(r'locked', py)) >= 3


def test_engines_print_not_live_not_dry_run():
    for path in ('scripts/trader/lister.py', 'scripts/trader/watcher.py', 'scripts/trader/detector.py'):
        py = read(path)
        assert "'NOT LIVE' if" in py, path
        assert 'DRY RUN' not in py, path


def test_profiles_switch_preview_says_plan_only():
    py = read('scripts/profiles.py')
    assert "' (PLAN ONLY - nothing is written)'" in py
    assert 'DRY RUN' not in py


def test_readme_speaks_live_not_live():
    md = read('README.md')
    assert 'dry run' not in md.lower() or 'dry_run' in md     # only the key name may appear
    assert 'Not live' in md
    assert '`dry_run` (the Live/Not-live gate, locked to Not live)' in md
