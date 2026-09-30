"""Phase 6 worked examples, executed: Heat, the pool, the riders, the preset refusal.

    python design/_planner/phase6_examples.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from builds import api, buffs, data, mechanics  # noqa: E402


def _best(db, name):
    rows = [r for r in db['mods'].values() if (r.get('name') or '') == name]
    return max(rows, key=lambda r: r.get('max_rank') or 0) if rows else None


def _weapon(db, mods, options=None):
    equipment = next(eid for eid, row in sorted(db['equipment'].items())
                     if row.get('name') == 'Braton Prime' and row.get('kind') == 'primary')
    build = {'config': 'A', 'equipment_id': equipment, 'equipment_rank': 30, 'orokin': True,
             'mastery_rank': 30,
             'slots': [{'kind': 'normal', 'index': i, 'polarity': None,
                        'mod': {'id': mid, 'rank': rank}} for i, (mid, rank) in enumerate(mods)]}
    return api.compute(build, db, options)


def main():
    db = data.load(os.path.join(REPO, 'data', 'build_data.json'))
    ser = _best(db, 'Serration')
    storm = _best(db, 'Stormbringer')
    infected = _best(db, 'Infected Clip')
    ks = _best(db, 'Kill Switch')
    serration = (ser['id'], ser.get('max_rank') or 0)

    print('== 6.4 Heat armour strip, stated (wiki: multiplicative with corrosive) ==')
    base = {'target_faction': 'grineer', 'target': {'protection': 'health', 'armor': 900}}
    for strip in (None, 0, 15, 50, 35):
        target = dict(base['target'])
        if strip is not None:
            target['heat_strip'] = strip
        out = _weapon(db, [serration], {'context': {'target_faction': 'grineer', 'target': target}})
        row = [c for c in out['conditions'] if c['condition'] in ('heat', 'target_damage')]
        block = out['result']['target_damage']
        print('strip=%-5s conditions=%s armour_effective=%s' % (
            strip, [(c['condition'], c['state'], c.get('unsupported_code')) for c in row],
            (block or {}).get('armor', {}).get('effective')))
    out = _weapon(db, [serration, (storm['id'], storm.get('max_rank') or 0)],
                  {'context': {'target_faction': 'grineer',
                               'target': {'protection': 'health', 'armor': 900,
                                          'corrosive_stacks': 4, 'heat_strip': 50}}})
    print('corrosive 4 + heat 50: effective=%s steps=%s' % (
        out['result']['target_damage']['armor']['effective'],
        [r['value'] for r in out['result']['traces']['target_damage.impact']['modifiers']
         if r.get('category') == 'mitigation_input']))

    print('\n== 6.6 the stated pool ==')
    out = _weapon(db, [serration], {'context': {'target_faction': 'grineer',
                                                'target': {'protection': 'health', 'armor': 900,
                                                           'health': 5000}}})
    print('pool block:', json.dumps(out['result']['pool']))
    print('shots_to_kill headline:', out['result']['stats']['shots_to_kill'])
    for label, target in (('no pool', {'protection': 'health', 'armor': 900}),
                          ('wrong pool for the landing',
                           {'protection': 'health', 'armor': 900, 'shields': 400}),
                          ('pool but no resolved path',
                           {'protection': 'health', 'health': 5000})):
        out = _weapon(db, [serration], {'context': {'target_faction': 'grineer', 'target': target}})
        rows = [c for c in out['conditions'] if c['condition'] == 'pool']
        print('%-26s pool row=%s key_present=%s shots=%s' % (
            label, [(c['state'], c.get('unsupported_code')) for c in rows],
            'pool' in out['result'], out['result']['stats'].get('shots_to_kill')))

    print('\n== 6.3 the rider family (stated state only) ==')
    out = _weapon(db, [serration, (ks['id'], 3)], {'context': {'buffs': {'on_kill': {'stacks': 1}}}})
    rider = out['result']['riders'][0]
    print('Kill Switch (single stack, no clause):', json.dumps({k: rider[k] for k in
          ('stat', 'cap', 'per_stack', 'contribution', 'applied', 'state')}))
    print('  reload_time %s (base 2.15 / 1.5)' % out['result']['stats']['reload_time'])
    print('  trace rows:', [(r.get('source'), r.get('condition'), r.get('stacks'))
                             for r in out['result']['traces']['reload_time']['modifiers']])
    out = _weapon(db, [serration, (ks['id'], 3)], {'context': {'buffs': {'on_kill': {'uptime': 0.5,
                                                                                   'stacks': 1}}}})
    print('averaged:', out['result']['riders'][0]['mode'],
          out['result']['riders'][0]['contribution'],
          '| assumption:', out['result']['riders'][0]['assumption'])
    out = _weapon(db, [serration, (ks['id'], 3)], {'context': {'buffs': {'on_kill': {'stacks': 2}}}})
    print('over the single stack cap:', out['result']['riders'][0]['state'],
          '|', out['result']['riders'][0]['reason'])
    print('enabled rider stats (the registry declaration):', mechanics.rider_stats())

    print('\n== 6.5 the preset gap ==')
    out = _weapon(db, [serration], {'context': {'target': {'preset': 'level-100-heavy-gunner'}}})
    row = [c for c in out['conditions'] if c['condition'] == 'target_damage'][0]
    print(json.dumps({k: row.get(k) for k in ('state', 'unsupported_code', 'reason')}, indent=1))
    print('phase 1 numbers still answer:', out['result']['stats']['damage_per_shot'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
