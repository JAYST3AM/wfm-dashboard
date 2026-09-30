"""Phase 5 worked examples: the before/after numbers the report quotes. Read-only."""
import sys
sys.path.insert(0, r'F:/VSC Projects/wfm-dashboard')
from builds import api, data

DB = data.load(r'F:/VSC Projects/wfm-dashboard/data/build_data.json')
WEAPON = '/Lotus/Weapons/Tenno/Rifle/BratonPrime'
SERRATION = '/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod'
CHAMBER = '/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod'


def best(name):
    out = None
    for row in DB['mods'].values():
        if (row.get('name') or '') == name:
            if out is None or (row.get('max_rank') or 0) > (out.get('max_rank') or 0):
                out = row
    return out


def build(mods, equip=WEAPON):
    return {'config': 'A', 'equipment_id': equip, 'equipment_rank': 30, 'orokin': True,
            'mastery_rank': 30,
            'slots': [{'kind': 'normal', 'index': i, 'polarity': None,
                       'mod': {'id': mid, 'rank': rank}} for i, (mid, rank) in enumerate(mods)]}


SER = (SERRATION, best('Serration').get('max_rank'))
CH = (CHAMBER, best('Galvanized Chamber').get('max_rank'))


def line(label, out):
    res = out.get('result') or {}
    stats = res.get('stats') or {}
    td = res.get('target_damage')
    riders = res.get('riders') or []
    ev = out.get('evaluation') or {}
    print('%-46s | %8s | %8s | %8s | %-28s | %s' % (
        label,
        stats.get('damage_per_shot'),
        stats.get('multishot'),
        (td or {}).get('per_projectile_total'),
        (('riders: ' + ', '.join('%s/%s/%s' % (r.get('stat'), r.get('state'), r.get('contribution'))
                                 for r in riders)) if riders else '-'),
        ev.get('state') + (' withheld=' + ','.join(ev.get('withheld') or []) if ev.get('withheld') else '')))


print('== A. the target path (no mods beyond Serration R10) ==')
print('%-46s | %8s | %8s | %8s | %-28s | %s' % ('case', 'dmg/shot', 'multi', 'vs target', 'riders', 'evaluation'))
line('no context (Phase 1 only)', api.compute(build([SER]), DB))
line('grineer / health / armour 300', api.compute(build([SER]), DB, {'context': {
    'target_faction': 'grineer', 'target': {'protection': 'health', 'armor': 300}}}))
line('grineer / health / armour 900', api.compute(build([SER]), DB, {'context': {
    'target_faction': 'grineer', 'target': {'protection': 'health', 'armor': 900}}}))
line('grineer / health / armour 900, corrosive 4', api.compute(build([SER]), DB, {'context': {
    'target_faction': 'grineer',
    'target': {'protection': 'health', 'armor': 900, 'corrosive_stacks': 4}}}))
line('grineer / health / armour 900 (no stacks stated)', api.compute(build([SER]), DB, {'context': {
    'target_faction': 'grineer', 'target': {'protection': 'health', 'armor': 900,
                                            'corrosive_stacks': None}}}))
line('grineer / health, armour missing', api.compute(build([SER]), DB, {'context': {
    'target_faction': 'grineer', 'target': {'protection': 'health'}}}))

print()
print('== B. the applied rider (Galvanized Chamber R10: +80% multishot, On Kill +30%/stack, 5x) ==')
line('no buff state', api.compute(build([SER, CH]), DB))
line('stacks 0 (a reported zero)', api.compute(build([SER, CH]), DB, {'context': {
    'buffs': {'on_kill': {'stacks': 0}}}}))
line('stacks 3 (instant)', api.compute(build([SER, CH]), DB, {'context': {
    'buffs': {'on_kill': {'stacks': 3}}}}))
line('stacks 5 + uptime 0.65 (averaged)', api.compute(build([SER, CH]), DB, {'context': {
    'buffs': {'on_kill': {'stacks': 5, 'uptime': 0.65}}}}))
line('stacks 5 + uptime 0.65 (averaged)', api.compute(build([SER, CH]), DB, {'context': {
    'buffs': {'on_kill': {'stacks': 5, 'uptime': 0.65}}}}))
line('uptime 0.65, no stacks', api.compute(build([SER, CH]), DB, {'context': {
    'buffs': {'on_kill': {'uptime': 0.65}}}}))
line('stacks 99 (above the 5x cap)', api.compute(build([SER, CH]), DB, {'context': {
    'buffs': {'on_kill': {'stacks': 99}}}}))

print()
print('== C. the Umbral set (warframe health) ==')
umb = [(best('Umbral Vitality')['id'], best('Umbral Vitality').get('max_rank'))]
umb2 = umb + [(best('Umbral Fiber')['id'], best('Umbral Fiber').get('max_rank'))]
umb3 = umb2 + [(best('Umbral Intensify')['id'], best('Umbral Intensify').get('max_rank'))]
excal = None
for eid, row in DB['equipment'].items():
    if row.get('name') == 'Excalibur' and row.get('kind') == 'warframe':
        excal = eid
for label, mods in (('no Umbral mods', []), ('1 piece (no bonus)', umb),
                    ('2 pieces (x1.30)', umb2), ('3 pieces (x1.80)', umb3)):
    out = api.compute(build(mods, equip=excal), DB)
    stats = (out.get('result') or {}).get('stats') or {}
    print('%-46s | health %s' % (label, stats.get('health')))
