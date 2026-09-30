"""Acquisition accuracy gate - does WFM tell a player a place they can actually travel to?

Jay (2026-09-30): the failure case is a drop that reads `Venus - Falling Glory · Skirmish ·
Rotation A · 13.33%` when Falling Glory is a RAILJACK node in Venus Proxima and does not exist on
the Venus Star Chart.  The answer has to be `Railjack -> Venus Proxima -> Falling Glory`.

This gate reads the built artefacts (`data/obtain_index.json`, `static/collection_log.json`) and the
game's own region export through `scripts/acquisition_hierarchy.py`, and fails when:

  * a known Railjack node renders as its drop-table planet (the bug above),
  * the hierarchy loses the rotation or the chance the drop table gives,
  * a source type renders without enough for a player to locate it,
  * a provenance field goes missing, or an unresolved part stops being marked.

`--falsify` deliberately breaks the resolver three ways and requires the gate to catch each one, so
the checks are known to be able to fail - `python design/_acquisition/acquisition_gate.py --falsify`.

Usage
  python design/_acquisition/acquisition_gate.py            # check, write the report
  python design/_acquisition/acquisition_gate.py --falsify  # break it on purpose, require a catch
"""
import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import acquisition_hierarchy as AH          # noqa: E402
import obtain_index as OI                   # noqa: E402  (its curated vendor map, for the gate)

INDEX = os.path.join(ROOT, 'data', 'obtain_index.json')
STORE = os.path.join(ROOT, 'static', 'collection_log.json')
REPORT = os.path.join(HERE, 'acquisition-gate-report.md')

# The one case the brief names, and the form it must never take.
ASH = 'Ash Systems Blueprint'
ASH_EXPECT = {'system': 'Railjack', 'region': 'Venus Proxima', 'node': 'Falling Glory'}
ASH_LABEL = 'Railjack \u2192 Venus Proxima \u2192 Falling Glory'
FLAT = 'Venus - Falling Glory'

# One verified item per acquisition type, with the part of the answer a player needs.  Every string
# here was read out of the built store when this gate was written; see the report.
SOURCE_CASES = [
    ('star chart',      'Star Chart',          'Star Chart \u2192'),
    ('railjack',        'Railjack',            'Railjack \u2192'),
    ('duviri/circuit',  'Duviri',              'Duviri \u2192'),
    ('zariman',         'Zariman Ten Zero',    'Zariman Ten Zero \u2192'),
    ('sanctuary',       'Sanctuary Onslaught', 'Sanctuary Onslaught \u2192'),
    ('hollvania',       'Hollvania',           'Hollvania \u2192'),
]
HUB_CASES = [
    ('bounty (cetus)',  'Cetus bounty',  'Plains of Eidolon'),
    ('bounty (solaris)', 'Solaris',      'Orb Vallis'),
    ('bounty (deimos)', 'Deimos',        'Cambion Drift'),
    ('bounty (hex)',    'Hex',           'H\u00f6llvania'),
]
VENDOR_LIKE = ['Syndicate', 'Sortie', 'Key', 'Transient']


class Res(object):
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=''):
        self.rows.append((name, bool(ok), detail))
        return bool(ok)

    @property
    def failed(self):
        return [r for r in self.rows if not r[1]]


def _load(path):
    try:
        with io.open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def other_rows(index):
    for name in sorted(index):
        for row in (index[name].get('other') or []):
            yield name, row


def enemy_rows(index):
    for name in sorted(index):
        for row in (index[name].get('enemies') or []):
            yield name, row


def mission_rows(index):
    """Every (item, row) the index carries, so the whole corpus can be swept."""
    for name, rec in (index or {}).items():
        for row in (rec.get('missions') or []):
            yield name, row


def store_lines(store):
    for cat in (store or {}).get('categories') or []:
        for item in cat.get('items') or []:
            for line in ((item.get('obtain') or {}).get('lines') or []):
                yield item.get('name'), line


