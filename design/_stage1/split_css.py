"""Stage 1 helper: move the app shell's CSS out of style.css into static/shell.css.

Run from the repo root ONCE against the pre-split style.css:
    python design/_stage1/split_css.py
It keeps every other line byte-identical, leaves a pointer comment where the chrome used to be,
and writes shell.css from the moved rules in their original order (so cascade order is preserved).
"""
import io
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STYLE = os.path.join(REPO, 'static', 'style.css')
SHELL = os.path.join(REPO, 'static', 'shell.css')

# (label, first_line, last_line) - 1-indexed inclusive, in style.css's own order
BLOCKS = [
    ('header / brand / chips / actions / search', 30, 69),
    ('main nav + pill', 88, 101),
    ('sidebar rail + the <=900px fold', 103, 129),
    ('theme panel', 319, 339),
    ('sub-nav sizing', 430, 431),
    ('global item search dropdown', 475, 490),
    ('nav pill accent dot', 545, 554),
    ('sound toggle (muted strike)', 559, 565),
    ('header .btn icon gap + sound icon swap', 753, 763),
    ('sync state line', 870, 871),
    ('rail pages: shellcol + quieter header chips', 1120, 1128),
]
# rules that live inside a media query in style.css and get their own block in shell.css
MEDIA = [
    ('@media (max-width: 900px)', [(343, 344)]),        # .search input + .tp-grid (2-up)
    ('@media (max-width: 560px)', [(707, 718)]),        # the compact header + the 3+3 pills
]

POINTER = """/* ============ the app shell's own CSS lives in /shell.css ============
   header + brand + chips + actions + global search, the theme panel, .mainnav/.navpill, the .side
   rail and its <=900px fold, .shellbody/.shellcol and the <=560px compact header. One source,
   loaded by every page right after this file. The view, card and table recipes stay here. */
"""


def read(p):
    with io.open(p, encoding='utf-8') as fh:
        return fh.read()


def main():
    original = read(STYLE)
    lines = original.split('\n')

    moved = [(label, '\n'.join(lines[a - 1:b])) for label, a, b in BLOCKS]
    media_moved = [(q, '\n'.join('\n'.join(lines[a - 1:b]) for a, b in rs)) for q, rs in MEDIA]

    gone = set()
    for _l, a, b in BLOCKS:
        gone.update(range(a, b + 1))
    for _q, rs in MEDIA:
        for a, b in rs:
            gone.update(range(a, b + 1))

    out = []                       # (text, came_from_a_removal)
    pointer_placed = False
    for n, ln in enumerate(lines, 1):
        if n in gone:
            out.append(('', True))
            continue
        if not pointer_placed and n > BLOCKS[0][1]:
            out.append((POINTER.rstrip('\n'), False))
            pointer_placed = True
        out.append((ln, False))

    # blank-line runs the removals left behind collapse to ONE blank line; runs that were already
    # in the file (no removed line among them) are left exactly as they were.
    kept, i = [], 0
    while i < len(out):
        ln, was_removed = out[i]
        if ln == '':
            j = i
            while j < len(out) and out[j][0] == '':
                j += 1
            run = out[i:j]
            if any(r for _t, r in run) and len(run) > 1:
                kept.append(('', False))
            else:
                kept.extend(run)
            i = j
            continue
        kept.append((ln, was_removed))
        i += 1
    text = '\n'.join(t for t, _r in kept)
    with io.open(STYLE, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)

    parts = ["""/* WFM Trader - the shared app shell: the chrome's one stylesheet.
 *
 * Loaded by every page right after /style.css, so a rule that used to live there keeps exactly
 * the precedence it had (page CSS and the page's own <style> block still come after this file).
 *
 * No colour is hardcoded here: every value comes from the theme vars theme.js writes on :root
 * (--bg --panel --panel2 --border --text --muted --accent --accent-dim --hover), so all 60
 * themes (30 dark + 30 light) work from this one file.
 *
 * Home: the header (brand, chips, actions, global search), the theme panel, .mainnav/.navpill,
 * the .side rail and its <=900px fold, .shellbody/.shellcol, and the <=560px compact header.
 * The view, card and table recipes stay in /style.css; page-specific CSS stays in the page.
 */
"""]
    for label, chunk in moved:
        parts.append('\n/* ---------------- %s ---------------- */\n' % label)
        parts.append(chunk + '\n')
    for query, chunk in media_moved:
        parts.append('\n/* ---------------- %s (shell rules) ---------------- */\n' % query)
        parts.append(query + ' {\n' + chunk + '\n}\n')
    shell_text = '\n'.join(parts).rstrip('\n') + '\n'
    with io.open(SHELL, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(shell_text)

    print('moved %d blocks + %d media groups' % (len(moved), len(media_moved)))
    print('style.css %d -> %d lines | shell.css %d lines'
          % (len(lines), len(text.split('\n')), len(shell_text.split('\n'))))


if __name__ == '__main__':
    main()
