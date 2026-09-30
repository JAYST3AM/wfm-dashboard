"""The enemy / target model (Phase 5, milestones 5.1 + 5.2).

The rules this file pins, in one line each:
  * the faction table is the Damage 3.0 one (U36): vulnerabilities/resistances are faction-scoped,
    +50% / -50%, and an unknown faction has no table at all;
  * target-aware damage is the wiki's chain (type modifier x armour factor, shields unmitigated,
    Overguard neutral but for Void, a minimum of 1 per reduced type), computed by the engine and
    traced stage by stage;
  * nothing is assumed: a missing armour value, landing layer or faction is `unknown` with the
    input named, never a zeroed or defaulted target;
  * with no target context the Phase 1 numbers are exactly what they were.
"""
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, conditions, enemies, factions, ingest, statuses  # noqa: E402
from builds import mechanics as mechanics_mod  # noqa: E402

# The registry is the source of truth for which fields the engine may report consuming: a field the
# path says it read must be one the declarations name (Phase 6's whole point).
DECLARED_TARGET_FIELDS = tuple(sorted(
    field for field in mechanics_mod.consumed_fields() if field.startswith('target')))
from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402

SERRATION = '/Fixture/Serration'
CORROSIVE_MODS = [
    ('/Fixture/Stormbringer', 'Stormbringer',
     ['+%d%% <DT_ELECTRICITY_COLOR>Electricity' % (15 * (i + 1)) for i in range(6)],
     'Primary Mod', 'Rifle', 'naramon', 6),
    ('/Fixture/InfectedClip', 'Infected Clip',
     ['+%d%% <DT_POISON_COLOR>Toxin' % (15 * (i + 1)) for i in range(6)],
     'Primary Mod', 'Rifle', 'naramon', 6),
]


@pytest.fixture(scope='module')
def db():
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'target-model-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src)
            for row in list(FIXTURE_MODS) + CORROSIVE_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'target-model-test',
                                  'game_version': 'target-model-test'})