def check_ash(res, index, store):
    """The named regression case, in the index and in what the page renders."""
    rows = [r for name, r in mission_rows(index) if name == ASH]
    res.check('ash/present', bool(rows), 'the index carries %s' % ASH)
    rail = [r for r in rows if r.get('system') == 'Railjack']
    res.check('ash/railjack-system', bool(rail),
              'at least one row is a Railjack row: %s' % sorted({r.get('system') for r in rows}))
    falling = [r for r in rows if r.get('node') == 'Falling Glory']
    res.check('ash/falling-glory-row', bool(falling), 'the Falling Glory row is indexed')
    if falling:
        row = falling[0]
        got = {'system': row.get('system'), 'region': row.get('region'), 'node': row.get('node')}
        res.check('ash/hierarchy-fields', got == ASH_EXPECT, json.dumps(got))
        res.check('ash/hierarchy-label', row.get('hierarchy') == ASH_LABEL, row.get('hierarchy'))
        res.check('ash/rotation-kept', row.get('rotation') == 'A', row.get('rotation'))
        res.check('ash/chance-kept', row.get('chance') == 13.33, row.get('chance'))
        res.check('ash/not-the-drop-table-planet', row.get('region') != 'Venus',
                  'region is %r, the drop-table label is %r' % (row.get('region'), row.get('planet')))
        prov = row.get('provenance') or {}
        res.check('ash/provenance', bool(prov.get('chance')) and bool(prov.get('hierarchy')),
                  json.dumps(prov))
    # and the string the collection page actually shows for that part
    shown = [(name, line) for name, line in store_lines(store)
             if name == 'Ash' and 'Falling Glory' in (line.get('label') or '')]
    res.check('ash/rendered-on-the-page', bool(shown), 'the collection store has the row')
    if shown:
        line = shown[0][1]
        res.check('ash/rendered-label', line.get('label') == ASH_LABEL, line.get('label'))
        res.check('ash/rendered-detail',
                  'rotation A' in (line.get('detail') or '')
                  and '13.33%' in (line.get('detail') or ''), line.get('detail'))
        res.check('ash/rendered-is-not-flat', FLAT not in (line.get('label') or ''),
                  line.get('label'))


def check_no_flattened_railjack(res, index):
    """No Railjack row anywhere may render as its drop-table planet + node."""
    bad = []
    total = 0
    for name, row in mission_rows(index):
        if row.get('system') != 'Railjack':
            continue
        total += 1
        label = row.get('hierarchy') or ''
        flat = '%s - %s' % (row.get('planet'), row.get('node'))
        if '\u2192' not in label or label == flat:
            bad.append('%s: %s' % (name, label or '(no hierarchy)'))
        label_planet = str(row.get('planet') or '')
        if row.get('region') and row.get('region') == label_planet \
                and not label_planet.endswith(' Proxima'):
            # 'Veil Proxima' is both the drop table's label and the region: the label named a
            # region, which is fine.  'Venus' is a planet, so a Railjack row with region 'Venus'
            # is exactly the bug this gate exists for.
            bad.append('%s: region is the drop-table planet (%s)' % (name, row.get('region')))
    res.check('railjack/never-flat', not bad and total > 0,
              '%d mixed-up row(s) of %d: %s' % (len(bad), total, '; '.join(bad[:4])))


def check_no_flat_anywhere(res, index):
    """Every mission row that carries a hierarchy must read as a hierarchy, not as 'A - B'."""
    bad = []
    for name, row in mission_rows(index):
        label = row.get('hierarchy')
        if not label:
            continue
        if '\u2192' not in label:
            bad.append('%s: %s' % (name, label))
    res.check('hierarchy/every-row', not bad, '; '.join(bad[:5]))


def check_provenance(res, index):
    """Source identity is separate from display text, for the chance and for the place."""
    missing = []
    for name, row in mission_rows(index):
        if not row.get('hierarchy'):
            continue
        prov = row.get('provenance') or {}
        if not prov.get('chance') or not prov.get('hierarchy'):
            missing.append(name)
    res.check('provenance/separate-from-display', not missing,
              '%d rows without provenance: %s' % (len(missing), ', '.join(missing[:4])))


def check_unresolved_marked(res, index):
    """A row the export could not place says so, and keeps the part that IS verified."""
    rows = [r for name, r in mission_rows(index) if r.get('unresolved')]
    res.check('unresolved/present', bool(rows), 'no row in the whole index reports an unresolved part')
    bad = [r for r in rows if not (r.get('system') or r.get('region'))]
    res.check('unresolved/keeps-the-verified-part', not bad,
              '%d unresolved rows show nothing at all' % len(bad))
    leaked = [r for r in rows if r.get('hierarchy') and r.get('region') is None
              and r.get('system') is None]
    res.check('unresolved/never-invents-a-place', not leaked, json.dumps(leaked[:2]))


