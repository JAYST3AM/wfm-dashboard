"""Vendor Jay's chosen icon set (Phosphor, MIT) into one self-hosted SVG sprite.

    python tools/build_icons.py --fetch     # download the pinned names -> static/icons/src/
    python tools/build_icons.py             # rebuild static/icons/phosphor.svg from src
    python tools/build_icons.py --check     # verify the sprite covers every data-icon in static/

Why a sprite: the dashboard ships no CDN and no build step, so the icons ride in one file
(~100 KB) fetched once by /icons.js and injected as <symbol>s; markup then refers to them by
name (data-icon="search") and CSS colours them with currentColor.

Names are pinned on purpose: regenerate only when a screen genuinely needs a new icon, so the
sprite stays a short, reviewable list instead of the whole 1,500-icon library.
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, 'static', 'icons', 'src')
SPRITE = os.path.join(REPO, 'static', 'icons', 'phosphor.svg')
LICENSE = os.path.join(REPO, 'static', 'icons', 'LICENSE')
CDN = 'https://cdn.jsdelivr.net/npm/@phosphor-icons/core@2.1.1/assets/%s/%s.svg'
UA = {'User-Agent': 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'}

# regular weight: the workhorse line icons
REGULAR = [
    # shell / navigation
    'house', 'package', 'tag', 'squares-four', 'user', 'dots-three-circle', 'gear-six', 'gear',
    'magnifying-glass', 'funnel', 'arrows-clockwise', 'bell', 'speaker-high', 'speaker-slash',
    'sun', 'moon', 'palette', 'caret-down', 'caret-right', 'caret-up', 'caret-left',
    'arrow-right', 'arrow-left', 'arrow-up-right', 'x', 'check', 'check-circle', 'plus',
    'minus', 'dots-three', 'dots-three-vertical', 'list', 'list-dashes', 'rows', 'columns',
    'table', 'grid-four', 'sliders-horizontal', 'eye', 'eye-slash', 'copy', 'clipboard-text',
    'download-simple', 'upload-simple', 'link', 'arrow-square-out', 'share-network',
    # market / trade
    'shopping-cart', 'shopping-cart-simple', 'coins', 'hand-coins', 'currency-circle-dollar',
    'money', 'receipt', 'storefront', 'scales', 'trend-up', 'trend-down', 'chart-line',
    'chart-bar', 'chart-donut', 'chart-pie-slice', 'percent', 'calculator', 'wallet',
    'credit-card', 'currency-btc',
    # time / history
    'clock', 'clock-counter-clockwise', 'calendar-blank', 'hourglass', 'timer', 'alarm',
    # collection / items
    'trophy', 'medal', 'star', 'sparkle', 'crown', 'diamond', 'cube', 'stack', 'archive',
    'folder', 'folder-open', 'file-text', 'file-plus', 'files', 'book-open', 'bookmark-simple',
    'seal-check', 'certificate', 'shield', 'shield-check', 'lock', 'lock-open', 'key', 'fingerprint',
    # game flavour
    'atom', 'dna', 'flask', 'planet', 'rocket', 'robot', 'sword', 'crosshair', 'target',
    'skull', 'users', 'users-three', 'person', 'handshake', 'lightning', 'fire', 'drop',
    'snowflake', 'leaf', 'bug', 'castle-turret', 'buildings', 'warehouse', 'gas-pump',
    'blueprint',
    # status / alerts
    'warning', 'warning-circle', 'warning-diamond', 'info', 'question', 'x-circle',
    'circle-notch', 'seal-warning', 'prohibit', 'plus-circle', 'minus-circle', 'spinner-gap',
    # cards / misc
    'newspaper', 'broadcast', 'megaphone', 'briefcase', 'notebook', 'note-pencil', 'pencil',
    'trash', 'trash-simple', 'broom', 'wrench', 'hammer', 'scissors', 'magnet', 'lightbulb',
    'floppy-disk', 'hard-drives', 'device-mobile', 'desktop', 'monitor', 'power', 'plug',
    'chart-polar', 'tray', 'arrows-left-right', 'arrow-up', 'arrow-down', 'repeat', 'shuffle',
]

# fill weight: for active/filled states only (nav, status marks, badges)
FILL = [
    'house', 'package', 'tag', 'squares-four', 'user', 'dots-three-circle', 'gear-six',
    'bell', 'speaker-high', 'magnifying-glass', 'funnel', 'arrows-clockwise', 'shopping-cart',
    'coins', 'hand-coins', 'star', 'trophy', 'medal', 'crown', 'diamond', 'sparkle', 'seal-check',
    'shield-check', 'lock', 'warning', 'check-circle', 'x-circle', 'plus-circle', 'lightning',
    'fire', 'drop', 'chart-bar', 'chart-line', 'clock', 'calendar-blank', 'folder', 'file-text',
    'users', 'handshake', 'cube', 'archive', 'trash', 'pencil', 'download-simple', 'copy',
    'list', 'table', 'eye', 'sliders-horizontal', 'caret-down', 'arrow-right', 'check', 'x',
    'plus', 'circle-notch', 'newspaper', 'megaphone', 'storefront', 'wallet', 'arrow-square-out',
    'blueprint',
]


def want_names():
    return [('regular', n) for n in REGULAR] + [('fill', n) for n in FILL]


def fetch_one(weight, name):
    dest = os.path.join(SRC, weight, name + '.svg')
    if os.path.exists(dest) and os.path.getsize(dest) > 60:
        return 'cached'
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = CDN % (weight, name if weight == 'regular' else name + '-fill')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode('utf-8', 'replace')
    if '<svg' not in text:
        raise ValueError('not svg')
    io.open(dest, 'w', encoding='utf-8', newline='\n').write(text)
    return 'fetched'


def inner_and_box(path):
    text = io.open(path, encoding='utf-8', errors='replace').read()
    box = re.search(r'viewBox="([^"]+)"', text)
    inner = re.sub(r'^.*?<svg[^>]*>', '', text, flags=re.S)
    inner = re.sub(r'</svg>\s*$', '', inner, flags=re.S)
    inner = re.sub(r'<!--.*?-->', '', inner, flags=re.S)
    return re.sub(r'\s+', ' ', inner).strip(), (box.group(1) if box else '0 0 256 256')


def build():
    parts = []
    missing = []
    for weight, name in want_names():
        path = os.path.join(SRC, weight, name + '.svg')
        if not os.path.exists(path):
            missing.append('%s/%s' % (weight, name))
            continue
        inner, box = inner_and_box(path)
        sid = 'i-%s' % name if weight == 'regular' else 'i-%s-fill' % name
        parts.append('<symbol id="%s" viewBox="%s">%s</symbol>' % (sid, box, inner))
    doc = ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">'
           '<defs>%s</defs></svg>\n' % ''.join(parts))
    os.makedirs(os.path.dirname(SPRITE), exist_ok=True)
    io.open(SPRITE, 'w', encoding='utf-8', newline='\n').write(doc)
    return len(parts), missing, len(doc)


def scan_references():
    """Every data-icon="x" and #i-x reference in the static front-end."""
    refs = {}
    static = os.path.join(REPO, 'static')
    for root, dirs, files in os.walk(static):
        dirs[:] = [d for d in dirs if d not in ('icons', 'hi', 'colimg', 'cardart')]
        for fn in files:
            if not fn.endswith(('.html', '.js')):
                continue
            path = os.path.join(root, fn)
            text = io.open(path, encoding='utf-8', errors='replace').read()
            for m in re.finditer(r'data-icon="([a-z0-9-]+)"', text):
                refs.setdefault(m.group(1), set()).add(fn)
            for m in re.finditer(r'#i-([a-z0-9-]+)', text):
                refs.setdefault(m.group(1), set()).add(fn)
    return refs