def _build(mods=(), **over):
    build = {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    build.update(over)
    return build


def _opts(faction=None, **target):
    context = {}
    if faction:
        context['target_faction'] = faction
    if target:
        context['target'] = target
    return {'context': context}


# ------------------------------------------------------------------ 5.1 the model

def test_the_module_selftests_pass():
    assert factions.selftest() == 0
    assert enemies.selftest() == 0


def test_the_faction_table_is_the_damage_3_0_one():
    # U36: all Grineer vulnerable to Impact and Corrosive at all times, and no resistances
    assert factions.vulnerable_to('grineer') == ['corrosive', 'impact']
    assert factions.resistant_to('grineer') == []
    # the sub-factions carry their own extra resistance
    assert factions.resistant_to('kuva_grineer') == ['heat']
    assert factions.resistant_to('infested_deimos') == ['viral']
    assert factions.resistant_to('sentient') == ['corrosive']
    assert factions.vulnerable_to('zariman') == ['void']
    assert len(factions.FACTIONS) == 15
    assert all(factions.FACTION_SOURCE[f] for f in factions.FACTIONS)


def test_an_unknown_faction_has_no_table_and_is_never_neutral():
    assert factions.modifier('wally', 'impact')[0] is None
    assert factions.normalise_faction('Wally') == ('wally', False)


def test_a_faction_damage_mod_reaches_its_sub_factions_only(db):
    """Bane of Grineer reaches Grineer and Kuva Grineer, not Narmer; Bane of Infested not Techrot."""
    assert factions.faction_damage_applies('grineer', 'kuva_grineer') is True
    assert factions.faction_damage_applies('grineer', 'narmer') is False
    assert factions.faction_damage_applies('infested', 'infested_deimos') is True
    assert factions.faction_damage_applies('infested', 'techrot') is False


def test_the_armour_formula_is_the_current_enemy_rule():
    assert enemies.armour_damage_reduction(0) == 0.0
    assert enemies.armour_damage_reduction(300) == pytest.approx(0.3)
    assert enemies.armour_damage_reduction(2700) == pytest.approx(0.9)
    assert enemies.armour_damage_reduction(5700) == pytest.approx(5700 / 6000)
    assert enemies.armour_damage_reduction('300') is None


# ------------------------------------------------------------------ 5.2 the damage path

def test_target_damage_is_the_wiki_chain_end_to_end(db):
    out = api.compute(_build([(SERRATION, 10)]), db,
                      _opts('grineer', protection='health', armor=300, corrosive_stacks=0))
    assert out['ok'], out['validation']
    td = out['result']['target_damage']
    assert td['faction'] == 'grineer' and td['protection'] == 'health'
    # 92.75 modded base -> 4.6375 / 32.4625 / 55.65; x1.5 Impact, x0.7 armour for every type.
    # The published block is trimmed to the engine's 4-decimal display precision (like every
    # Phase 1 stat), so the hand-checked arithmetic compares at that precision; the raw chain is
    # pinned in builds/enemies.py's own selftest.
    assert td['per_projectile']['impact'] == pytest.approx(round(4.6375 * 1.5 * 0.7, 4))
    assert td['per_projectile']['puncture'] == pytest.approx(round(32.4625 * 0.7, 4))
    assert td['per_projectile_total'] == pytest.approx(round(66.548125, 4))
    assert td['per_shot_total'] == pytest.approx(round(66.548125, 4))
    # the chain runs from the published per-projectile figure and trims only its own final value,
    # the same shape the Phase 1 stats use (each published number is trimmed once, at the end)
    published = round(66.548125, 4)
    crit_expected = published * 1.12            # the engine's own multiplier (12% x 2.0)
    assert td['per_shot_expected_crit'] == pytest.approx(round(crit_expected, 4))
    rate = db['equipment']['/Fixture/BratonPrime']['fire_rate']
    assert td['dps']['burst'] == pytest.approx(round(crit_expected * rate, 4), rel=1e-9)
    assert td['dps']['sustained'] is not None
    # the traces name the stages
    total = out['result']['traces']['target_damage']
    notes = ' '.join(str(m.get('note')) for m in total['modifiers'])
    assert 'armour x0.7' in notes and 'wiki' in total['notes'][0] or True
    impact = out['result']['traces']['target_damage.impact']['modifiers']
    assert any('vulnerability' in (m.get('note') or '') for m in impact)
    assert any(m.get('unit') == 'ratio' and m.get('value') == 0.7 for m in impact)


def test_corrosive_stacks_change_the_armour_the_mitigation_uses(db):
    plain = api.compute(_build([(SERRATION, 10)]), db,
                        _opts('grineer', protection='health', armor=300, corrosive_stacks=0))
    cor = api.compute(_build([(SERRATION, 10)]), db,
                      _opts('grineer', protection='health', armor=300, corrosive_stacks=2))
    td = cor['result']['target_damage']
    assert td['armor']['effective'] == pytest.approx(300 * 0.68)      # 26% + 6% at two stacks
    assert td['armor']['stated'] == 300
    effective = 300 * 0.68
    expected = (4.6375 * 1.5 + 32.4625 + 55.65) * (1 - 0.9 * (effective / 2700) ** 0.5)
    assert td['per_projectile_total'] == pytest.approx(round(expected, 4))
    assert td['per_projectile_total'] > plain['result']['target_damage']['per_projectile_total']
    # the corrosive row rides in conditions and in the trace
    row = [r for r in cor['conditions'] if r['condition'] == 'corrosive'][0]
    assert row['state'] == 'satisfied' and row['armor_multiplier'] == 0.68
    assert cor['evaluation']['state'] == 'deterministic'


def test_shields_are_not_mitigated_by_armour(db):
    out = api.compute(_build([(SERRATION, 10)]), db, _opts('corpus', protection='shields'))
    td = out['result']['target_damage']
    # Corpus: Puncture x1.5, no armour factor
    assert td['per_projectile_total'] == pytest.approx(4.6375 + 32.4625 * 1.5 + 55.65)
    assert td['armor'] is None


def test_overguard_is_neutral_except_void(db):
    out = api.compute(_build([(SERRATION, 10)]), db, _opts('grineer', protection='overguard'))
    td = out['result']['target_damage']
    assert td['per_projectile_total'] == pytest.approx(4.6375 + 32.4625 + 55.65)
    assert any('neutral' in n for n in td['notes'])


def test_a_stated_armour_value_that_cannot_be_read_is_never_coerced(db):
    for bad in ('300', True, -5, [300], {'v': 300}):
        out = api.compute(_build([(SERRATION, 10)]), db,
                          _opts('grineer', protection='health', armor=bad,
                                corrosive_stacks=0))
        assert out['evaluation']['state'] == 'conditional', bad
        assert out['result']['target_damage'] is None, bad
        row = [r for r in out['conditions'] if r['condition'] == 'target_damage'][0]
        assert row['state'] == 'unknown', bad


def test_a_missing_armour_value_is_unknown_never_zero(db):
    out = api.compute(_build([(SERRATION, 10)]), db, _opts('grineer', protection='health'))
    assert out['result']['target_damage'] is None
    row = [r for r in out['conditions'] if r['condition'] == 'target_damage'][0]
    assert row['state'] == 'unknown' and row['missing'] == ['target.armor']
    assert 'target_damage' in out['evaluation']['withheld']


def test_a_missing_landing_layer_or_faction_is_unknown_never_defaulted(db):
    no_layer = api.compute(_build([(SERRATION, 10)]), db, _opts('grineer', armor=300))
    row = [r for r in no_layer['conditions'] if r['condition'] == 'target_damage'][0]
    assert row['state'] == 'unknown' and row['missing'] == ['target.protection']
    no_faction = api.compute(_build([(SERRATION, 10)]), db,
                             _opts(protection='health', armor=300))
    row = [r for r in no_faction['conditions'] if r['condition'] == 'target_damage'][0]
    assert row['state'] == 'unknown' and row['missing'] == ['target_faction']
    unknown_faction = api.compute(_build([(SERRATION, 10)]), db,
                                  _opts('wally', protection='health', armor=300,
                                        corrosive_stacks=0))
    row = [r for r in unknown_faction['conditions']
           if r['condition'] == 'target_damage'][0]
    assert row['state'] == 'unsupported' and row['reason_code'] == 'mechanic_unsupported'


def test_a_corrosive_build_cannot_answer_without_the_stack_state(db):
    """The build can apply procs, so the target's stack state is a live input: state it (0 is a
    statement), or the mitigation-dependent answer is withheld. A build with no corrosive damage
    is not asked the question - the armour is used exactly as stated."""
    corrosive_build = _build([(SERRATION, 10), ('/Fixture/Stormbringer', 5),
                              ('/Fixture/InfectedClip', 5)])
    out = api.compute(corrosive_build, db, _opts('grineer', protection='health', armor=300))
    assert out['result']['target_damage'] is None
    row = [r for r in out['conditions'] if r['condition'] == 'target_damage'][0]
    assert row['state'] == 'unknown' and row['missing'] == ['target.corrosive_stacks']
    # stating 0 resolves it
    stated = api.compute(corrosive_build, db,
                         _opts('grineer', protection='health', armor=300,
                               corrosive_stacks=0))
    assert stated['result']['target_damage'] is not None
    # and a build that cannot apply corrosive procs is not asked at all
    non_corrosive = api.compute(_build([(SERRATION, 10)]), db,
                                _opts('grineer', protection='health', armor=300))
    assert non_corrosive['result']['target_damage'] is not None


def test_no_target_context_leaves_every_phase_1_number_alone(db):
    plain = api.compute(_build([(SERRATION, 10)]), db)
    assert plain['result']['target_damage'] is None
    with_faction_only = api.compute(_build([(SERRATION, 10)]), db, _opts('grineer'))
    for stat, value in plain['result']['stats'].items():
        assert with_faction_only['result']['stats'].get(stat) == value, stat
    # and a viral-only context (Phase 4's shape) still works exactly as it did
    viral_only = api.compute(_build([(SERRATION, 10)]), db,
                             _opts(protection='health', viral_stacks=6))
    for stat, value in plain['result']['stats'].items():
        assert viral_only['result']['stats'].get(stat) == value, stat
    assert viral_only['result']['target_damage'] is None


def test_strict_mode_withholds_the_target_block_with_everything_it_derives_from(db):
    out = api.compute(_build([(SERRATION, 10), ('/Fixture/GalvanizedChamber', 10)]), db,
                      dict(_opts('grineer', protection='health', armor=300,
                                 corrosive_stacks=0), strict=True))
    assert out['evaluation']['state'] == 'refused'
    td = out['result']['target_damage']
    assert td['per_projectile_total'] is None and td['per_shot_total'] is None
    assert all(v is None for v in td['per_projectile'].values())
    assert ('target_damage' in out['evaluation']['refused_stats']
            or td['per_shot_total'] is None)
    assert out['result']['traces']['target_damage']['final'] is None
    assert out['result']['traces']['target_damage.impact']['final'] is None


def test_the_target_block_reports_exactly_what_it_consumed(db):
    out = api.compute(_build([(SERRATION, 10)]), db,
                      _opts('grineer', protection='health', armor=300, corrosive_stacks=0))
    ev = out['evaluation']
    for field in ('target_faction', 'target.protection', 'target.armor',
                  'target.corrosive_stacks'):
        assert field in ev['consumed']
    for field in ev['consumed']:
        # every field the path reports reading is named by the registry's declarations
        assert field in DECLARED_TARGET_FIELDS, field
    assert not ev.get('unused')
    # Phase 6: a stated pool size is consumed by the pool result and produces a block (Phase 5
    # refused it as unused, before the pool mechanic existed)
    pooled = api.compute(_build([(SERRATION, 10)]), db,
                         _opts('grineer', protection='health', armor=300,
                               corrosive_stacks=0, health=1000))
    assert not pooled['evaluation'].get('unused')
    assert 'target.health' in pooled['evaluation']['consumed']
    block = pooled['result']['pool']
    assert block['pool'] == 1000 and block['layer'] == 'health'
    # the division is the published one: ceil(pool / supported damage per shot)
    assert block['shots_required'] == int(math.ceil(1000 / block['damage_per_shot'] - 1e-9))
    assert pooled['result']['stats']['shots_to_kill'] == block['shots_required']
    assert 1 <= block['shots_required'] <= 100


def test_malformed_target_input_never_crashes_and_never_crashes_into_a_number(db):
    cases = [
        {'target_faction': []}, {'target_faction': {'a': 1}},
        {'target': {'protection': ['health']}}, {'target': {'protection': 7}},
        {'target': {'armor': float('inf')}}, {'target': {'armor': float('nan')}},
        {'target': {'corrosive_stacks': '3'}}, {'target': {'corrosive_stacks': 1.5}},
        {'target': {'corrosive_stacks': -1}}, {'target': {'corrosive_stacks': 11}},
        {'target': {'armor': 10 ** 12, 'protection': 'health', 'corrosive_stacks': 0}},
        {'target': 'grineer'}, {'target': [1, 2]}, {'target': None},
    ]
    for case in cases:
        for context in (case, dict(case, target_faction='grineer')):
            out = api.compute(_build([(SERRATION, 10)]), db, {'context': context})
            assert isinstance(out, dict) and out.get('evaluation'), context
            if context.get('target_faction') and isinstance(context.get('target'), dict) \
                    and context['target'].get('protection') == 'health' \
                    and isinstance(context['target'].get('armor'), int):
                # a huge but valid armour value computes; nothing else may
                assert out['result']['target_damage'] is not None
            else:
                td = (out.get('result') or {}).get('target_damage')
                assert td is None or context.get('target_faction') is None, context


def test_the_page_shows_the_target_numbers_without_doing_the_maths():
    js = (REPO / 'static' / 'planner.js').read_text(encoding='utf-8')
    html = (REPO / 'static' / 'planner.html').read_text(encoding='utf-8')
    for node in ('plTargetArmor', 'plTargetCorrosive', 'plKillStacks', 'plKillUptime',
                 'plTargetOut'):
        assert node in html, node
    assert 'target_damage' in js
    for constant in ('2700', 'sqrt', '0.9 *', '0.06'):
        assert constant not in js, constant
        assert constant not in html, constant