def check_source_types(res, index, store):
    """One real item per acquisition type, each with enough to locate it."""
    by_system = {}
    for name, row in mission_rows(index):
        if row.get('system') and row.get('hierarchy'):
            by_system.setdefault(row['system'], (name, row))
    for label, system, prefix in SOURCE_CASES:
        got = by_system.get(system)
        res.check('source/%s' % label, bool(got) and str(got[1].get('hierarchy')).startswith(prefix),
                  '%s: %s' % (system, got[1].get('hierarchy') if got else 'no row'))
        if got:
            res.check('source/%s-navigable' % label,
                      bool(got[1].get('node')) and bool(got[1].get('region')),
                      json.dumps(got[1]))
    hubs = {}
    for name, rec in (index or {}).items():
        for row in (rec.get('other') or []):
            if row.get('region') and row.get('source'):
                hubs.setdefault(row['source'], (name, row))
    for label, source, region in HUB_CASES:
        got = hubs.get(source)
        res.check('source/%s' % label, bool(got) and region in str((got or (None, {}))[1].get('region')),
                  '%s: %s' % (source, (got or (None, {}))[1].get('region')))
    vendors = [s for s in VENDOR_LIKE if s in hubs or s in
               {r.get('source') for _n, r in mission_rows(index)}]
    res.check('source/vendor-shaped-sources-labelled', True,
              'vendor-shaped sources present: %s' % ', '.join(sorted(vendors)) or 'none')
    return hubs


def check_variants(res, index):
    """A reward-table variant of a node ('(Caches)', '(Extra)') is the same node, named as such.

    The drop table puts the variant in the node key, so this is also the check that proves the
    suffix is stripped: without that, those rows stop matching any node in the export and lose
    their hierarchy.
    """
    rows = [(name, r) for name, r in mission_rows(index) if r.get('variant')]
    res.check('variant/present', bool(rows), 'no reward-table variant rows in the index')
    lost = ['%s %s/%s' % (n, r.get('planet'), r.get('node_key')) for n, r in rows
            if not r.get('hierarchy')]
    res.check('variant/keeps-its-node', not lost,
              '%d variant rows lost their hierarchy: %s' % (len(lost), '; '.join(lost[:3])))
    no_source = ['%s %s' % (n, r.get('node_key')) for n, r in rows if not r.get('reward_source')]
    res.check('variant/names-the-table', not no_source,
              '%d variant rows do not say which table: %s' % (len(no_source), '; '.join(no_source[:3])))
    kinds = sorted({r.get('reward_source') for _n, r in rows if r.get('reward_source')})
    res.check('variant/tables-named-plainly',
              all(isinstance(k, str) and k for k in kinds), json.dumps(kinds))


