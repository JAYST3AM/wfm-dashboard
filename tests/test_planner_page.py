"""The build planner page (Phase 2) - static contract tests.

design/build-planner/phase2-ui-spec.md freezes this page: the routes and payload shapes
(tests/test_planner_api.py drives those over a real socket), the ids its panels bind to, planner
storage v1 (`wfm.planner.v1`), and the ONE rule the page keeps - it owns no Warframe math. Slots,
mods, capacity, stats, traces, refusals and validation all arrive from /api/planner/*, which runs
the Phase 1 engine in builds/; the page formats what the engine answered and diffs two engine
answers it was handed (both runs are real - see /preview).

These are source-level contracts on the shipped files, the way tests/test_app_shell.py and
tests/test_ia_reachability.py pin the shell: an id cannot be renamed out from under a panel, the
storage key cannot drift from the version the server reports, and a calculation cannot sneak into
the UI. The page itself is served by the real server (booted here the way tests/test_planner_api.py
boots it), so "the page ships and declares itself" is measured, not assumed.

The page's two panel scripts (planner-library.js, planner-stats.js) land with their panels -
planner.html already asks for both - so every scan below runs over the scripts that exist and
says so; planner.js is the page and must always be there.
"""
import importlib.util
import json
import os
import re
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import REPO, read_static, shell_decl

STATIC = os.path.join(REPO, 'static')
SPEC = os.path.join(REPO, 'design', 'build-planner', 'phase2-ui-spec.md')
ICONS_PY = os.path.join(REPO, 'tools', 'build_icons.py')

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import ingest  # noqa: E402
from test_builds_engine import (FIXTURE_EQUIPMENT, FIXTURE_MODS,  # noqa: E402
                                _mod_row)

SCRIPTS = ('planner.js', 'planner-library.js', 'planner-stats.js')


# ------------------------------------------------------------------ the scripts themselves

def scripts():
    """[(name, text)] for the page scripts that ship today.

    planner-library.js and planner-stats.js are skipped while they are absent (they belong to the
    library and stat panels; planner.html already loads them), so each contract below covers the
    files that exist instead of failing on a panel that has not landed. planner.js is the page.
    """
    out = [(name, read_static(name)) for name in SCRIPTS
           if os.path.isfile(os.path.join(STATIC, name))]
    assert out and out[0][0] == 'planner.js', 'static/planner.js is the page and must exist'
    return out


def scrubbed(text):
    """A script with its comments blanked out, line numbers kept (so a failure message points at
    the real line). The file headers talk about drain and capacity; a comment cannot compute."""
    text = re.sub(r'/\*.*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def read_spec():
    with open(SPEC, encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ the server on a real socket

@pytest.fixture(scope='session')
def db_file(tmp_path_factory):
    """One ingested fixture database on disk, built through the real ingest path - the same
    fixture tests/test_planner_api.py uses, so the page's storage version can be read from the
    server that answers it instead of being copied into this file as a literal."""
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'planner-page-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src) for row in FIXTURE_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    db = ingest.build_database(mods, equipment, {'generated_iso': 'planner-page-test',
                                                 'game_version': 'planner-page-test'})
    out = tmp_path_factory.mktemp('planner_page_db') / 'build_data.json'
    out.write_text(json.dumps(db, indent=1, sort_keys=True), encoding='utf-8')
    return str(out)


class Harness:
    """server.py as a module on a real socket, with the planner pointed at the fixture DB (the
    tests/test_planner_api.py Harness), plus a text GET for the page itself."""

    def __init__(self, root, data, db):
        self.root, self.data, self.db = str(root), str(data), str(db)
        self.server = None

    def __enter__(self):
        spec = importlib.util.spec_from_file_location('planner_page_test_server',
                                                      str(Path(self.root) / 'server.py'))
        self.mod = importlib.util.module_from_spec(spec)
        os.environ['WFM_BUILD_DB'] = self.db
        spec.loader.exec_module(self.mod)
        self.mod.ROOT = self.root
        self.mod.DATA = self.data                 # never the repo's data/
        self.mod._PLANNER.clear()                 # bind to this database, not a cached one
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.mod.H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_address[1]
        return self

    def __exit__(self, *exc):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        os.environ.pop('WFM_BUILD_DB', None)

    def get_page(self, path):
        with urllib.request.urlopen(self.base + path, timeout=60) as resp:
            return resp.status, resp.headers.get('Content-Type', ''), resp.read().decode('utf-8')


