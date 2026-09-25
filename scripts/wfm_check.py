"""Verify your warframe.market login and show your live orders.

Usage: python scripts/wfm_check.py

Login, in order of preference:
  * `wfm_token` (or env WFM_TOKEN) — the JWT cookie from a session you made in your own browser.
    This is the way past a Cloudflare browser check.
  * `wfm_email` / `wfm_password` (or env WFM_EMAIL / WFM_PASSWORD) in secrets.json.

**Verification is your own step** — the same thing AlecaFrame tells its users. The app never asks
for, fetches, stores or logs a one-time code, and it never answers a browser check for you: if the
site wants either, this prints what to do and stops (README → Signing in).
"""
import http.cookiejar, json, os, sys, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
SITE = 'https://warframe.market/'

GUIDE = """\
warframe.market wants a browser check or a one-time code, and stopped the sign-in here.

That part is yours to do - it is the same thing AlecaFrame tells its users. Nothing here asks
for, fetches, stores or logs a code; nothing is sent anywhere except warframe.market.

  1. Sign in at https://warframe.market in your own browser and finish whatever it shows
     (Cloudflare check, emailed code, authenticator).
  2. Then paste that session into secrets.json so this never comes up again:
         "wfm_token": "<F12 -> Application -> Cookies -> warframe.market -> JWT>"
     The app uses the session you made and skips the password sign-in entirely."""

CODE_HINTS = ('2fa', '2-factor', 'two-factor', 'two_factor', 'verification', 'verify',
              'one-time', 'one_time', 'otp', 'code', 'captcha', 'challenge')


def is_browser_challenge(status, headers):
    """Cloudflare offering an interactive check (not a plain block)."""
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    return status in (403, 503) and 'challenge' in (hdrs.get('cf-mitigated') or '').lower()


def is_blocked_by_edge(status, headers):
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    return status in (403, 503) and 'cloudflare' in (hdrs.get('server') or '').lower()


def wants_code(status, body_text):
    if status not in (400, 401, 403, 409, 422, 428):
        return False
    text = (body_text or '').lower()
    return any(hint in text for hint in CODE_HINTS)


def load_login():
    """(token, email, password) — token first, then the password pair."""
    sec = {}
    p = os.path.join(ROOT, 'secrets.json')
    if os.path.exists(p):
        try:
            sec = json.load(open(p, encoding='utf-8'))
        except (OSError, ValueError):
            sec = {}
    token = (sec.get('wfm_token') or os.environ.get('WFM_TOKEN') or '').strip()
    email = sec.get('wfm_email') or os.environ.get('WFM_EMAIL')
    pw = sec.get('wfm_password') or os.environ.get('WFM_PASSWORD')
    return token, email, pw


def session_from_token(token):
    cj = http.cookiejar.CookieJar()
    cj.set_cookie(http.cookiejar.Cookie(0, 'JWT', token, None, False, '.warframe.market', True,
                                        True, '/', True, True, None, False, None, None, {}, False))
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def signin(opener, email, pw):
    """Returns the user dict, or None when the site asked for the user's own verification."""
    try:
        home = opener.open(urllib.request.Request(SITE, headers={'User-Agent': UA}),
                           timeout=30).read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        hdrs = dict(e.headers or {})
        if is_browser_challenge(e.code, hdrs):
            print(GUIDE)
            return None
        if is_blocked_by_edge(e.code, hdrs):
            print(f'warframe.market blocked this connection at its edge (http {e.code}) - '
                  f'no code fixes that. Try again later, or use wfm_token.')
            return None
        raise
    import re
    m = re.search(r'csrf-token" content="([^"]+)"', home)
    csrf = m.group(1) if m else ''
    body = json.dumps({'email': email, 'password': pw}).encode()
    req = urllib.request.Request('https://api.warframe.market/v1/auth/signin', data=body, headers={
        'User-Agent': UA, 'Content-Type': 'application/json',
        'X-CSRF-Token': csrf, 'Referer': SITE})
    try:
        j = json.loads(opener.open(req, timeout=30).read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        if is_browser_challenge(e.code, dict(e.headers or {})) or wants_code(e.code, raw):
            print(GUIDE)
            return None
        raise
    return (j.get('payload') or {}).get('user') or {}


def main():
    token, email, pw = load_login()
    if token:
        op = session_from_token(token)
        print('using the session from your browser (wfm_token)')
    elif email and pw:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        user = signin(op, email, pw)
        if user is None:
            sys.exit(2)
        name = user.get('ingameName') or user.get('ingame_name') or '?'
        print(f'OK - signed in as {name} (rep {user.get("reputation", "?")})')
    else:
        print('No login found.')
        print('Put "wfm_token" (your browser session) or "wfm_email"/"wfm_password" in secrets.json, '
              'or set WFM_TOKEN / WFM_EMAIL / WFM_PASSWORD. See README -> Signing in.')
        sys.exit(1)

    try:
        o = json.loads(op.open(urllib.request.Request(
            'https://api.warframe.market/v2/orders/my',
            headers={'User-Agent': UA, 'Accept': 'application/json'}), timeout=30).read().decode())
    except urllib.error.HTTPError as e:
        print(f'orders fetch failed: http {e.code} - the session may have expired; '
              f'sign in again in your browser and refresh wfm_token.')
        sys.exit(2)
    orders = o.get('data') or []
    sells = sum(1 for x in orders if x.get('type') == 'sell')
    buys = sum(1 for x in orders if x.get('type') == 'buy')
    print(f'live orders: {len(orders)} ({sells} sell / {buys} buy)')


if __name__ == '__main__':
    main()
