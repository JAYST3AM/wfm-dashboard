"""Build the mod-cards grid thumbnail set.

Jay 2026-09-28: "make the card page more optimised, seems to cause some lag." The grid was
loading the full card art (static/hi/<slug>.webp, 1000x1456, median 261 KB) into ~125px tiles -
140 of those on first paint is 37 MB and roughly 800 MB of decoded bitmaps, which is the lag.

This writes static/hi/thumb/<slug>.webp at 264px wide (about 15 KB, ~14x fewer pixels). The grid
uses the thumb; the inspect overlay and the drawer keep the full-size file, so the big card stays
crisp. static/hi/ is gitignored, so neither set ships - the released app falls back to letter
tiles by design.

Run:  python tools/build_card_thumbs.py [--force]
"""

import os
import sys
import time

try:
    from PIL import Image
except ImportError:
    print('Pillow is required: pip install pillow')
    raise SystemExit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'static', 'hi')
DST = os.path.join(SRC, 'thumb')
WIDTH = 264          # ~2x the widest tile column, so it stays sharp on a hidpi screen
QUALITY = 84         # the tile is displayed at up to 262 device px from these 264: encode artefacts
                     # would show at 1:1, and 84 costs about 10 KB more than 72 for a clean face
METHOD = 6           # webp encoder effort: 6 buys clean edges at ~3x the encode time of 4, once


def main(argv):
    force = '--force' in argv
    if not os.path.isdir(SRC):
        print('no static/hi - nothing to do (the app keeps its letter tiles)')
        return 0
    os.makedirs(DST, exist_ok=True)
    names = sorted(f for f in os.listdir(SRC) if f.lower().endswith('.webp'))
    if not names:
        print('static/hi has no webp art - nothing to do')
        return 0
    made = skipped = failed = 0
    t0 = time.time()
    for i, name in enumerate(names, 1):
        src = os.path.join(SRC, name)
        dst = os.path.join(DST, name)
        if not force and os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            skipped += 1
            continue
        try:
            im = Image.open(src)
            if im.width > WIDTH:
                h = max(1, round(im.height * WIDTH / im.width))
                im = im.resize((WIDTH, h), Image.LANCZOS)
            im.save(dst, 'WEBP', quality=QUALITY, method=METHOD)
            made += 1
        except Exception as e:
            failed += 1
            print('  fail %s: %s' % (name, e))
        if i % 200 == 0:
            print('  %d/%d (%.0fs)' % (i, len(names), time.time() - t0), flush=True)
    files = [f for f in os.listdir(DST) if f.lower().endswith('.webp')]
    tot = sum(os.path.getsize(os.path.join(DST, f)) for f in files)
    print('thumbs: %d made, %d already fresh, %d failed | %d files, %.1f MB, %.0fs'
          % (made, skipped, failed, len(files), tot / 1e6, time.time() - t0))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