@pytest.fixture(scope='module')
def server(tmp_path_factory, db_file):
    with Harness(REPO, tmp_path_factory.mktemp('planner_page_data'), db_file) as h:
        yield h


def test_the_real_server_serves_the_planner_as_a_shell_page(server):
    """/planner.html is only a page if the server hands it out and it declares itself to the
    shell: data-shell is how shell.js finds the page's registry entry (its sub-title, its active
    rail pill, its way back), so a page that loses the declaration renders with no chrome."""
    status, ctype, body = server.get_page('/planner.html')
    assert status == 200, 'server.py must serve /planner.html out of static/'
    assert 'text/html' in ctype, ctype
    assert 'data-shell="planner"' in body, \
        'planner.html must declare <body data-shell="planner"> or shell.js mounts nothing'
    assert '<script src="/shell.js"></script>' in body, 'and it must load the shared shell'
    # same declaration shape as collection.html: a page, no optional header actions
    assert shell_decl('planner.html') == ('planner', set()), 'planner.html declares itself to the shell'


# ------------------------------------------------------------------ the ids the panels bind to

BIND_PATTERNS = (
    r"getElementById\('([^']+)'\)",     # the long form
    r"\$\('([^']+)'\)",                 # planner.js's shorthand: function $(id) { getElementById }
    r"querySelector\('#([^']+)'",       # querySelector('#id ...') inside a container
)


def bound_ids(text):
    """Every element id a page script reaches for, in any of the three lookup styles."""
    ids = set()
    for pat in BIND_PATTERNS:
        ids |= set(re.findall(pat, text))
    return ids


def test_every_id_the_scripts_bind_to_exists_exactly_once_in_the_page():
    """A panel finds its rows through ids alone: rename one on either side and the page renders
    into nothing, or into the wrong node, with no error. The list is derived from the scripts at
    test time - not hand-copied - so ids added by planner-library.js / planner-stats.js are
    covered the day those files land."""
    html = read_static('planner.html')
    owner = {}
    for name, text in scripts():
        for el_id in bound_ids(text):
            owner.setdefault(el_id, name)
    # the scan is only a contract while it still finds the page's bindings; a change of binding
    # style must fail here, not silently pass
    assert len(owner) >= 20, ('the id scan found almost nothing (%d ids) - the binding style '
                              'changed; re-arm this test' % len(owner))
    missing = ['#%s (bound by %s)' % (i, owner[i]) for i in sorted(owner)
               if 'id="%s"' % i not in html]
    assert missing == [], ('planner.html is missing ids its scripts bind to - add them: '
                           + ', '.join(missing))
    twice = [i for i in sorted(owner) if html.count('id="%s"' % i) > 1]
    assert twice == [], ('getElementById would silently pick the first of each duplicate: '
                         + ', '.join(twice))


# The ids the panels cannot work without, pinned by hand as well as derived: the scan above can
# only see the bindings a script still has, so if a panel loses one (a rewritten script, a
# deleted loader) the id would vanish from both sides and that test would go quiet. These are the
# page's own core - the slot grid, the library list, the stat panel's body, the trace box, the
# validation list, the capacity readout and the two search boxes. (The storage-backed state - the
# config tabs, the toolbar toggles - is pinned by the storage test below, not here.)
CORE_IDS = ('plError', 'plLibHidden', 'plGrid', 'plLibList', 'plStatBody', 'plTraces',
            'plValidity', 'plCapUsed', 'plEquipSearch', 'plLibSearch')


def test_the_pages_core_ids_survive():
    html = read_static('planner.html')
    for el_id in CORE_IDS:
        assert html.count('id="%s"' % el_id) == 1, (
            '#%s is part of the frozen page contract (design/build-planner/phase2-ui-spec.md): '
            'restore it, exactly once' % el_id)


# ------------------------------------------------------------------ storage v1

