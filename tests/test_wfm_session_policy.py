"""scripts/trader/wfm_session.py: verification is the account owner's own step.

The rule this file locks in (Jay, 2026-09-26): a browser check or one-time code is the user's to
obtain - the app never fetches, guesses, logs or stores it. Same thing AlecaFrame tells its users.

scripts/trader/ is private (gitignored - not in the public checkout), so this module skips itself
when that folder is missing. Nothing here touches the network: the opener is faked.
"""
import importlib.util
import json
import os
import sys
import urllib.error

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION_PY = os.path.join(REPO, 'scripts', 'trader', 'wfm_session.py')

pytestmark = pytest.mark.skipif(not os.path.exists(SESSION_PY),
                                reason='scripts/trader/ is private (not in the public checkout)')


def load_session():
    sys.path.insert(0, os.path.dirname(SESSION_PY))
    spec = importlib.util.spec_from_file_location('trader_wfm_session', SESSION_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Resp:
    def __init__(self, payload):
        self._bytes = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._bytes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Serves scripted responses; records every request so a test can inspect the bodies."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def open(self, req, timeout=None):
        self.seen.append({'url': req.full_url, 'method': req.get_method(),
                          'data': (req.data or b'').decode('utf-8', 'replace'),
                          'csrf': req.get_header('X-csrf-token')})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return Resp(item)


HOME_HTML = b'<html><head><meta name="csrf-token" content="TOKEN123"></head></html>'


def http_error(code, body, headers=None):
    return urllib.error.HTTPError('https://api.warframe.market/v1/auth/signin', code, 'err',
                                  headers or {}, Resp(body))


# --------------------------------------------------------------------------- detection rules
def test_cloudflare_challenge_is_recognised_as_a_browser_step():
    w = load_session()
    assert w.is_browser_challenge(403, {'cf-mitigated': 'challenge'}) is True
    assert w.is_browser_challenge(503, {'cf-mitigated': 'challenge'}) is True
    assert w.is_browser_challenge(403, {'server': 'cloudflare'}) is False    # a plain block, not a check
    assert w.is_blocked_by_edge(403, {'server': 'cloudflare'}) is True


def test_only_verification_flavoured_errors_ask_for_a_code():
    w = load_session()
    assert w.wants_verification(401, '{"error": "2FA code required"}') is True
    assert w.wants_verification(400, 'verification required') is True
    assert w.wants_verification(401, '{"error": "invalid password"}') is False
    assert w.wants_verification(500, 'verification required') is False      # server fault, not a code


def test_the_guide_is_the_users_own_step_and_says_so():
    w = load_session()
    guide = w.DEFAULT_VERIFICATION_GUIDE.lower()
    assert 'alecaframe' in guide                 # same message that app gives
    assert 'wfm_token' in guide and 'secrets.json' in guide
    assert 'never' in guide and 'yours to do' in guide


# --------------------------------------------------------------------------- signin paths
def test_browser_challenge_stops_with_instructions(tmp_path, monkeypatch):
    w = load_session()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    monkeypatch.setenv('WFM_EMAIL', 'a@b.c')
    monkeypatch.setenv('WFM_PASSWORD', 'pw')
    monkeypatch.setattr(w.urllib.request, 'build_opener',
                        lambda *a, **k: FakeOpener([http_error(403, '', {'CF-Mitigated': 'challenge'})]))
    with pytest.raises(w.VerificationNeeded) as exc:
        w.signin()
    assert 'cloudflare' in str(exc.value).lower()
    assert 'wfm_token' in exc.value.instructions


def test_a_plain_edge_block_is_not_dressed_up_as_a_code(tmp_path, monkeypatch):
    w = load_session()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    monkeypatch.setenv('WFM_EMAIL', 'a@b.c')
    monkeypatch.setenv('WFM_PASSWORD', 'pw')
    monkeypatch.setattr(w.urllib.request, 'build_opener',
                        lambda *a, **k: FakeOpener([http_error(403, 'blocked', {'Server': 'cloudflare'})]))
    with pytest.raises(w.WfmError) as exc:
        w.signin()
    assert not isinstance(exc.value, w.VerificationNeeded)
    assert 'blocked this connection' in str(exc.value)


def test_the_users_browser_session_skips_the_password_signin(tmp_path, monkeypatch):
    w = load_session()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    (tmp_path / 'secrets.json').write_text(json.dumps({'wfm_token': 'JWT-FROM-BROWSER'}), encoding='utf-8')
    monkeypatch.delenv('WFM_TOKEN', raising=False)
    monkeypatch.delenv('WFM_PASSWORD', raising=False)
    s = w.signin()                                  # no network: the token route needs none
    jar = next(h.cookiejar for h in s.op.handlers if hasattr(h, 'cookiejar'))
    assert [c.value for c in jar] == ['JWT-FROM-BROWSER']


def test_no_credentials_asks_for_setup(tmp_path, monkeypatch):
    w = load_session()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    for var in ('WFM_TOKEN', 'WFM_EMAIL', 'WFM_PASSWORD'):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(w.WfmError) as exc:
        w.signin()
    assert 'no WFM login' in str(exc.value)


def test_a_requested_code_is_used_once_and_never_stored(tmp_path, monkeypatch):
    w = load_session()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    monkeypatch.setenv('WFM_EMAIL', 'a@b.c')
    monkeypatch.setenv('WFM_PASSWORD', 'pw')
    monkeypatch.setenv('WFM_VERIFY_CODE', '42-CODE')
    fake = FakeOpener([HOME_HTML,
                       http_error(401, '{"error":"2FA verification required"}'),
                       {'payload': {'user': {'ingameName': 'SampleTennoIX'}}}])
    monkeypatch.setattr(w.urllib.request, 'build_opener', lambda *a, **k: fake)
    s = w.signin()

    assert s.user['ingameName'] == 'SampleTennoIX'
    posts = [r for r in fake.seen if r['method'] == 'POST']
    assert len(posts) == 2
    assert '42-CODE' not in posts[0]['data']                 # never sent pre-emptively
    assert json.loads(posts[1]['data'])['code'] == '42-CODE'  # sent only after being asked
    # and nothing anywhere wrote the code to disk
    written = list(tmp_path.rglob('*'))
    for p in written:
        if p.is_file():
            assert '42-CODE' not in p.read_text(encoding='utf-8', errors='replace')


def test_missing_code_leaves_the_ball_with_the_user(tmp_path, monkeypatch):
    w = load_session()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    monkeypatch.setenv('WFM_EMAIL', 'a@b.c')
    monkeypatch.setenv('WFM_PASSWORD', 'pw')
    monkeypatch.delenv('WFM_VERIFY_CODE', raising=False)
    monkeypatch.setattr(w.sys.stdin, 'isatty', lambda: False, raising=False)
    fake = FakeOpener([HOME_HTML, http_error(401, '{"error":"2FA code required"}')])
    monkeypatch.setattr(w.urllib.request, 'build_opener', lambda *a, **k: fake)
    with pytest.raises(w.VerificationNeeded):
        w.signin()
    assert len([r for r in fake.seen if r['method'] == 'POST']) == 1     # no blind retries
