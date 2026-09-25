"""Verify your warframe.market login (secrets.json) and show your live orders.

Usage: python scripts/wfm_check.py
Login comes from secrets.json ("wfm_email" / "wfm_password") or env WFM_EMAIL / WFM_PASSWORD.
"""
import json, os, re, sys, urllib.request, http.cookiejar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'


def load_login():
    sec = {}
    p = os.path.join(ROOT, 'secrets.json')
    if os.path.exists(p):
        sec = json.load(open(p, encoding='utf-8'))
    email = sec.get('wfm_email') or os.environ.get('WFM_EMAIL')
    pw = sec.get('wfm_password') or os.environ.get('WFM_PASSWORD')
    if not email or not pw:
        print('No login found.')
        print('Copy secrets.example.json to secrets.json and fill it in, then run this again.')
        sys.exit(1)
    return email, pw


def main():
    email, pw = load_login()
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    home = op.open(urllib.request.Request('https://warframe.market/', headers={'User-Agent': UA}), timeout=30)
    m = re.search(r'csrf-token" content="([^"]+)"', home.read().decode('utf-8', 'replace'))
    csrf = m.group(1) if m else ''

    body = json.dumps({'email': email, 'password': pw}).encode()
    req = urllib.request.Request('https://api.warframe.market/v1/auth/signin', data=body, headers={
        'User-Agent': UA, 'Content-Type': 'application/json',
        'X-CSRF-Token': csrf, 'Referer': 'https://warframe.market/'})
    j = json.loads(op.open(req, timeout=30).read().decode())
    user = (j.get('payload') or {}).get('user') or {}
    name = user.get('ingameName') or user.get('ingame_name') or '?'
    rep = user.get('reputation', '?')
    print(f'OK — signed in as {name} (rep {rep})')

    o = json.loads(op.open(urllib.request.Request(
        'https://api.warframe.market/v2/orders/my',
        headers={'User-Agent': UA, 'Accept': 'application/json'}), timeout=30).read().decode())
    orders = o.get('data') or []
    sells = sum(1 for x in orders if x.get('type') == 'sell')
    buys = sum(1 for x in orders if x.get('type') == 'buy')
    print(f'live orders: {len(orders)} ({sells} sell / {buys} buy)')


if __name__ == '__main__':
    main()
