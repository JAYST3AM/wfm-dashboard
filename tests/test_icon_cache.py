"""scripts/icon_cache.py: URL->file rule, resume, --limit, --refresh and the index contract.

Offline by construction: the collection log is a fixture in tmp_path, the fetch is a plain
Python function injected into run_once() (urllib is never reached), and the output directory is
always under tmp_path - the repo's real data/ and static/colimg/ are never read or written.
The last block asserts the wiring: .gitignore, setup.py's PAGE_STEPS and static/collection.js
prefers icon_local over the remote icon.
"""
import json
import os
from types import SimpleNamespace

import pytest

from conftest import REPO, load_script, read_json

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 40
HTML = b'<html><body>not an image</body></html>'

LOG = {'version': 1, 'categories': [
    {'key': 'warframes', 'name': 'Warframes', 'items': [
        {'name': 'Ash', 'icon': 'https://cdn.warframestat.us/img/Ash.png'},
        {'name': 'Ash Prime', 'icon': 'https://cdn.warframestat.us/img/Ash.png'},
        {'name': 'Atlas', 'icon': 'https://cdn.warframestat.us/img/Atlas.png'},
    ]},
    {'key': 'primary', 'name': 'Primary', 'items': [
        {'name': 'Braton', 'icon': 'https://cdn.warframestat.us/img/Braton.png'},
        {'name': 'No Icon Item', 'icon': None},
    ]},
]}
ICONS = {'https://cdn.warframestat.us/img/Ash.png': PNG,
         'https://cdn.warframestat.us/img/Atlas.png': PNG,
         'https://cdn.warframestat.us/img/Braton.png': PNG}
NAMES = {'Ash.png', 'Atlas.png', 'Braton.png'}
WANT = 3
INDEX_KEYS = ['count', 'failed', 'files', 'schema', 'updated']
ASH_URL = 'https://cdn.warframestat.us/img/Ash.png'
ATLAS_URL = 'https://cdn.warframestat.us/img/Atlas.png'


@pytest.fixture
def ic(tmp_path, monkeypatch):
    """The script with DATA redirected into tmp_path and COLIMG kept out of the repo."""
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'collection_log.json').write_text(json.dumps(LOG), encoding='utf-8')
    mod = load_script('icon_cache', monkeypatch=monkeypatch, env={'WFM_DATA_DIR': str(data)})
    assert mod.DATA == str(data)
    out = tmp_path / 'colimg'
    monkeypatch.setattr(mod, 'COLIMG', str(out))       # the default must never reach the repo
    return SimpleNamespace(mod=mod, data=data, out=out, log=data / 'collection_log.json')


def fetcher(mapping, calls=None, exc=None):
    """Offline fetch_fn: fixture bytes for known URLs, else the injected error."""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if exc is not None:
            raise exc
        if url not in mapping:
            raise OSError('offline: no fixture for %s' % url)
        return 200, mapping[url]
    return fetch


def run(ic, **kw):
    """run_once against the fixture log, with an injected offline fetch."""
    kw.setdefault('fetch_fn', fetcher(ICONS))
    kw.setdefault('sleep_fn', lambda _s: None)
    return ic.mod.run_once(out_dir=str(ic.out), log_file=str(ic.log), **kw)


def disk(ic):
    return sorted(p.name for p in ic.out.iterdir()) if ic.out.exists() else []


def no_network(*_a, **_kw):
    raise AssertionError('the network was used although the run was offline')


# ---------------------------------------------------------------- URL -> file name
@pytest.mark.parametrize('url,name', [
    ('https://cdn.warframestat.us/img/Ash.png', 'Ash.png'),
    ('https://cdn.warframestat.us/img/OrionSirius.png', 'OrionSirius.png'),
    ('https://cdn.warframestat.us/img/AK47Weapon.png', 'AK47Weapon.png'),
    ('https://cdn.warframestat.us/img/ThanotechRifle.png', 'ThanotechRifle.png'),
    ('https://cdn.warframestat.us/img/Ash.png?v=2', 'Ash.png'),       # query ignored
    ('https://cdn.warframestat.us/img/sub/Deep.png', 'Deep.png'),     # last segment only
])
def test_url_basename_is_the_file_name(ic, url, name):
    assert ic.mod.file_name_for(url) == name