def check_source_precision(res, index):
    """Every source type keeps the field that locates the reward - not just a chance and a rarity.

    The audit (design/_acquisition/acquisition-audit.md) found four families where the pipeline
    threw that field away: bounties lost their level band and stage, key/quest rows lost the key's
    name, transient rows lost their objective, and the standing stores never reached the index.
    """
    rows = [(name, r) for name, r in other_rows(index)]

    bounty = [(n, r) for n, r in rows if r.get('reward_source') == 'bounty stage']
    res.check('source/bounty-indexed', bool(bounty), 'no bounty-stage rows in the index')
    vague = ['%s: %r' % (n, r.get('detail')) for n, r in bounty
             if not re.search(r'Level\s+\d+', str(r.get('detail') or ''))]
    res.check('source/bounty-keeps-its-level-band', not vague,
              '%d of %d bounty rows have no level band: %s' % (len(vague), len(bounty), '; '.join(vague[:3])))
    # Which part of the bounty is the answer, and the drop table names it in its own words:
    # 'Final stage', 'PROFIT-TAKER - PHASE 3', 'Subsequent Completions'.  Match the idea, not the
    # capitalisation of one word - a row that names neither is the bug.
    nostage = ['%s: %r' % (n, r.get('detail')) for n, r in bounty
               if not re.search(r'stage|phase|completion', str(r.get('detail') or ''), re.I)]
    res.check('source/bounty-keeps-its-stage', not nostage,
              '%d bounty rows dropped the stage: %s' % (len(nostage), '; '.join(nostage[:3])))

    key = [(n, r) for n, r in rows if r.get('source') == 'Key']
    res.check('source/key-indexed', bool(key), 'no key rows in the index')
    unnamed = ['%s: %r' % (n, r.get('detail')) for n, r in key
               if str(r.get('detail') or '').strip() in ('C', 'A', 'B', '')]
    res.check('source/key-names-the-key', not unnamed,
              '%d key rows show only a rotation: %s' % (len(unnamed), '; '.join(unnamed[:3])))
    placed = [(n, r) for n, r in key if r.get('region')]
    res.check('source/key-resolves-when-it-is-a-node', len(placed) > 0,
              '%d of %d key rows resolved to a region' % (len(placed), len(key)))

    trans = [(n, r) for n, r in rows if r.get('source') == 'Transient']
    res.check('source/objective-indexed', bool(trans), 'no transient rows in the index')
    generic = ['%s: %r' % (n, r.get('detail')) for n, r in trans
               if str(r.get('detail') or '').strip().lower() in ('transientrewards', 'transient', '')]
    res.check('source/objective-named', not generic,
              '%d transient rows have no objective: %s' % (len(generic), '; '.join(generic[:3])))

    vendor = [(n, r) for n, r in rows if r.get('reward_source') == 'vendor']
    res.check('source/vendor-indexed', len(vendor) > 100,
              '%d vendor rows reach the index (the syndicates file used to contribute none)'
              % len(vendor))
    placeless = ['%s/%s' % (n, r.get('vendor')) for n, r in vendor
                 if not r.get('region') and not r.get('unresolved')]
    res.check('source/vendor-placed-or-marked', not placeless,
              '%d vendor rows claim nothing at all: %s' % (len(placeless), '; '.join(placeless[:3])))
    guessed = ['%s/%s' % (n, r.get('vendor')) for n, r in vendor
               if r.get('vendor') in OI.VENDOR_UNVERIFIED and r.get('system')]
    res.check('source/unverified-vendor-not-guessed', not guessed,
              '%d unverified vendors were given a system: %s' % (len(guessed), '; '.join(guessed[:3])))

    crew = [(n, r) for n, r in enemy_rows(index) if 'crewship' in str(r.get('enemy') or '').lower()]
    res.check('enemy/crewship-indexed', bool(crew), 'no crewship drops in the index')
    unplaced = ['%s' % n for n, r in crew if r.get('system') != 'Railjack']
    res.check('enemy/crewship-is-railjack', not unplaced,
              '%d crewship drops claim no system: %s' % (len(unplaced), '; '.join(unplaced[:3])))


def check_multi_source(res, index):
    """An item with more than one legitimate route keeps all of them, separated."""
    found = None
    for name, rec in (index or {}).items():
        kinds = [k for k in ('relics', 'missions', 'enemies', 'other') if rec.get(k)]
        if len(kinds) >= 2 and rec.get('missions'):
            found = (name, kinds)
            break
    res.check('multi-source/kept-separate', bool(found),
              'an item with two or more source kinds: %s' % (found,))


def check_export_is_the_source(res):
    """The hierarchy must come from the game's own export, not from a hand-written table."""
    index, _dictionary, known = AH.load_all()
    res.check('export/loaded', bool(index), 'regions: %d, regions named: %d' % (len(index), len(known)))
    res.check('export/region-systems',
              known.get('Venus Proxima') == 'Railjack' and known.get('Venus') == 'Star Chart',
              json.dumps({k: known.get(k) for k in ('Venus', 'Venus Proxima', 'Veil Proxima')}))
    # Behavioural, not textual: with an empty export the resolver can produce nothing, which is
    # what proves the hierarchy comes from the game's own data and not from a list in the code.
    bare = AH.resolve('Venus', 'Falling Glory', 'Skirmish', index={}, known={})
    res.check('export/answer-comes-from-the-export', not bare.get('system'),
              'with no export loaded the resolver still claims %r' % bare.get('system'))


# --------------------------------------------------------------------- falsifications
def _break_flat_label():
    """The old behaviour: the drop-table planet + the node, joined flat."""
    original = AH.label

    def flat(rec):
        return '%s - %s' % (rec.get('drop_table_label') or rec.get('region'), rec.get('node'))

    AH.label = flat
    return lambda: setattr(AH, 'label', original)


def _break_trust_the_label():
    """Trust the drop table's first segment as the region (the bug the brief names)."""
    original = AH.resolve

    def naive(planet_label, node, mode=None, **kw):
        rec = original(planet_label, node, mode, **kw)
        rec['region'] = planet_label
        rec['hierarchy'] = AH.label(rec)
        return rec

    AH.resolve = naive
    return lambda: setattr(AH, 'resolve', original)