def test_planner_storage_is_one_key_at_the_servers_version(server):
    """One key, one version. The version is asserted against server.planner_meta() rather than
    copied into this file, so a migration that bumps PLANNER_STORAGE_VERSION fails here until the
    page writes the same version - meta.storage_version is what the page reads to decide."""
    page = read_static('planner.js')
    key = re.search(r"var STORE_KEY = '([^']+)';", page)
    assert key, 'planner.js must declare STORE_KEY'
    assert key.group(1) == 'wfm.planner.v1', 'the storage key is frozen: ' + key.group(1)
    version = re.search(r'var STORE_VERSION = (\d+);', page)
    assert version, 'planner.js must declare STORE_VERSION'
    meta = server.mod.planner_meta()
    assert meta.get('ok') is True, ('the engine + database must answer for this comparison to '
                                    'mean anything: %s' % meta.get('error'))
    assert int(version.group(1)) == meta['storage_version'], (
        'planner.js STORE_VERSION=%s but server.planner_meta() answers storage_version=%s - the '
        'page and the API must agree' % (version.group(1), meta['storage_version']))
    # the frozen spec names the same key and the same version the page writes
    spec = read_spec()
    assert 'wfm.planner.v1' in spec, 'the spec dropped the storage key - see design/build-planner/'
    assert '"version": 1' in spec, 'the spec no longer shows storage version 1'
    # a stored blob of any other version is a fresh start, never migrated blindly
    assert 'Number(data.version) !== STORE_VERSION' in page, \
        'planner.js must ignore an unknown stored version (freshStorage), not read it as v1'
    # and every read/write goes through the one named key, so nothing can accumulate beside it
    for name, text in scripts():
        for call in re.findall(r'localStorage\.(?:get|set|remove)Item\(([^,)]+)', text):
            assert 'STORE_KEY' in call, ('%s writes a second localStorage slot (%s) - the planner '
                                         'owns one key, wfm.planner.v1' % (name, call.strip()))


# ------------------------------------------------------------------ no Warframe math

# `builds/` is the single owner of Warframe math; a number the page computes is a second engine
# that drifts the day the first one changes (this is why /preview and /explain exist at all). What
# the page may do with an engine figure is display it: format it, concatenate it into a label,
# compare it against another engine figure (the capacity bar colours itself from the engine's own
# used > total - both numbers were sent by /compute). What it may not do is multiply or divide a
# Warframe quantity: that is where a second engine starts.
#
# Two narrow signals, both armed below, so a passing test means something:
#   1. an identifier that IS a Warframe quantity (raw_drain, capacity_used, multishot, ...)
#      multiplied or divided by anything - the page computing its own number;
#   2. a line that carries its own arithmetic (Math.round/floor/ceil or a multiplication) AND
#      names a quantity - the whitelist form: formatting a value the engine produced is fine, a
#      line that also reasons about drain/capacity/stats is one edit away from computing one.
# The formatting sites this tolerates today: fmt.num / fmt.int (Math.round of an engine value),
# the capacity bar's width and the stats panel's element share (a percentage of two engine
# figures), and the library popup's pixel positioning. The toolbar's capacity floor is no longer
# on this list: the page reads capacity.minimum_from_mastery off the compute answer, and
# `mastery` is now one of the watched quantities, so a local floor formula would trip the scan.
QUANTITY = r'(?:drain|damage|health|armou?r|shield|multishot|crit|status|capacity|mastery)'
COMPUTE = re.compile(r'\b\w*%s\w*\s*[*/]\s*[\w(]|[)\w]\s*[*/]\s*\w*%s\w*' % (QUANTITY, QUANTITY),
                     re.I)
ARITH = re.compile(r'Math\.(?:round|floor|ceil)\(|[A-Za-z0-9_)\]]\s*\*\s*[\w(]')
QUANTITY_WORD = re.compile(r'\b%s\b' % QUANTITY, re.I)


def test_the_page_formats_engine_numbers_and_computes_none_of_its_own():
    computed, mixed = [], []
    arith_seen = qty_seen = 0
    for name, text in scripts():
        code = scrubbed(text)
        arith_seen += bool(ARITH.search(code))
        qty_seen += bool(QUANTITY_WORD.search(code))
        for no, line in enumerate(code.splitlines(), 1):
            if COMPUTE.search(line):
                computed.append('%s:%d %s' % (name, no, line.strip()))
            elif ARITH.search(line) and QUANTITY_WORD.search(line):
                mixed.append('%s:%d %s' % (name, no, line.strip()))
    # the scan is only a contract while both halves still match the real files, and while the
    # computation pattern still recognises a computation
    assert arith_seen and qty_seen, ('the no-math scan lost its teeth (arith=%d quantity=%d) - '
                                     're-arm it before trusting it' % (arith_seen, qty_seen))
    assert COMPUTE.search('var doubled = raw_drain * 2;'), 'the computation pattern must match'
    assert computed == [], ('the page is multiplying or dividing a Warframe quantity - that is a '
                            'second engine; read the engine\'s field or POST the edit to '
                            '/api/planner/preview instead: ' + ' | '.join(computed))
    assert mixed == [], ('a line does its own arithmetic on a Warframe quantity - if it only '
                         'formats a number the engine produced, narrow it; otherwise move it '
                         'into builds/: ' + ' | '.join(mixed))