@pytest.mark.parametrize('url', ['', None, 7, 'Ash.png', 'https://cdn.warframestat.us/img/',
                                 'https://cdn.warframestat.us/img/a b.png',
                                 'https://cdn.warframestat.us/img/a%20b.png',
                                 'https://cdn.warframestat.us/img/%2e%2e.png',
                                 'https://cdn.warframestat.us/img/.hidden.png',
                                 'file:///etc/passwd', 'https:///img/Ash.png'])
def test_unusable_or_hostile_urls_get_no_file_name(ic, url):
    assert ic.mod.file_name_for(url) is None


def test_collect_wanted_reads_every_category_and_dedupes(ic):
    wanted, items, no_icon = ic.mod.collect_wanted(LOG)
    assert len(wanted) == WANT and set(wanted) == set(ICONS)
    assert wanted[ASH_URL] == 'Ash.png'
    assert (items, no_icon) == (5, 1)                  # 5 items, one has no icon at all
    assert ic.mod.collect_wanted(None) == ({}, 0, 0)   # a missing/foreign log never raises


def test_image_validation(ic):
    assert ic.mod.image_kind(PNG) == 'png'
    assert ic.mod.image_kind(b'GIF89a' + b'x' * 10) == 'gif'
    assert ic.mod.image_kind(b'\xff\xd8\xff\xe0' + b'x' * 10) == 'jpeg'
    assert ic.mod.image_kind(HTML) is None
    assert ic.mod.image_kind(b'') is None


# ---------------------------------------------------------------- the cache pass
def test_first_run_downloads_everything_and_writes_the_index(ic):
    result = run(ic, now=1700000000)
    c = result['counts']
    assert (c['want'], c['cached'], c['downloaded'], c['failed']) == (WANT, 0, WANT, 0)
    assert ic.mod.summary_line(c) == 'icon_cache: want 3 | cached 0 | downloaded 3 | failed 0'
    assert disk(ic) == sorted(NAMES | {'index.json'})
    assert all((ic.out / n).stat().st_size > 0 for n in NAMES)
    doc = read_json(ic.out / 'index.json')
    assert sorted(doc) == INDEX_KEYS                   # schema/updated/count/files/failed
    assert (doc['schema'], doc['updated'], doc['count']) == (1, 1700000000, WANT)
    assert doc['files'][ASH_URL] == {'file': 'Ash.png', 'bytes': len(PNG)}
    assert all(sorted(v) == ['bytes', 'file'] for v in doc['files'].values())
    assert doc['failed'] == []


def test_index_write_is_atomic_and_leaves_no_tmp(ic):
    run(ic, limit=1)
    assert (ic.out / 'index.json').exists()            # written even for a partial run
    assert not (ic.out / 'index.json.tmp').exists()
    assert not [n for n in disk(ic) if n.endswith('.tmp')]


def test_resume_skips_files_already_on_disk(ic):
    run(ic)
    calls = []
    second = run(ic, fetch_fn=fetcher(ICONS, calls=calls, exc=AssertionError('network used')))
    assert (second['counts']['downloaded'], second['counts']['cached']) == (0, WANT)
    assert calls == []                                 # not even a fetch was attempted
    assert read_json(ic.out / 'index.json')['count'] == WANT


def test_limit_bounds_a_single_run(ic):
    first = run(ic, limit=1)
    assert (first['counts']['downloaded'], first['counts']['cached'],
            first['counts']['left']) == (1, 0, WANT - 1)
    assert sorted(n for n in disk(ic) if n != 'index.json') == ['Ash.png']
    second = run(ic, limit=1)
    assert (second['counts']['downloaded'], second['counts']['cached']) == (1, 1)
    final = run(ic)
    assert (final['counts']['downloaded'], final['counts']['cached'],
            final['counts']['left']) == (1, 2, 0)


def test_refresh_re_downloads_present_files(ic):
    run(ic)
    calls = []
    again = run(ic, refresh=True, fetch_fn=fetcher(ICONS, calls=calls))
    assert again['counts']['downloaded'] == WANT and again['counts']['cached'] == WANT
    assert sorted(calls) == sorted(ICONS)
    assert not [n for n in disk(ic) if n.endswith('.tmp')]


def test_one_bad_icon_is_recorded_and_never_stops_the_run(ic):
    broken = dict(ICONS)
    del broken[ATLAS_URL]
    result = run(ic, fetch_fn=fetcher(broken))
    c = result['counts']
    assert (c['downloaded'], c['failed']) == (2, 1) and c['want'] == WANT
    assert not (ic.out / 'Atlas.png').exists()
    doc = read_json(ic.out / 'index.json')             # the index is still written
    assert doc['count'] == 2 and len(doc['failed']) == 1
    assert doc['failed'][0]['url'] == ATLAS_URL
    assert doc['failed'][0]['file'] == 'Atlas.png'
    assert doc['failed'][0]['reason'].startswith('OSError')
    assert os.path.exists(str(ic.out / 'Ash.png'))     # the good files went through


