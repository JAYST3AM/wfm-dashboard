"""Read the player's current in-game loadout — local only, read-only, never inferred.

The save is AlecaFrame's copy of the game's own data (`lastData.dat`, AES-encrypted JSON). This
module decrypts it through the existing `saveio` path, hands the result to the pure mapper in
`builds/player_import.py`, and caches the translated snapshot in `data/current_loadout.json`.

Everything here is deliberately boring: no polling, no watcher, no network, no writes to the save.
A read happens on request, the parsed snapshot is reused while it is fresh and the source file has
not changed, and every failure mode is a named state the UI can explain rather than an exception.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import saveio                                    # noqa: E402
from builds import data as build_data                         # noqa: E402
from builds import player_import                              # noqa: E402

CACHE_TTL_S = 60
SAVE_ENV = 'WFM_PLAYER_SAVE'
CACHE_ENV = 'WFM_PLAYER_CACHE'


def save_path():
    """The save to read: an explicit override (tests, fixtures) or the real AlecaFrame file."""
    override = os.environ.get(SAVE_ENV)
    if override:
        return override
    local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(local, 'AlecaFrame', 'lastData.dat')


def cache_path():
    return os.environ.get(CACHE_ENV) or os.path.join(ROOT, 'data', 'current_loadout.json')


# ------------------------------------------------------------------ reading

def _catalogue():
    return build_data.load()


def read_source():
    """Decrypt and map the save. Returns (state, snapshot) where state is one of the named
    failure modes the UI explains, or 'ok'."""
    path = save_path()
    if not os.path.exists(path):
        return ('missing', {'expected': path,
                            'message': 'No local source: WFM expected the AlecaFrame save.'})
    for attempt in (1, 2):
        try:
            save = saveio.load_normalised(path)
            break
        except PermissionError:
            if attempt == 2:
                return ('locked', {'expected': path,
                                   'message': 'The save is locked by another process.'})
            time.sleep(0.2)
        except Exception as e:                                     # malformed, unreadable, truncated
            return ('malformed', {'expected': path,
                                  'message': 'The save could not be read: %s' % str(e)[:120]})

    if not isinstance(save, dict) or not (save.get('LoadOutPresets') or save.get('Suits')):
        return ('no_build_data', {'expected': path,
                                  'message': 'Current build not available from this data source.'})

    mtime = int(os.path.getmtime(path))
    now = int(time.time())
    db = _catalogue()
    snapshot = player_import.import_loadout(save, db, source=os.path.basename(path),
                                            source_timestamp=mtime, imported_timestamp=now, now=now)
    snapshot['source_path'] = path
    # the engine's own view of what it could not model, so the UI can be honest about stats (§18)
    if not snapshot.get('categories'):
        return ('no_build_data', {'expected': path,
                                  'message': 'Current build not available from this data source.'})
    return ('ok', snapshot)


def _write_cache(payload):
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass                                          # a cache we cannot write is not an error


def _read_cache():
    try:
        with open(cache_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load(force=False):
    """The current-loadout payload: {state, snapshot, read_at, source_mtime, cached, refreshable}.

    Cached for CACHE_TTL_S seconds and reused only while the source file's mtime is unchanged,
    so a page load does not decrypt a 650 KB blob every time and a game session that changes the
    loadout is picked up on the next read.
    """
    path = save_path()
    try:
        mtime = int(os.path.getmtime(path))
    except OSError:
        mtime = None
    now = int(time.time())
    cached = _read_cache()
    if (not force and cached and cached.get('state') == 'ok'
            and cached.get('source_mtime') == mtime
            and isinstance(cached.get('read_at'), int)
            and now - cached['read_at'] < CACHE_TTL_S):
        out = dict(cached)
        out['cached'] = True
        out['snapshot']['freshness'] = player_import.freshness(
            out['source_mtime'], out.get('read_at'), now=now)
        return out

    state, payload = read_source()
    out = {'state': state, 'read_at': now, 'source_mtime': mtime,
           'refreshable': state != 'missing', 'cached': False}
    if state == 'ok':
        out['snapshot'] = payload
    else:
        out['detail'] = payload
        # keep the last good snapshot visible but labelled: a locked file is not a lost loadout
        if cached and cached.get('state') == 'ok' and cached.get('snapshot'):
            out['last_good'] = {'snapshot': cached['snapshot'], 'read_at': cached.get('read_at')}
    _write_cache(out)
    return out


def clone(category, config_name='A', master=None):
    """A planner document cloned from the CURRENT snapshot. Never mutates the snapshot."""
    payload = load()
    if payload.get('state') != 'ok':
        return {'ok': False, 'error': 'no current build is available',
                'state': payload.get('state'), 'detail': payload.get('detail')}
    snapshot = json.loads(json.dumps(payload['snapshot']))       # clone data, not a reference
    out = player_import.clone_to_planner(snapshot, category, config_name, master=master)
    out['source'] = snapshot.get('source')
    out['source_timestamp'] = snapshot.get('source_timestamp')
    out['freshness'] = snapshot.get('freshness')
    return out


if __name__ == '__main__':                                        # tiny self-test / manual probe
    p = load(force=True)
    if p['state'] != 'ok':
        print('state:', p['state'], '|', (p.get('detail') or {}).get('message'))
        raise SystemExit(1)
    snap = p['snapshot']
    print('source:', snap['source'], '|', snap['freshness']['label'])
    for category, imported in sorted(snap['categories'].items()):
        eq = (imported.get('equipment') or {}).get('value') or {}
        print('  %-16s %-22s config=%s rank=%s' % (category, eq.get('name'),
              (imported.get('config') or {}).get('label'),
              (imported.get('equipment_rank') or {}).get('value')))
    print('unknown fields:', len(snap['unknown_fields']), '| unmapped:', len(snap['unmapped']))
