"""static/icons/* - the self-hosted Phosphor sprite, its wiring and its attribution.

Offline twin of ``python tools/build_icons.py --check``: the sprite and the static/ front-end
are read directly (no network, no server), so a typo'd ``data-icon`` fails the suite loudly even
when the authoring gate was not run. Pinned here:

  * the sprite parses as SVG, carries >180 <symbol>s and every id is namespaced ``i-``;
  * icons.js safety properties - a missing sprite must never throw (the fetch chain has a
    catch), the SVG class goes through setAttribute (SVGElement.className is read-only), and
    icons are appended into the host, never written over it with innerHTML;
  * the self-hosted promise - no icon CDN (jsdelivr / unpkg / esm.sh) or remote phosphor URL
    anywhere under static/;
  * the six UI pages each link /icons.css and /icons.js exactly once, inside <head>;
  * Phosphor's MIT licence shipped at static/icons/LICENSE and credited in README.md;
  * the sprite stays under 400 KB and stays in sync with the pinned name lists in
    tools/build_icons.py.
"""
import importlib.util
import io
import os
import re
import sys
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO, 'static')
SPRITE = os.path.join(STATIC, 'icons', 'phosphor.svg')
ICONS_JS = os.path.join(STATIC, 'icons.js')
ICONS_CSS = os.path.join(STATIC, 'icons.css')
LICENCE = os.path.join(STATIC, 'icons', 'LICENSE')
README = os.path.join(REPO, 'README.md')
BUILD_ICONS = os.path.join(REPO, 'tools', 'build_icons.py')

# every page that ships the dashboard UI
PAGES = ('index.html', 'collection.html', 'cards.html', 'item.html', 'lookup.html', 'settings.html')
MAX_SPRITE_BYTES = 400 * 1024

SYMBOL = re.compile(r'<symbol id="([^"]+)"')
DATA_ICON = re.compile(r"""data-icon\s*=\s*(["'])([a-z0-9-]+)\1""")
HASH_I = re.compile(r'#i-([a-z0-9-]+)')
CDN = re.compile(r'cdn\.jsdelivr\.net|unpkg\.com|esm\.sh', re.I)
PHOSPHOR_URL = re.compile(r'https?://[^"\')\s]*phosphor', re.I)


def read(path):
    return io.open(path, encoding='utf-8', errors='replace').read()


def sprite_ids():
    return SYMBOL.findall(read(SPRITE))


def scan_references():
    """Every data-icon="x" and #i- reference in static/**/*.{html,js}.

    Stricter than the authoring gate: both quote styles count, and the owning files are
    collected so a failure points at the page that carries the typo. Returns
    ``(refs, occurrences, n_files)`` with ``refs`` mapping name -> sorted file names.
    """
    refs, total, files = {}, 0, set()
    for root, _dirs, fns in os.walk(STATIC):
        for fn in sorted(fns):
            if not fn.endswith(('.html', '.js')):
                continue
            text = read(os.path.join(root, fn))
            rel = os.path.relpath(os.path.join(root, fn), STATIC).replace(os.sep, '/')
            for m in DATA_ICON.finditer(text):
                refs.setdefault(m.group(2), set()).add(rel)
                total += 1
                files.add(rel)
            for m in HASH_I.finditer(text):
                refs.setdefault(m.group(1), set()).add(rel)
                files.add(rel)
    return refs, total, len(files)


def scan_summary(refs, total, nfiles):
    return '%d distinct icon names in %d references across %d files under static/' % (
        len(refs), total, nfiles)


def function_body(js, name):
    """Text between the outer braces of ``function name(...) { ... }`` (naive, fine here)."""
    m = re.search(r'function\s+%s\s*\([^)]*\)\s*\{' % name, js)
    assert m, 'icons.js no longer defines %s()' % name
    depth = 0
    for pos in range(m.end() - 1, len(js)):
        if js[pos] == '{':
            depth += 1
        elif js[pos] == '}':
            depth -= 1
            if depth == 0:
                return js[m.end():pos]
    raise AssertionError('unbalanced braces after %s() in icons.js' % name)


# --- the sprite ---------------------------------------------------------------------------

def test_sprite_parses_and_symbols_are_namespaced():
    assert os.path.exists(SPRITE), 'missing sprite %s' % SPRITE
    root = ET.parse(SPRITE).getroot()
    assert root.tag.split('}')[-1] == 'svg', 'sprite root element is %s' % root.tag
    symbols = [el for el in root.iter() if el.tag.split('}')[-1] == 'symbol']
    ids = sprite_ids()
    assert len(symbols) == len(ids), 'XML parse sees %d symbols, regex sees %d' % (
        len(symbols), len(ids))
    assert len(ids) > 180, 'expected >180 symbols, found %d' % len(ids)
    bad = [i for i in ids if not i.startswith('i-')]
    assert not bad, 'symbol ids must be namespaced i-<name>: %s' % bad[:5]
    assert len(set(ids)) == len(ids), 'duplicate symbol ids in the sprite'


def test_sprite_is_not_enormous():
    size = os.path.getsize(SPRITE)
    assert size < MAX_SPRITE_BYTES, 'sprite is %d bytes (%.0f KB) - over the 400 KB budget' % (
        size, size / 1024.0)


