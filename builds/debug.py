#!/usr/bin/env python3
"""Developer surface for the build planner (brief sections 12-14).

    python builds/debug.py summary
    python builds/debug.py sources
    python builds/debug.py unsupported
    python builds/debug.py mod "Serration"
    python builds/debug.py equipment "Excalibur"
    python builds/debug.py stat "Braton Prime" --mod Serration:10 --mod "Hellfire":5 \
        --orokin --rank 30 --mastery 12
    python builds/debug.py explain "Braton Prime" --mod Serration:10 \
        --stat critical_chance
    python builds/debug.py selftest

`--mod NAME:RANK` may be repeated and accepts an id or slug instead of a name. Output is
plain text: this is the surface that proves the engine's explanations are human-readable.
"""
import argparse
import os
import sys

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from builds import api, capacity as capacity_mod, data as data_mod, effects as effects_mod
from builds import schema, trace as trace_mod, unsupported as unsupported_mod


def ascii_s(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def rule(title, char='-'):
    print('\n%s\n%s' % (title, char * len(title)))


def _load(args):
    db = data_mod.load(getattr(args, 'db', None))
    return db


def cmd_summary(args):
    db = _load(args)
    info = data_mod.summary(db)
    rule('build database')
    for key in ('schema_version', 'generated', 'equipment', 'mods', 'game_version',
                'content_hash'):
        print('%-16s %s' % (key, info.get(key)))
    print('%-16s %s' % ('by kind', info.get('equipment_by_kind')))
    print('%-16s %s' % ('notes', info.get('notes')))


def cmd_sources(args):
    db = _load(args)
    rule('where every number comes from')
    for key, row in sorted(data_mod.sources(db).items()):
        print('%-22s %s' % (key, row.get('source')))
        if row.get('url'):
            print('%-22s %s' % ('', row['url']))
        print('%-22s owns: %s' % ('', row.get('owns')))


def cmd_unsupported(args):
    rule('what the engine does NOT know yet')
    for row in unsupported_mod.list_all():
        print('%-28s phase %-2s %s' % (row['code'], row.get('phase'),
                                       row.get('reason')))


def cmd_mod(args):
    db = _load(args)
    row = data_mod.find_mod(db, args.name)
    if row is None:
        print('no mod matching %r' % args.name)
        return 1
    rule('%s  (%s)' % (row['name'], row['id']))
    print('class %s  targets %s  rarity %s' % (row.get('class'), row.get('targets'),
                                               row.get('rarity')))
    print('polarity %s  drain %s  max rank %s  slot %s  exilus %s'
          % (row.get('polarity'), row.get('base_drain'), row.get('max_rank'),
             row.get('slot'), row.get('exilus_ok')))
    print('flags %s' % _flags(row.get('flags') or {}))
    for rank in (0, row.get('max_rank')):
        print('\nrank %s effects:' % rank)
        for line in effects_mod.effect_text(row.get('effects'), rank):
            print('  %s' % line)
    unmodelled = (row.get('effects') or {}).get('unmodelled') or {}
    if unmodelled:
        print('\nstats the engine does not model (%d):' % len(unmodelled))
        for text in list(unmodelled)[:12]:
            print('  %s' % text)
    conditional = (row.get('effects') or {}).get('conditional') or []
    if conditional:
        print('\nconditional (needs Phase 2) (%d):' % len(conditional))
        for text in conditional[:12]:
            print('  %s' % text)


def cmd_equipment(args):
    db = _load(args)
    row = data_mod.find_equipment(db, args.name)
    if row is None:
        print('no equipment matching %r' % args.name)
        return 1
    rule('%s  (%s)' % (row['name'], row['id']))
    print('kind %s  subtype %s  max rank %s  mastery req %s'
          % (row.get('kind'), row.get('subtype'), row.get('max_rank'),
             row.get('mastery_req')))
    print('polarities %s  aura %s  stance %s  exilus %s'
          % (row.get('polarities'), row.get('aura_polarity'), row.get('stance_polarity'),
             row.get('exilus_polarity')))
    for key in ('stats', 'damage'):
        if row.get(key):
            print('%s %s' % (key, row[key]))
    for key in ('damage_total', 'crit_chance', 'crit_multiplier', 'status_chance',
                'fire_rate', 'multishot', 'magazine', 'reload', 'trigger', 'range',
                'incarnon'):
        if row.get(key) is None:
            continue
        print('%-18s %s' % (key, row.get(key)))
    if row.get('variant'):
        print('%-18s %s (a starter copy that shares this display name)'
              % ('variant', row['variant']))


def _flags(flags):
    return ', '.join(sorted(k for k, v in flags.items() if v)) or '-'


def _slot_args(args, equipment, db=None):
    """--mod NAME:RANK[,slot_index] -> the build's slot list.

    Mods fill normal slots in order unless a slot is given explicitly as NAME:RANK@N
    (aura/stance/exilus have fixed slots: 'aura', 'stance', 'exilus'). With
    --match-polarity every filled slot is polarized to the mod's own polarity, i.e. the
    build a player would actually run after Forma'ing the slots ("as if Forma'd").
    """
    slots, used, special = [], set(), set()
    for spec in args.mod or []:
        target = None
        if '@' in spec:
            spec, target = spec.rsplit('@', 1)
        name, _, rank = spec.partition(':')
        rank = int(rank) if rank.strip() else None
        slots.append({'name': name.strip(), 'rank': rank, 'target': target})
    out = []
    slot_classes = {'aura', 'stance', 'exilus'}
    auto_polarities = list(equipment.get('polarities') or [])
    for entry in slots:
        name, rank, target = entry['name'], entry['rank'], entry['target']
        if target in slot_classes:
            used.add(target)
            special.add(target)
            kind = target if target != 'exilus' else schema.SLOT_EXILUS
            polarity = equipment.get('%s_polarity' % ('stance' if target == 'stance'
                                                     else 'aura'), None)
            if kind == schema.SLOT_EXILUS:
                polarity = equipment.get('exilus_polarity')
            out.append({'name': name, 'rank': rank, 'kind': kind, 'index': None,
                        'polarity': polarity, 'unlocked': True})
            continue
        index = int(target) if (target and target.isdigit()) else None
        if index is None:
            for candidate in range(schema.NORMAL_SLOTS):
                if candidate not in used and candidate not in special:
                    index = candidate
                    break
        used.add(index)
        polarity = auto_polarities[index] if index < len(auto_polarities) else None
        out.append({'name': name, 'rank': rank, 'kind': schema.SLOT_NORMAL, 'index': index,
                    'polarity': polarity})
    if getattr(args, 'match_polarity', False) and db is not None:
        for entry in out:
            if not entry['name']:
                continue
            row = data_mod.find_mod(db, entry['name'])
            if row and row.get('polarity'):
                entry['polarity'] = row['polarity']
    return out


def _build_from_args(args, db):
    equipment = data_mod.find_equipment(db, args.equipment)
    if equipment is None:
        return None, None, [{'code': 'unknown_equipment',
                             'message': 'no equipment matching %r' % args.equipment}]
    slots, errors = [], []
    for entry in _slot_args(args, equipment, db):
        row = data_mod.find_mod(db, entry['name'])
        if row is None:
            errors.append({'code': 'unknown_mod', 'message': 'no mod matching %r'
                           % entry['name']})
            continue
        slots.append({'kind': entry['kind'], 'index': entry['index'],
                      'polarity': entry['polarity'], 'unlocked': entry.get('unlocked'),
                      'mod': {'id': row['id'],
                              'rank': row['max_rank'] if entry['rank'] is None
                              else entry['rank']}})
    build = {'config': 'debug', 'equipment_id': equipment['id'],
             'equipment_rank': args.rank, 'orokin': args.orokin,
             'mastery_rank': args.mastery, 'slots': slots}
    return equipment, build, errors


def cmd_stat(args):
    from builds import trace as trace_mod2
    db = _load(args)
    equipment, build, errors = _build_from_args(args, db)
    if equipment is None:
        print(errors[0]['message'])
        return 1
    computed = api.compute(build, db, {'faction': args.faction})
    if errors:
        computed['validation']['errors'].extend(errors)
    validation = computed.get('validation') or {}
    if validation.get('errors'):
        rule('validation failed')
        for row in validation['errors']:
            print('%-24s %s' % (row.get('code'), row.get('message')))
        return 1
    rule('%s -> computed stats' % equipment['name'])
    stats = (computed.get('result') or {}).get('stats') or {}
    baseline = ((computed.get('baseline') or {}).get('stats')) or {}
    width = max(len(k) for k in stats) if stats else 8
    print('%s %14s %14s %12s' % ('stat'.ljust(width), 'unmodded', 'modded', 'delta'))
    for key in sorted(stats):
        before, after = baseline.get(key), stats.get(key)
        delta = ''
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            delta = '%+g' % (round(after - before, 4),)
        print('%s %14s %14s %12s' % (key.ljust(width), _fmt(before), _fmt(after), delta))
    cap = computed.get('capacity') or {}
    print('\ncapacity %s/%s used, %s free  (aura bonus %s)'
          % (cap.get('drain', {}).get('total'), cap.get('capacity', {}).get('total'),
             cap.get('drain', {}).get('remaining'),
             cap.get('capacity', {}).get('aura_bonus')))
    for row in validation.get('warnings') or []:
        print('warning: %s' % row.get('message'))
    for row in computed.get('unsupported') or []:
        print('unsupported: %-26s %s' % (row.get('code'), row.get('reason')))


def _fmt(value):
    if isinstance(value, float):
        return ('%.4f' % value).rstrip('0').rstrip('.')
    return '' if value is None else str(value)


def cmd_explain(args):
    db = _load(args)
    equipment, build, errors = _build_from_args(args, db)
    if equipment is None:
        print(errors[0]['message'])
        return 1
    computed = api.compute(build, db)
    if args.stat:
        text = api.explain(computed, args.stat)
        if text is None:
            available = sorted(((computed.get('result') or {}).get('traces') or {}))
            print('no trace for %r; try: %s' % (args.stat, ', '.join(available[:20])))
            return 1
        print(text)
        return 0
    traces = (computed.get('result') or {}).get('traces') or {}
    for key in sorted(traces):
        print(trace_mod.text(traces[key]))
        print()
    return 0


def cmd_selftest(args):
    from builds import ingest
    code = ingest.selftest()
    code |= effects_mod.selftest()
    code |= capacity_mod.selftest()
    from builds import elements
    code |= elements.selftest()
    from builds import weapons
    code |= weapons.selftest()
    from builds import warframes
    code |= warframes.selftest()
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description='build planner developer surface')
    parser.add_argument('--db', default=None, help='path to build_data.json')
    sub = parser.add_subparsers(dest='command')

    p = sub.add_parser('summary'); p.set_defaults(func=cmd_summary)
    p = sub.add_parser('sources'); p.set_defaults(func=cmd_sources)
    p = sub.add_parser('unsupported'); p.set_defaults(func=cmd_unsupported)
    p = sub.add_parser('mod'); p.add_argument('name'); p.set_defaults(func=cmd_mod)
    p = sub.add_parser('equipment'); p.add_argument('name'); p.set_defaults(func=cmd_equipment)
    p = sub.add_parser('selftest'); p.set_defaults(func=cmd_selftest)

    for name, func in (('stat', cmd_stat), ('explain', cmd_explain)):
        p = sub.add_parser(name)
        p.add_argument('equipment')
        p.add_argument('--mod', action='append', default=[],
                       help='NAME:RANK (repeatable; NAME:RANK@SLOT for a fixed slot)')
        p.add_argument('--stat', default=None, help='one trace to render (explain only)')
        p.add_argument('--rank', type=int, default=30)
        p.add_argument('--mastery', type=int, default=30)
        p.add_argument('--orokin', action='store_true')
        p.add_argument('--match-polarity', action='store_true',
                       help='polarize each filled slot to its mod (as if Forma\'d)')
        p.add_argument('--faction', default=None)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    if not getattr(args, 'func', None):
        parser.print_help()
        return 1
    return args.func(args) or 0


if __name__ == '__main__':
    sys.exit(main())
