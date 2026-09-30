"""The Phase 6 migration probe: canonical JSON for a corpus of builds x contexts.

Run from a tree root with the repo's python:

    python design/_planner/phase6_probe.py --db <abs path to build_data.json> [--out file]

The output is the engine's whole answer per case (every key the phases pin), so two trees can be
diffed byte for byte by `phase6_migration.py`. Nothing here reads the tree it runs in except the
engine itself - that is the point: same database, same cases, two engines.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from builds import api, data  # noqa: E402


def _best_mod(db, name):
    best = None
    for row in db['mods'].values():
        if (row.get('name') or '') == name:
            if best is None or (row.get('max_rank') or 0) > (best.get('max_rank') or 0):
                best = row
    return best


def _equip(db, name, kind):
    for eid, row in sorted(db['equipment'].items()):
        if row.get('name') == name and row.get('kind') == kind:
            return eid
    return None


def build(db):
    """The fixture corpus: (case id, equipment, [(mod name, rank)], options)."""
    rifle = _equip(db, 'Braton Prime', 'primary') or _equip(db, 'Soma Prime', 'primary')
    frame = _equip(db, 'Excalibur', 'warframe')
    melee = next((eid for eid, row in sorted(db['equipment'].items())
                  if row.get('kind') == 'melee'), None)
    serration = _best_mod(db, 'Serration')
    chamber = _best_mod(db, 'Galvanized Chamber')
    vit = _best_mod(db, 'Umbral Vitality')
    fib = _best_mod(db, 'Umbral Fiber')
    inten = _best_mod(db, 'Umbral Intensify')
    storm = _best_mod(db, 'Stormbringer')
    infected = _best_mod(db, 'Infected Clip')

    def m(row):
        return (row['id'], row.get('max_rank') or 0)

    cool = [m(serration)]
    corrosive = [m(serration), m(storm), m(infected)]
    rider = [m(serration), m(chamber)]

    cases = []
    for label, ctx in (
            ('no-context', None),
            ('faction-only', {'context': {'target_faction': 'grineer'}}),
            ('first-shot-1', {'context': {'target_faction': 'grineer',
                                          'attack': {'shot_index': 1}}}),
            ('first-shot-2', {'context': {'target_faction': 'grineer',
                                          'attack': {'shot_index': 2}}}),
            ('faction-health-no-armour', {'context': {
                'target_faction': 'grineer',
                'target': {'protection': 'health', 'viral_stacks': 6}}}),
            ('viral-only', {'context': {'target': {'protection': 'health', 'viral_stacks': 6}}}),
            ('viral-junk', {'context': {'target': {'protection': 'health', 'viral_stacks': 'lots'}}}),
            ('viral-immune', {'context': {'target': {'protection': 'health', 'viral_stacks': 4,
                                                     'immune_to': 'viral'}}}),
            ('corrosive-0-alone', {'context': {'target': {'corrosive_stacks': 0}}}),
            ('armour-missing', {'context': {'target_faction': 'grineer',
                                            'target': {'protection': 'health'}}}),
            ('armour-junk', {'context': {'target_faction': 'grineer',
                                         'target': {'protection': 'health', 'armor': 'lots'}}}),
            ('armour-negative', {'context': {'target_faction': 'grineer',
                                             'target': {'protection': 'health', 'armor': -5}}}),
            ('layer-junk', {'context': {'target_faction': 'grineer',
                                        'target': {'protection': 'hull', 'armor': 300}}}),
            ('faction-junk', {'context': {'target_faction': 'wally',
                                          'target': {'protection': 'health', 'armor': 300}}}),
            ('alias-conflict', {'context': {'target_faction': 'grineer',
                                            'target': {'protection': 'health', 'armor': 300,
                                                       'armour': 900}}}),
            ('removed-vocabulary', {'context': {'target': {'health_type': 'ferrite',
                                                           'armor_type': 'alloy'}}}),
            ('unused-pools', {'context': {'target': {'health': 1000, 'shields': 500}}}),
            ('rider-none', {'context': {'buffs': {'on_kill': {'stacks': 0}}}}),
            ('rider-3', {'context': {'buffs': {'on_kill': {'stacks': 3}}}}),
            ('rider-average', {'context': {'buffs': {'on_kill': {'stacks': 5, 'uptime': 0.65}}}}),
            ('rider-uptime-only', {'context': {'buffs': {'on_kill': {'uptime': 0.65}}}}),
            ('rider-over-cap', {'context': {'buffs': {'on_kill': {'stacks': 99}}}}),
            ('rider-junk', {'context': {'buffs': {'on_kill': {'stacks': 2.5}}}}),
            ('rider-extra-key', {'context': {'buffs': {'on_kill': {'stacks': 3, 'kills': 4}}}}),
            ('bool-yes', {'orokin': 'yes'} if False else {'orokin': True}),
            ('strict-target', {'context': {'target_faction': 'grineer',
                                           'target': {'protection': 'health'}}, 'strict': True}),
            ('hypothetical', {'context': {'target_faction': 'grineer'}, 'hypothetical': True}),
    ):
        cases.append({'id': label, 'mods': cool, 'options': ctx})
    for armour in (0, 300, 675, 900, 2700, 3000):
        cases.append({'id': 'armour-%d' % armour, 'mods': cool,
                      'options': {'context': {'target_faction': 'grineer',
                                              'target': {'protection': 'health',
                                                         'armor': armour}}}})
    for stacks in (1, 4, 10, 11):
        cases.append({'id': 'corrosive-%d' % stacks, 'mods': corrosive,
                      'options': {'context': {'target_faction': 'grineer',
                                              'target': {'protection': 'health', 'armor': 900,
                                                         'corrosive_stacks': stacks}}}})
    for layer in ('shields', 'overguard'):
        cases.append({'id': 'layer-' + layer, 'mods': cool,
                      'options': {'context': {'target_faction': 'grineer',
                                              'target': {'protection': layer, 'armor': 900}}}})
    cases.append({'id': 'no-armour-context', 'mods': corrosive, 'options': None})
    cases.append({'id': 'melee-plain', 'mods': [], 'equipment': melee, 'options': None})
    for label, mods in (('umbral-1', [m(vit)]), ('umbral-2', [m(vit), m(fib)]),
                        ('umbral-3', [m(vit), m(fib), m(inten)]),
                        ('umbral-duplicate', [m(vit), m(vit)]),
                        ('umbral-rank-invalid', [m(vit), (fib['id'], 99)])):
        cases.append({'id': label, 'mods': mods, 'equipment': frame, 'options': None})
    cases.append({'id': 'rider-build-plain', 'mods': rider, 'options': None})
    cases.append({'id': 'rider-build-stated', 'mods': rider,
                  'options': {'context': {'buffs': {'on_kill': {'stacks': 3}}},
                              'strict': True}})
    for case in cases:
        case.setdefault('equipment', rifle)
    return cases


def _canonical(out):
    return json.dumps(out, sort_keys=True, default=str, separators=(',', ':'))


def main(argv):
    db_path = None
    out_path = None
    for i, arg in enumerate(argv):
        if arg == '--db':
            db_path = argv[i + 1]
        if arg == '--out':
            out_path = argv[i + 1]
    if not db_path:
        db_path = os.path.join(REPO, 'data', 'build_data.json')
    db = data.load(db_path)
    report = {}
    for case in build(db):
        payload = {'config': 'A', 'equipment_id': case['equipment'], 'equipment_rank': 30,
                   'orokin': True, 'mastery_rank': 30, 'slots': []}
        for index, (mod_id, rank) in enumerate(case['mods']):
            payload['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                                     'mod': {'id': mod_id, 'rank': rank}})
        out = api.compute(payload, db, case['options'])
        report[case['id']] = _canonical(out)
    text = json.dumps(report, sort_keys=True, indent=1)
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as handle:
            handle.write(text)
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