def test_every_static_reference_resolves_to_a_symbol():
    ids = set(sprite_ids())
    refs, total, nfiles = scan_references()
    assert len(refs) >= 40, 'scan looks vacuous (%s) - did the scanner break?' % scan_summary(
        refs, total, nfiles)
    unknown = {r: sorted(f) for r, f in refs.items() if ('i-' + r) not in ids}
    assert not unknown, 'unresolved data-icon / #i- references (%s, sprite carries %d symbols): %s' % (
        scan_summary(refs, total, nfiles), len(ids),
        '; '.join('%s <- %s' % (r, ', '.join(f)) for r, f in sorted(unknown.items())))


def test_build_icons_pins_match_sprite():
    """tools/build_icons.py's REGULAR/FILL lists and the sprite must stay one-to-one."""
    spec = importlib.util.spec_from_file_location('wfm_build_icons_under_test', BUILD_ICONS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    expected = set()
    for weight, name in mod.want_names():
        expected.add('i-%s' % name if weight == 'regular' else 'i-%s-fill' % name)
    assert len(expected) == len(mod.want_names()), 'duplicate pins collapse to one symbol id'
    ids = set(sprite_ids())
    missing = sorted(expected - ids)
    extra = sorted(ids - expected)
    assert not missing and not extra, (
        'sprite has %d symbols but build_icons.py pins %d names (missing %s / extra %s)' % (
            len(ids), len(expected), missing, extra))


# --- self-hosted, no CDN ------------------------------------------------------------------

def test_no_icon_cdn_anywhere_in_static():
    hits = []
    for root, _dirs, fns in os.walk(STATIC):
        for fn in fns:
            if not fn.endswith(('.html', '.js', '.css', '.svg')):
                continue
            path = os.path.join(root, fn)
            text = read(path)
            for rx in (CDN, PHOSPHOR_URL):
                for m in rx.finditer(text):
                    hits.append('%s: %s' % (
                        os.path.relpath(path, REPO).replace(os.sep, '/'), m.group(0)))
    assert not hits, 'the sprite is self-hosted; remote/CDN references found: %s' % hits


# --- wiring -------------------------------------------------------------------------------

def test_six_pages_link_icons_css_and_js_once():
    problems = []
    for page in PAGES:
        path = os.path.join(STATIC, page)
        assert os.path.exists(path), 'missing page %s' % page
        text = read(path)
        head = re.search(r'<head[^>]*>(.*?)</head>', text, re.S | re.I)
        assert head, '%s has no <head>' % page
        for label, rx in (('/icons.css', r'<link[^>]+href=["\']/icons\.css["\']'),
                          ('/icons.js', r'<script[^>]+src=["\']/icons\.js["\']')):
            whole = len(re.findall(rx, text))
            in_head = len(re.findall(rx, head.group(1)))
            if whole != 1 or in_head != 1:
                problems.append('%s: %s appears %d time(s) in the document, %d in <head>' % (
                    page, label, whole, in_head))
    assert not problems, 'each UI page must link the icons assets exactly once, in <head>: %s' % (
        '; '.join(problems))


def test_icons_css_sizes_icons_at_1em():
    css = read(ICONS_CSS)
    rule = re.search(r'\.i\s*\{([^}]*)\}', css)
    assert rule, 'icons.css no longer styles .i'
    body = rule.group(1)
    assert re.search(r'\bwidth\s*:\s*1em', body), '.i lost width: 1em'
    assert re.search(r'\bheight\s*:\s*1em', body), '.i lost height: 1em'


def test_icons_js_safety_properties():
    js = read(ICONS_JS)

    # a missing or failed sprite must never break the page
    assert 'fetch(' in js
    assert re.search(r'\.catch\s*\(', js), (
        'icons.js fetch chain lost its .catch - a missing sprite would throw instead of '
        'degrading to a UI without icons')

    # SVGElement.className is a read-only SVGAnimatedString: class must go through setAttribute
    assert re.search(r"""setAttribute\(\s*['"]class['"]""", js)
    assert not re.search(r'\.className\s*=', js), (
        'SVG className assignment (read-only, silently ignored) is back; use setAttribute')

    # icons are appended into the host, never innerHTML'd over its content
    body = function_body(js, 'render')
    assert 'innerHTML' not in body, 'render() must not innerHTML its host - labels live there'
    assert 'insertBefore(' in body, 'render() must insert the icon into the host'
    assert 'host.innerHTML' not in js
    targets = set(re.findall(r'([A-Za-z_$][\w$]*)\.innerHTML', js))
    assert targets <= {'holder'}, 'innerHTML writes outside the detached sprite holder: %s' % (
        sorted(targets))

    # later renders (app.js templates) are picked up without an explicit render() call
    assert 'MutationObserver' in js and 'observe(' in js
    assert 'wfmIcons' in js and 'i-before' in js


# --- attribution --------------------------------------------------------------------------

def test_licence_and_readme_credit_phosphor():
    lic = read(LICENCE)
    assert 'MIT' in lic and 'Phosphor' in lic, 'static/icons/LICENSE must hold Phosphor MIT text'
    readme = read(README)
    credited = [ln.strip() for ln in readme.splitlines() if 'Phosphor' in ln and 'MIT' in ln]
    assert credited, 'README.md must credit Phosphor (MIT)'
    assert 'static/icons/' in readme, 'README.md must say the icons are vendored in static/icons/'
