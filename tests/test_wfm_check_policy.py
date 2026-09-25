"""scripts/wfm_check.py: the public login checker follows the same rule as the private one.

A browser check or one-time code is the account owner's own step (AlecaFrame tells its users the
same). This checker never prompts for a code, never stores one, and stops with instructions.
No network: the opener is faked.
"""
import importlib.util
import json
import os
import urllib.error

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_PY = os.path.join(REPO, 'scripts', 'wfm_check.py')


def load_check():
    spec = importlib.util.spec_from_file_location('wfm_check_mod', CHECK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Resp:
    def __init__(self, payload):
        self._b = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._b


class FakeOpener:
    def __init__(self, script):
        self.script = list(script)

    def open(self, req, timeout=None):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return Resp(item)


def load_session():
    return load_check()


# --------------------------------------------------------------------------- detection rules
def test_challenge_and_block_are_not_the_same_thing():
    w = load_check()
    assert w.is_browser_challenge(403, {'cf-mitigated': 'challenge'}) is True
    assert w.is_browser_challenge(403, {'server': 'cloudflare'}) is False
    assert w.is_blocked_by_edge(403, {'server': 'cloudflare'}) is True
    assert w.wants_code(401, '{"error":"2FA code required"}') is True
    assert w.wants_code(401, '{"error":"bad password"}') is False


# --------------------------------------------------------------------------- login resolution
def test_token_wins_over_the_password_pair(tmp_path, monkeypatch):
    w = load_check()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    (tmp_path / 'secrets.json').write_text(
        json.dumps({'wfm_token': 'TOK', 'wfm_email': 'a@b.c', 'wfm_password': 'pw'}), encoding='utf-8')
    assert w.load_login() == ('TOK', 'a@b.c', 'pw')
    monkeypatch.delenv('WFM_TOKEN', raising=False)


def test_env_fallback_and_no_login_message(tmp_path, monkeypatch):
    w = load_check()
    monkeypatch.setattr(w, 'ROOT', str(tmp_path))
    for var in ('WFM_TOKEN', 'WFM_EMAIL', 'WFM_PASSWORD'):
        monkeypatch.delenv(var, raising=False)
    assert w.load_login() == ('', None, None)


# --------------------------------------------------------------------------- behaviour
def test_a_browser_check_prints_the_guide_instead_of_crashing(tmp_path, monkeypatch, capsys):
    w = load_check()
    opener = FakeOpener([urllib.error.HTTPError('u', 403, 'err',
                                                {'CF-Mitigated': 'challenge'}, Resp(b''))])
    assert w.signin(opener, 'a@b.c', 'pw') is None
    out = capsys.readouterr().out
    assert 'yours to do' in out and 'AlecaFrame' in out
    assert 'wfm_token' in out


def test_a_code_request_also_prints_the_guide(tmp_path, capsys):
    w = load_check()
    opener = FakeOpener([b'<meta name="csrf-token" content="X">',
                         urllib.error.HTTPError('u', 401, 'err', {}, Resp(b'{"error":"2FA required"}'))])
    assert w.signin(opener, 'a@b.c', 'pw') is None
    assert 'wfm_token' in capsys.readouterr().out


def test_a_good_signin_returns_the_user():
    w = load_check()
    opener = FakeOpener([b'<meta name="csrf-token" content="X">',
                         {'payload': {'user': {'ingameName': 'SampleTennoIX'}}}])
    user = w.signin(opener, 'a@b.c', 'pw')
    assert user['ingameName'] == 'SampleTennoIX'


def test_the_public_checker_never_asks_for_a_code():
    src = open(CHECK_PY, encoding='utf-8').read()
    for banned in ('getpass', 'input(', 'WFM_VERIFY_CODE'):
        assert banned not in src, banned
    assert 'never asks' in src          # the policy line ships with the script


def test_the_example_secrets_file_documents_the_browser_session():
    example = json.load(open(os.path.join(REPO, 'secrets.example.json'), encoding='utf-8'))
    assert 'wfm_token' in example
    blob = json.dumps(example).lower()
    assert 'alecaframe' in blob and 'never asked for' in blob
