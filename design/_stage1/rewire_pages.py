"""Stage 1 helper: rewire the five shell pages onto /shell.js + /shell.css.

Run from the repo root ONCE against the pre-shell pages:
    python design/_stage1/rewire_pages.py
It removes each page's hand-written header / rail / theme panel, declares what the page is on
<body> (data-shell + the header actions it really has today) and loads /shell.js before the
page's own scripts. Everything else - content, sub-nav, footer, scripts, ids - is untouched.
"""
import io
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC = os.path.join(REPO, 'static')

# page -> (body tag before, body tag after, script anchor)
PAGES = {
    'index.html': (
        '<body class="shell-fit">',
        '<body class="shell-fit" data-shell="index" data-shell-actions="search syncState refresh png">',
    ),
    'collection.html': ('<body>', '<body data-shell="collection" data-shell-actions="">'),
    'cards.html': ('<body>', '<body data-shell="cards" data-shell-actions="">'),
    'settings.html': ('<body>', '<body data-shell="settings" data-shell-actions="">'),
    'item.html': ('<body>', '<body data-shell="item" data-shell-actions="">'),
}

NOTE = ('<!-- The chrome (header: brand, #chips, search, sound, theme + panel, the settings/back\n'
        '     link, #syncState, #refresh, PNG, and the left rail #mainnav) is rendered by /shell.js\n'
        '     from this page\'s data-shell declaration. -->\n')

# the page-local CSS the shell now owns (byte-identical to shell.css's .mainnav rule)
DEAD_CSS = '  .mainnav { max-width: calc(100% - 36px); flex-wrap: wrap; }\n'
DEAD_CSS_CRLF = DEAD_CSS.replace('\n', '\r\n')


def main():
    for page, (old_body, new_body) in PAGES.items():
        path = os.path.join(STATIC, page)
        with io.open(path, encoding='utf-8', newline='') as fh:
            text = fh.read()
        crlf = '\r\n' in text
        nl = '\r\n' if crlf else '\n'
        before_ids = re.findall(r'\bid="([^"]+)"', text)

        def sub_once(pattern, repl, flags=0, label=''):
            new, n = re.subn(pattern, repl, text, count=1, flags=flags)
            assert n == 1, '%s: %s did not match once (%d)' % (page, label or pattern, n)
            return new

        # 1. shell.css right after style.css (same precedence the moved rules had)
        text = sub_once(re.escape('<link rel="stylesheet" href="/style.css">'),
                        lambda m: m.group(0) + nl + '<link rel="stylesheet" href="/shell.css">',
                        label='style.css link')
        # 2. what the page is
        text = sub_once(re.escape(old_body), lambda m: new_body, label='body tag')
        # 3. the header + the rail + the theme panel are the shell's now
        text = sub_once(r'[ \t]*<header>.*?</header>\r?\n', NOTE, flags=re.S, label='header block')
        if '<aside class="side"' in text:
            text = sub_once(r'[ \t]*<aside class="side" aria-label="Primary">.*?</aside>\r?\n',
                            '', flags=re.S, label='rail block')
        # 4. shell.js runs first, before every page script (see the file's ORDER note)
        text = sub_once(re.escape('<script src="/adv.js">'),
                        lambda m: '<script src="/shell.js"></script>' + nl + m.group(0),
                        label='shell.js script')
        # 5. the page-local .mainnav override the shared sheet now carries
        if DEAD_CSS in text or DEAD_CSS_CRLF in text:
            text = text.replace(DEAD_CSS, '').replace(DEAD_CSS_CRLF, '')

        with io.open(path, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)

        after_ids = re.findall(r'\bid="([^"]+)"', text)
        moved = [i for i in before_ids if i not in after_ids]
        print('%-16s %3d ids -> %3d, %2d moved to the shell: %s'
              % (page, len(before_ids), len(after_ids), len(moved), ', '.join(moved)))


if __name__ == '__main__':
    main()