# ------------------------------------------------------------------ API text never becomes markup

EMPTY_INNERHTML = re.compile(r"""\.innerHTML\s*=\s*(?:''|"")\s*[;,)]?\s*$""")


def test_no_script_puts_api_text_into_innerHTML():
    """Every row this page draws is API text: mod names, effect lines, refusal reasons, validation
    messages. The shared el() helper builds nodes and sets textContent, so the one sink that would
    execute or mangle that text as markup stays closed - clearing a container with
    `x.innerHTML = ''` is the only assignment this allows."""
    bad = []
    for name, text in scripts():
        for no, line in enumerate(scrubbed(text).splitlines(), 1):
            if not re.search(r'\.innerHTML\s*=', line):
                continue
            if not EMPTY_INNERHTML.search(line.strip()):
                bad.append('%s:%d %s' % (name, no, line.strip()))
    # the check only means something while the page still renders rows through the node helper:
    # pin the helper (createElement + textContent), not just the absence above
    page = dict(scripts())['planner.js']
    assert 'function el(tag, attrs, kids)' in page and 'createElement' in page, (
        'planner.js no longer builds its DOM through el()/textContent - re-check this contract '
        'before editing it')
    # self-check: a broken pattern must fail loudly, never pass this test quietly
    assert re.search(r'\.innerHTML\s*=', 'node.innerHTML = name'), 'the sink pattern must match'
    assert bad == [], ('only an empty literal may go into innerHTML - the rows are API text: '
                       + ' | '.join(bad))


# ------------------------------------------------------------------ icons

def pinned_icons():
    """(REGULAR, FILL) from tools/build_icons.py - the sprite is generated from exactly these
    lists ("Names are pinned on purpose"), so an icon that is not here is a hole in the page."""
    with open(ICONS_PY, encoding='utf-8') as fh:
        text = fh.read()

    def names(var):
        block = text.split('%s = [' % var, 1)[1].split(']', 1)[0]
        return set(re.findall(r"'([a-z0-9-]+)'", block))

    return names('REGULAR'), names('FILL')


# The scripts write attributes through an object literal ('data-icon': 'x'), and one of them picks
# its icon with a ternary, so the scan covers those shapes as well as the HTML attribute form -
# with the HTML form alone it would find nothing in a JS file and pass having checked nothing.
ICON = re.compile(r"""data-icon['"]?\s*[:=]\s*(?:
      ["']([a-z0-9-]+)["']                                              # data-icon="x" / 'x'
    | [^?]{0,80}\?\s*["']([a-z0-9-]+)["']\s*:\s*["']([a-z0-9-]+)["']    # ... ? 'a' : 'b'
)""", re.X)


def icon_names(text):
    out = set()
    for m in ICON.finditer(text):
        out |= {g for g in m.groups() if g}
    return out


def test_every_icon_the_page_asks_for_is_pinned_in_the_sprite_builder():
    """The sprite ships no CDN and no build step: a name that is not in tools/build_icons.py's
    REGULAR (or FILL, for a `-fill` name) resolves to nothing and the icon renders blank."""
    regular, fill = pinned_icons()
    assert regular and fill, 'tools/build_icons.py no longer parses - re-arm this test'
    bad, seen = [], 0
    for name, text in scripts():
        for icon in sorted(icon_names(text)):
            seen += 1
            base = icon[:-len('-fill')] if icon.endswith('-fill') else icon
            pinned = base in fill if icon.endswith('-fill') else icon in regular
            if not pinned:
                bad.append('%s: %s' % (name, icon))
    assert seen >= 3, ('the icon scan found nothing (%d names) - the reference style changed; '
                       're-arm this test' % seen)
    assert bad == [], ('unpinned icon(s): ' + ', '.join(bad) + ' - add the name to '
                       'tools/build_icons.py (REGULAR, or FILL for a -fill name) and run: '
                       'python tools/build_icons.py --fetch')
