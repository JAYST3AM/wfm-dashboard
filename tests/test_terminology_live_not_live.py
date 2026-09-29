"""Terminology: posting is "Live" / "Not live" — never "Dry run" (Jay, 2026-09-26).

Jay: *"change from terminology of Dry Run, to Live / Not Live."* The wording people read must say
Live / Not live; the `dry_run` key, its lock and every data contract are unchanged (that is what
makes the gate load-bearing). These tests pin the wording so it cannot drift back.
"""
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# scripts/trader/ is private and gitignored, so a clean checkout (CI) has no such files. The
# wording inside it is still pinned - but only where the files exist. Without this the three tests
# below fail on every CI run, which is how the suite stayed red without anyone seeing it: the data/
# check above them failed first and pytest never started.
PRIVATE = os.path.join(ROOT, 'scripts', 'trader')
needs_private = pytest.mark.skipif(not os.path.isdir(PRIVATE),
                                   reason='scripts/trader is private and absent from this checkout')

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


def test_live_wording_survives_the_retired_trader_cards():
    """2026-09-27: the Trade 'Engine status' card was retired with the other internals, so the
    wording rule now stands on the surfaces that still show the posting state."""
    js = read('static/app.js')
    assert 'renderEngine' not in js and "line('Posting mode'" not in js, 'retired cards stay retired'
    assert 'killMeta' in js, 'the kill-switch card is still on the Trade view'
    assert "dry ? 'Not live' : 'Live'" in read('static/settings.js'), 'settings still states the gate'
    assert 'Not live' in read('static/home.js'), 'home still says it plainly'


def test_no_raw_plan_mode_can_reach_the_ui():
    """Plans still store mode:'dry-run' (data). The flipper-internals card was the only surface
    that printed a mode, so neither the renderer nor the mapper may come back without a decision."""
    js = read('static/app.js')
    assert 'function renderFlipper' not in js
    assert 'function modeText' not in js and 'modeText(' not in js
    assert 'flipPlanList' not in js
    for s in visible_strings(js):
        assert not re.search(r'dry[ -]?run', s, re.I), s


def test_settings_card_shows_not_live():
    """2026-09-27 copy diet: the posting row is the status pill alone (label + status). The
    wording pinned is still the visible 'Not live'; the explainer that sat under it is gone and
    must not come back."""
    js = read('static/settings.js')
    assert "dry ? 'Not live' : 'Live'" in js
    assert 'nothing is posted until' not in js
    assert 'not editable here' not in js


def test_home_card_shows_not_live():
    js = read('static/home.js')
    assert "'Not live - plan only'" in js          # copy diet 2026-09-27: one short phrase, no sentence


@needs_private
def test_guardrail_help_uses_the_new_wording():
    py = read('scripts/trader/settings.py')
    assert 'Live posting gate: not live = nothing is posted' in py
    assert 'Locked to not live until Jay approves live posting.' in py


@needs_private
def test_lock_refusal_still_explains_itself():
    """The gate itself is untouched: turning it off is still refused with an approval message."""
    py = read('scripts/trader/settings.py')
    assert 'needs Jay' in py and 'explicit approval first' in py
    assert len(re.findall(r'locked', py)) >= 3


@needs_private
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