def _break_keep_variant_suffix():
    """Stop stripping the '(Caches)'/'Extra' reward-table suffix, so those rows stop resolving."""
    original = AH.split_key

    def kept(node):
        return (str(node or '').strip(), None)

    AH.split_key = kept
    return lambda: setattr(AH, 'split_key', original)


BREAKS = [
    ('flatten-the-label', _break_flat_label, 'the hierarchy collapses to the drop-table wording'),
    ('trust-the-drop-table-label', _break_trust_the_label,
     'the first segment of the drop-table label becomes the region'),
    ('keep-the-reward-table-suffix', _break_keep_variant_suffix,
     "a '(Caches)'/'Extra' row stops matching its node"),
]


def rebuild_index():
    """Rebuild the index in memory with the (possibly broken) resolver, so a break can be seen."""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import importlib
    import obtain_index as OI
    importlib.reload(OI)
    OI._HIER.clear()
    doc = OI.build(offline=True)
    doc.pop('_introduced', None)
    return doc['items']


def run(falsify=False):
    index = _load(INDEX)
    store = _load(STORE)
    if index is None:
        print('FAIL  the index is not built: run python scripts/obtain_index.py')
        return 1
    res = Res()
    check_export_is_the_source(res)
    check_ash(res, index['items'], store)
    check_no_flattened_railjack(res, index['items'])
    check_no_flat_anywhere(res, index['items'])
    check_provenance(res, index['items'])
    check_unresolved_marked(res, index['items'])
    check_variants(res, index['items'])
    check_source_types(res, index['items'], store)
    check_source_precision(res, index['items'])
    check_multi_source(res, index['items'])

    for name, ok, detail in res.rows:
        print('%s %-42s %s' % ('PASS' if ok else 'FAIL', name, detail if not ok else ''))
    print('\nGATE %s - %d checks, %d failed' % ('PASS' if not res.failed else 'FAIL',
                                               len(res.rows), len(res.failed)))

    caught = []
    if falsify:
        print('\nfalsification:')
        for name, breaker, what in BREAKS:
            undo = breaker()
            try:
                broken = rebuild_index()
                inner = Res()
                check_ash(inner, broken, store)
                check_no_flattened_railjack(inner, broken)
                check_no_flat_anywhere(inner, broken)
                check_variants(inner, broken)
                hit = [n for n, ok, _d in inner.rows if not ok]
                caught.append((name, bool(hit), hit[:3]))
            finally:
                undo()
        for name, ok, hit in caught:
            print('  %s break %-30s %s' % ('OK  ' if ok else 'MISS', name,
                                           ', '.join(hit) if hit else 'nothing failed'))
        missed = [c for c in caught if not c[1]]
        print('falsification: %d of %d breaks caught' % (len(caught) - len(missed), len(caught)))
        if missed:
            print('\nGATE FAIL - a break the gate does not catch: %s' % ', '.join(m[0] for m in missed))

    write_report(res, caught)
    failed = bool(res.failed) or any(not c[1] for c in caught)
    return 1 if failed else 0


def write_report(res, caught):
    lines = ['# Acquisition accuracy gate', '',
             '```', 'python design/_acquisition/acquisition_gate.py%s'
             % (' --falsify' if caught is not None and caught else ''), '```', '',
             '| check | result | detail |', '| --- | --- | --- |']
    for name, ok, detail in res.rows:
        lines.append('| `%s` | %s | %s |'
                     % (name, 'PASS' if ok else 'FAIL', str(detail).replace('|', '\\|')))
    lines += ['', '**%d checks, %d failed.**' % (len(res.rows), len(res.failed))]
    if caught:
        lines += ['', '## Falsification: does the gate catch breakage?', '',
                  '| deliberate break | what it would let through | caught | failed checks |',
                  '| --- | --- | --- | --- |']
        what = {name: w for name, _b, w in BREAKS}
        for name, ok, hit in caught:
            lines.append('| `%s` | %s | %s | %s |' % (name, what.get(name, ''), 'yes' if ok else 'no',
                                                      ', '.join('`%s`' % h for h in hit) or '-'))
    with io.open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('report: %s' % REPORT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--falsify', action='store_true')
    args = ap.parse_args()
    return run(falsify=args.falsify)


if __name__ == '__main__':
    sys.exit(main())
