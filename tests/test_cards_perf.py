"""The cards page must stay cheap to open: thumb art, one render per typing pause, offscreen tiles
skipped, and one rect measurement per hover change.

Jay 2026-09-28: "make the card page more optimised, seems to cause some lag." The profile said the
grid was loading the full 1000x1456 art (median 261 KB) into ~125px tiles - 140 of them on first
paint, ~37 MB and roughly 800 MB of decoded bitmaps - plus a 335 ms synchronous rebuild on the
second keystroke and a forced 180-rect measure inside that same event.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    with open(os.path.join(ROOT, p), encoding='utf-8') as fh:
        return fh.read()


def test_the_grid_loads_the_thumb_set_and_the_overlay_keeps_the_full_art():
    js = read('static/cards.js')
    assert "'/hi/' + (full ? '' : 'thumb/') + card.slug + '.webp'" in js      # grid = thumb
    assert 'function artAlt(card, full) { return artSrc(card, !full); }' in js  # fallback other size
    assert 'if (!tried) { tried = true; img.src = artAlt(card, full); return; }' in js
    assert 'if (!fa) addArt(art, card, !!(opts && opts.full));' in js
    assert 'var big = buildCard(card, { quiet: true, full: true });' in js    # inspect = crisp
    assert "img.loading = 'lazy';" in js and "img.decoding = 'async';" in js


def test_typing_renders_once_per_pause_not_once_per_letter():
    js = read('static/cards.js')
    assert 'q._t = window.setTimeout(function () { state.q = v; render(); }, 140);' in js
    assert 'window.clearTimeout(q._t);' in js                    # both handlers cancel a pending run
    assert js.count('window.clearTimeout(q._t);') == 2           # input + clear button
    # the old per-keystroke render is gone
    assert "q.addEventListener('input', function () { state.q = q.value.trim().toLowerCase(); render(); });" not in js


def test_the_rect_cache_pass_cannot_block_a_keystroke_or_go_stale():
    js = read('static/cards.js')
    assert 'var gen = (paintGen += 1);' in js                    # one measure pass per paint
    assert 'if (gen !== paintGen) return;' in js                 # a newer paint wins
    assert 'if (gnode._gr) continue;' in js                      # nothing re-measured twice
    assert 'if (card) card._gr = null;' in js                    # re-measure on hover change
    # the old inline measure loop inside paint() is gone
    assert 'rr = gnode.getBoundingClientRect();\n      gnode._gr' not in js


def test_offscreen_tiles_skip_layout_and_paint():
    html = read('static/cards.html')
    assert 'content-visibility: auto;' in html
    assert 'contain-intrinsic-size: auto 175px;' in html         # ~125px column x 7/5


def test_the_thumb_builder_is_incremental_and_keeps_the_source_ratio():
    py = read('tools/build_card_thumbs.py')
    assert 'WIDTH = 264' in py and 'QUALITY = 84' in py and 'METHOD = 6' in py
    assert 'os.path.getmtime(dst) >= os.path.getmtime(src)' in py   # skip what is already fresh
    assert "im.save(dst, 'WEBP', quality=QUALITY, method=METHOD)" in py
    assert 'static/hi/thumb' in py.replace('\\', '/')               # writes beside the source art
    assert '--force' in py