def check():
    ids = set(re.findall(r'<symbol id="([^"]+)"', io.open(SPRITE, encoding='utf-8').read()))
    if not ids:
        print('FAIL no sprite at %s - run without --check first' % SPRITE)
        return 1
    refs = scan_references()
    unknown = {r: sorted(f) for r, f in refs.items() if ('i-' + r) not in ids}
    print('sprite symbols : %d' % len(ids))
    print('referenced     : %d distinct' % len(refs))
    if unknown:
        print('UNRESOLVED (%d):' % len(unknown))
        for name, files in sorted(unknown.items()):
            print('   %-24s %s' % (name, ', '.join(files[:3])))
        return 1
    print('all references resolve')
    return 0


def main():
    ap = argparse.ArgumentParser(description='Build the self-hosted Phosphor sprite.')
    ap.add_argument('--fetch', action='store_true', help='download the pinned names first')
    ap.add_argument('--check', action='store_true', help='verify every static/ reference resolves')
    args = ap.parse_args()
    if args.check:
        sys.exit(check())
    if args.fetch:
        got = {'fetched': 0, 'cached': 0}
        failed = []
        for weight, name in want_names():
            try:
                got[fetch_one(weight, name)] += 1
            except Exception as exc:
                failed.append('%s/%s (%s)' % (weight, name, type(exc).__name__))
        print('fetch: %d downloaded, %d cached, %d failed' % (got['fetched'], got['cached'], len(failed)))
        for f in failed:
            print('   FAILED', f)
    count, missing, size = build()
    print('sprite : %d symbols, %d bytes -> %s' % (count, size, os.path.relpath(SPRITE, REPO)))
    if missing:
        print('missing sources (%d): %s' % (len(missing), ', '.join(missing[:12])))
    print('attribution: %s' % ('present' if os.path.exists(LICENSE) else 'MISSING - add static/icons/LICENSE'))


if __name__ == '__main__':
    main()