def test_a_non_image_body_is_never_written(ic):
    bad = dict(ICONS, **{ATLAS_URL: HTML})
    result = run(ic, fetch_fn=fetcher(bad))
    assert not (ic.out / 'Atlas.png').exists()
    assert result['counts']['downloaded'] == 2
    assert any('not an image' in f['reason'] for f in result['doc']['failed'])


def test_offline_never_calls_the_fetcher(ic):
    run(ic)
    os.remove(str(ic.out / 'Atlas.png'))
    result = run(ic, offline=True, fetch_fn=no_network)
    assert (result['counts']['downloaded'], result['counts']['cached'],
            result['counts']['missing']) == (0, 2, 1)
    assert read_json(ic.out / 'index.json')['count'] == 2


def test_dry_run_lists_the_work_and_writes_nothing(ic):
    calls = []
    result = run(ic, dry_run=True, fetch_fn=fetcher(ICONS, calls=calls))
    assert result['counts']['planned'] == WANT and len(result['would']) == WANT
    assert calls == [] and not ic.out.exists()


# ---------------------------------------------------------------- CLI
def test_main_prints_the_summary_first_and_a_resume_line(ic, monkeypatch, capsys):
    monkeypatch.setattr(ic.mod, 'fetch_bytes', lambda url, **kw: (200, ICONS[url]))
    assert ic.mod.main(['--once', '--out-dir', str(ic.out)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == \
        'icon_cache: want 3 | cached 0 | downloaded 3 | failed 0'
    monkeypatch.setattr(ic.mod, 'fetch_bytes', no_network)
    assert ic.mod.main(['--once', '--out-dir', str(ic.out)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == 'icon_cache: want 3 | cached 3 | downloaded 0 | failed 0'


def test_main_dry_run_writes_nothing(ic, monkeypatch, capsys):
    monkeypatch.setattr(ic.mod, 'fetch_bytes', no_network)
    assert ic.mod.main(['--dry-run', '--out-dir', str(ic.out)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == 'icon_cache: want 3 | cached 0 | downloaded 0 | failed 0'
    assert any('wrote nothing' in line for line in lines)
    assert not ic.out.exists()


def test_main_json_keeps_stdout_parseable(ic, monkeypatch, capsys):
    monkeypatch.setattr(ic.mod, 'fetch_bytes', lambda url, **kw: (200, ICONS[url]))
    assert ic.mod.main(['--json', '--out-dir', str(ic.out)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert sorted(doc) == INDEX_KEYS and doc['count'] == WANT


def test_missing_collection_log_reports_it_and_writes_nothing(ic, monkeypatch, capsys):
    os.remove(str(ic.log))
    monkeypatch.setattr(ic.mod, 'fetch_bytes', no_network)
    assert ic.mod.main(['--once', '--out-dir', str(ic.out)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == 'icon_cache: want 0 | cached 0 | downloaded 0 | failed 0'
    assert any('no collection log' in line for line in lines)
    assert not ic.out.exists()


def test_selftest_is_offline_and_exits_zero(ic, capsys):
    assert ic.mod.main(['--selftest']) == 0
    out = capsys.readouterr().out
    assert 'selftest: ' in out and '0 failed' in out
    assert not ic.out.exists()                         # selftest writes only under its own tmp


# ---------------------------------------------------------------- repo wiring
def test_repo_files_wire_the_cache_in():
    ignore = open(os.path.join(REPO, '.gitignore'), encoding='utf-8').read()
    assert 'static/colimg/' in ignore                   # derived data is never committed
    setup = load_script('setup')
    steps = [s[0] for s in setup.PAGE_STEPS]
    assert 'icon_cache.py' in steps
    assert steps.index('icon_cache.py') == steps.index('collection_log.py') + 1
    js = open(os.path.join(REPO, 'static', 'collection.js'), encoding='utf-8').read()
    assert 'safeUrl(it.icon_local) || safeUrl(it.icon)' in js   # own copy wins, CDN falls back
    assert "u.indexOf('/colimg/') === 0" in js                  # same-origin whitelist branch
    assert "img.addEventListener('error'" in js                 # letter tile stays the last resort
    assert "img.setAttribute('src', url)" in js
