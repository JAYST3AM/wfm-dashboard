"""Terminal interface for the local WFM dashboard data (read-only, no network).

Reads the JSON files other dashboard scripts already write:
  data/prices.json, data/stats.json (optional vol/median enrichment),
  data/owned.json, data/report.json, data/deals.json, data/trader_plan.json,
  data/trader_limits.json, data/sets.json, data/ducats.json,
  data/wfm_items_v2.json (item names for search)

Nothing here writes anything or touches the network.

Exit codes: 0 = ok, 1 = missing/empty data (clear one-line message), 2 = bad args.
"""
import argparse
import difflib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

# default row caps per command (0 = no cap); --limit overrides
CAPS = {'prices': 25, 'owned': 25, 'picks': 15, 'deals': 15, 'sets': 10,
        'ducats': 8, 'plan': 0}


class MissingData(Exception):
    """Raised for missing/unreadable input files."""


# --------------------------------------------------------------------------- io
def load_json(name, required=True, default=None):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        if required:
            raise MissingData('missing data file: data/%s' % name)
        return default
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise MissingData('cannot read data/%s: %s' % (name, exc))


_NAME_MAP = None
_STATS = None


def name_map():
    """slug -> display name, from the item catalog (fallback: owned.json)."""
    global _NAME_MAP
    if _NAME_MAP is not None:
        return _NAME_MAP
    mapping = {}
    catalog = load_json('wfm_items_v2.json', required=False, default={}) or {}
    for item in (catalog.get('data') or []):
        slug = item.get('slug')
        nm = ((item.get('i18n') or {}).get('en') or {}).get('name')
        if slug and nm:
            mapping[slug] = nm
    for row in (load_json('owned.json', required=False, default=[]) or []):
        if row.get('slug') and row.get('name'):
            mapping.setdefault(row['slug'], row['name'])
    _NAME_MAP = mapping
    return mapping


def stats():
    global _STATS
    if _STATS is None:
        _STATS = load_json('stats.json', required=False, default={}) or {}
    return _STATS


def item_name(slug):
    nm = name_map().get(slug)
    if nm:
        return nm
    return ' '.join(w.capitalize() for w in str(slug).split('_'))


def vol48_of(slug, price_entry):
    v = (price_entry or {}).get('vol48')
    if v is None:
        v = (stats().get(slug) or {}).get('vol48')
    return v


def med48_of(slug, price_entry):
    v = (price_entry or {}).get('med48')
    if v is None:
        v = (stats().get(slug) or {}).get('med48')
    return v


# ------------------------------------------------------------------------ format
def ascii_(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def fmt(value, nd=2, dash='-'):
    if value is None or value == '':
        return dash
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        txt = '%.*f' % (nd, value)
        if '.' in txt:
            txt = txt.rstrip('0').rstrip('.')
        return txt or '0'
    return ascii_(value)


def render(headers, rows, right=()):
    """Plain-ASCII aligned table (no box drawing, no emoji)."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    right = set(right)

    def line(cells):
        out = []
        for i, cell in enumerate(cells):
            out.append(cell.rjust(widths[i]) if i in right else cell.ljust(widths[i]))
        return '  '.join(out).rstrip()

    lines = [line([ascii_(h) for h in headers]),
             '  '.join('-' * w for w in widths)]
    lines += [line([ascii_(c) for c in row]) for row in rows]
    return '\n'.join(lines)


def kv_block(pairs):
    width = max((len(k) for k, _ in pairs), default=0)
    return '\n'.join('%s  %s' % (ascii_(k).ljust(width), ascii_(v)) for k, v in pairs)


def txt(value, dash='-'):
    """Safe scalar for key/value blocks: None -> dash, bools -> yes/no, epoch -> ISO."""
    if value is None or value == '':
        return dash
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 1e9:
        import datetime
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc
                                               ).strftime('%Y-%m-%dT%H:%M:%SZ')
    return ascii_(value)


def fail(message):
    print(message)
    sys.exit(1)


def cap(args, command):
    default = CAPS.get(command, 0)
    limit = getattr(args, 'limit', None)
    if limit is None:
        return default
    return limit  # 0 = everything


def take(rows, limit):
    return rows if not limit else rows[:limit]


# ------------------------------------------------------------------------ search
def norm(text):
    return ' '.join(str(text).lower().replace('_', ' ').replace('-', ' ').split())


def search(pairs, query):
    """Rank (slug, name) pairs against a fuzzy query: exact, substring, tokens, close."""
    nq = norm(query)
    if not nq:
        return []
    exact, subs, close = [], [], []
    for slug, name in pairs:
        ns, nn = norm(slug), norm(name)
        if nq == ns or nq == nn:
            exact.append((slug, name))
        elif nq in nn or nq in ns:
            pos = nn.find(nq) if nq in nn else ns.find(nq)
            subs.append((pos, name, slug))
        elif all(tok in nn or tok in ns for tok in nq.split()):
            subs.append((50, name, slug))
        else:
            ratio = difflib.SequenceMatcher(None, nq, nn).ratio()
            if ratio >= 0.6:
                close.append((ratio, name, slug))
    subs.sort(key=lambda t: (t[0], t[1]))
    close.sort(key=lambda t: (-t[0], t[1]))
    out, seen = [], set()
    for slug, name in exact + [(s, n) for _, n, s in subs] + [(s, n) for _, n, s in close]:
        if slug not in seen:
            seen.add(slug)
            out.append((slug, name))
    return out


# ---------------------------------------------------------------------- commands
def cmd_status(args):
    limits = load_json('trader_limits.json')
    plan = load_json('trader_plan.json', required=False, default={}) or {}
    report = load_json('report.json', required=False)
    deals = load_json('deals.json', required=False)
    sets = load_json('sets.json', required=False)
    owned = load_json('owned.json', required=False)
    ducats = load_json('ducats.json', required=False)
    prices = load_json('prices.json', required=False)

    print('WFM DASHBOARD STATUS')
    print(kv_block([
        ('account', txt(limits.get('account'))),
        ('plat', txt(limits.get('plat'))),
        ('trades left', '%s / %s' % (fmt(limits.get('trades_left'), dash='?'),
                                     fmt(limits.get('trade_cap'), dash='?'))),
        ('reset (Melbourne)', txt(limits.get('reset_melbourne'))),
        ('limit status', txt(limits.get('status'))),
        ('plan', '%s planned, %s held, %s live orders (dry_run=%s)' % (
            fmt(plan.get('planned'), dash='?'),
            len(plan.get('held_list') or []) if plan else '?',
            fmt(plan.get('live_orders'), dash='?'),
            fmt(plan.get('dry_run')))),
        ('plan generated', txt(plan.get('generated'))),
    ]))
    notes = limits.get('notes') or []
    if notes:
        print('note: %s' % ascii_('; '.join(str(n) for n in notes))[:200])
    print('')

    counts = []
    if prices is not None:
        counts.append(('prices slugs', len(prices)))
    if owned is not None:
        counts.append(('owned entries', len(owned)))
        counts.append(('owned slugs', len({r.get('slug') for r in owned if r.get('slug')})))
    if report is not None:
        counts.append(('report sell_now', len(report.get('sell_now') or [])))
        counts.append(('report flips', len(report.get('flips') or [])))
    if deals is not None:
        dc = deals.get('counts') or {}
        counts.append(('deals total', dc.get('total')))
        for kind, n in sorted((dc.get('by_kind') or {}).items()):
            counts.append(('deals %s' % kind, n))
        counts.append(('deals run', dc.get('run_deals')))
    counts.append(('plan rows', len(plan.get('plan') or []) if plan else None))
    if sets is not None:
        sc = sets.get('summary') or {}
        counts.append(('sets tracked', sc.get('sets_total')))
        counts.append(('sets targets', sc.get('targets')))
    if ducats is not None:
        counts.append(('ducats rows', len(ducats.get('rows') or [])))

    print(render(['dataset', 'count'], [[k, fmt(v, dash='missing')] for k, v in counts], right={1}))
    return 0


def cmd_prices(args):
    prices = load_json('prices.json')
    pairs = [(slug, item_name(slug)) for slug in prices]
    hits = search(pairs, args.search)
    if not hits:
        fail("no price rows match '%s'" % args.search)
    limit = cap(args, 'prices')
    shown = take(hits, limit)
    print("%s match(es) for '%s' (showing %s)" % (len(hits), args.search, len(shown)))
    rows = []
    for slug, name in shown:
        pe = prices.get(slug) or {}
        rows.append([slug, name, fmt(pe.get('wts')), fmt(pe.get('wtb')),
                     fmt(vol48_of(slug, pe))])
    print(render(['slug', 'name', 'wts', 'wtb', 'vol48'], rows, right={2, 3, 4}))
    return 0


def cmd_item(args):
    slug = str(args.slug).lower().replace(' ', '_').replace('-', '_')
    prices = load_json('prices.json', required=False, default={}) or {}
    owned = load_json('owned.json', required=False, default=[]) or []
    pe = prices.get(slug)
    mine = [o for o in owned if o.get('slug') == slug]
    if pe is None and not mine:
        fail("no data for item '%s'" % args.slug)

    count = sum(o.get('count') or 1 for o in mine)
    ducats = next((o.get('ducats') for o in mine if o.get('ducats') is not None), None)
    tags, sections = [], []
    for o in mine:
        for tag in (o.get('tags') or []):
            if tag not in tags:
                tags.append(tag)
        if o.get('section') and o['section'] not in sections:
            sections.append(o['section'])
    wts = (pe or {}).get('wts')

    pairs = [('slug', slug), ('name', item_name(slug))]
    pairs.append(('price source', 'data/prices.json' if pe is not None
                  else 'not in data/prices.json'))
    core = ['wts', 'wtb', 'vol48', 'med48', 'n_sell', 'n_buy']
    for key in core:
        if key in ('vol48', 'med48'):
            inline = (pe or {}).get(key)
            value = vol48_of(slug, pe) if key == 'vol48' else med48_of(slug, pe)
            suffix = '' if inline is not None else (' (stats.json)' if value is not None else '')
            pairs.append((key, fmt(value) + suffix))
        elif pe is not None:
            pairs.append((key, fmt(pe.get(key))))
    for key in sorted((pe or {}).keys()):
        if key not in core:
            pairs.append(('raw %s' % key, fmt(pe.get(key))))
    pairs += [('owned count', count if mine else 0),
              ('owned value', fmt(wts * count) if (mine and wts is not None) else '-'),
              ('ducats', fmt(ducats)),
              ('tags', ', '.join(tags) if tags else '-'),
              ('sections', ', '.join(sections) if sections else '-')]
    print(kv_block(pairs))
    return 0


def cmd_owned(args):
    owned = load_json('owned.json')
    prices = load_json('prices.json', required=False, default={}) or {}
    agg = {}
    for row in owned:
        slug = row.get('slug')
        if not slug:
            continue
        entry = agg.setdefault(slug, {'name': row.get('name') or item_name(slug),
                                      'count': 0, 'ducats': None})
        entry['count'] += row.get('count') or 1
        if entry['ducats'] is None and row.get('ducats') is not None:
            entry['ducats'] = row.get('ducats')
    hits = search([(s, e['name']) for s, e in agg.items()], args.search)
    if not hits:
        fail("no owned items match '%s'" % args.search)

    rows = []
    for slug, name in hits:
        entry = agg[slug]
        wts = (prices.get(slug) or {}).get('wts')
        rows.append(dict(slug=slug, name=name, xcount=entry['count'],
                         value=(wts or 0) * entry['count'] if wts is not None else None,
                         ducats=entry['ducats']))
    rows.sort(key=lambda r: -(r['value'] or 0))
    limit = cap(args, 'owned')
    shown = take(rows, limit)
    print("%s owned slug(s) match '%s' (showing %s, sorted by value desc)"
          % (len(rows), args.search, len(shown)))
    print(render(['slug', 'name', 'xcount', 'value', 'ducats'],
                 [[r['slug'], r['name'], fmt(r['xcount']), fmt(r['value']), fmt(r['ducats'])]
                  for r in shown], right={2, 3, 4}))
    return 0


def cmd_picks(args):
    report = load_json('report.json')
    picks = report.get('sell_now') or []
    if not picks:
        fail('no sell_now picks in data/report.json')
    limit = cap(args, 'picks') or len(picks)
    print('sell_now top %s of %s (report generated %s, total value %s)'
          % (min(limit, len(picks)), len(picks), report.get('generated'),
             fmt((report.get('totals') or {}).get('value'))))
    rows = [[r.get('slug'), r.get('name'), fmt(r.get('count')), fmt(r.get('wts')),
             fmt(r.get('med'), nd=1), fmt(r.get('vol48')), fmt(r.get('value'))]
            for r in take(picks, limit)]
    print(render(['slug', 'name', 'xcount', 'wts', 'med', 'vol48', 'value'],
                 rows, right={2, 3, 4, 5, 6}))
    return 0


def cmd_deals(args):
    deals = load_json('deals.json')
    rows = deals.get('deals') or []
    if args.kind:
        rows = [d for d in rows if d.get('kind') == args.kind]
        if not rows:
            fail("no deals of kind '%s' in data/deals.json" % args.kind)
    elif not rows:
        fail('no deals in data/deals.json')
    rows = sorted(rows, key=lambda d: -(d.get('score') or 0))
    limit = cap(args, 'deals') or len(rows)
    counts = deals.get('counts') or {}
    print('deals %s top %s of %s (by_kind %s, generated %s)'
          % (args.kind or 'all', min(limit, len(rows)), len(rows),
             json.dumps(counts.get('by_kind') or {}), deals.get('generated_iso')))
    table = [[r.get('slug'), r.get('name'), r.get('kind'),
              fmt(r.get('floor_sell')), fmt(r.get('ref')), fmt(r.get('profit')),
              fmt(r.get('profit_pct'), nd=1), fmt(r.get('vol48'))]
             for r in take(rows, limit)]
    print(render(['slug', 'name', 'kind', 'floor', 'ref', 'profit', 'pct', 'vol48'],
                 table, right={3, 4, 5, 6, 7}))
    return 0


def cmd_plan(args):
    plan = load_json('trader_plan.json')
    rows = plan.get('plan') or []
    if not rows:
        fail('trader plan is empty (data/trader_plan.json has no rows)')
    limit = cap(args, 'plan') or len(rows)
    print('trader plan: %s planned, %s held, %s live orders | account %s dry_run=%s '
          '| trades_left %s'
          % (plan.get('planned'), len(plan.get('held_list') or []), plan.get('live_orders'),
             plan.get('account'), plan.get('dry_run'), plan.get('trades_left')))
    table = [[r.get('slug'), r.get('name'), fmt(r.get('qty')), fmt(r.get('price')),
              r.get('lane'), fmt(r.get('est_total')), fmt(r.get('vol48')),
              fmt(r.get('med'), nd=1)]
             for r in take(rows, limit)]
    print(render(['slug', 'name', 'qty', 'price', 'lane', 'est_total', 'vol48', 'med'],
                 table, right={2, 3, 5, 6, 7}))
    held = plan.get('held_list') or []
    if held:
        parts = ['%s: %s' % (h[0], h[1]) if isinstance(h, (list, tuple)) and len(h) >= 2
                 else str(h) for h in held[:10]]
        print('held (%s): %s%s' % (len(held), ascii_('; '.join(parts)),
                                   ' ...' if len(held) > 10 else ''))
    return 0


def cmd_limits(args):
    limits = load_json('trader_limits.json')
    print(json.dumps(limits, indent=2, ensure_ascii=True))
    return 0


def cmd_sets(args):
    sets = load_json('sets.json')
    targets = sets.get('top_targets') or []
    if not targets:
        fail('no top_targets in data/sets.json')
    summary = sets.get('summary') or {}
    limit = cap(args, 'sets') or len(targets)
    print('set targets top %s of %s | targets %s, complete_or_near %s, net profit %s '
          '(generated %s)'
          % (min(limit, len(targets)), len(targets), summary.get('targets'),
             summary.get('complete_or_near'), fmt(summary.get('net_profit_build_targets')),
             sets.get('generated')))
    table = [[t.get('slug'), t.get('name'), t.get('parts'),
              fmt(len(t.get('need') or [])), fmt(t.get('cost_est'), dash='free'),
              fmt(t.get('set_value'), nd=1), fmt(t.get('profit'), nd=1), t.get('action'),
              t.get('confidence'), fmt(t.get('score'), nd=1)]
             for t in take(targets, limit)]
    print(render(['slug', 'name', 'parts', 'need', 'cost', 'setval', 'profit', 'action',
                  'conf', 'score'], table, right={3, 4, 5, 6, 9}))
    return 0


def cmd_ducats(args):
    ducats = load_json('ducats.json')
    summary = ducats.get('summary') or {}
    rows = ducats.get('rows') or []
    if not rows:
        fail('no rows in data/ducats.json')
    limit = cap(args, 'ducats') or len(rows)
    print('ducat plan (generated %s)' % ducats.get('generated'))
    print(kv_block([(k, fmt(v, dash='-')) for k, v in summary.items()]))
    print('')

    burn = sorted([r for r in rows if r.get('verdict') == 'BURN'],
                  key=lambda r: -(r.get('ducats_total') or 0))
    sell = sorted([r for r in rows if r.get('verdict') == 'SELL'],
                  key=lambda r: -((r.get('sell_total') or 0)))
    if burn:
        print('top %s burn (%s total)' % (min(limit, len(burn)), len(burn)))
        table = [[r.get('slug'), r.get('name'), fmt(r.get('count')), fmt(r.get('ducats')),
                  fmt(r.get('ducats_total')), fmt(r.get('ducats_per_plat'), nd=1)]
                 for r in take(burn, limit)]
        print(render(['slug', 'name', 'xcount', 'ducats', 'dtotal', 'd/plat'],
                     table, right={2, 3, 4, 5}))
    else:
        print('no BURN rows')
    print('')
    if sell:
        print('top %s sell (%s total)' % (min(limit, len(sell)), len(sell)))
        table = [[r.get('slug'), r.get('name'), fmt(r.get('count')), fmt(r.get('wts')),
                  fmt(r.get('sell_total')), fmt(r.get('vol48'))]
                 for r in take(sell, limit)]
        print(render(['slug', 'name', 'xcount', 'wts', 'sell_total', 'vol48'],
                     table, right={2, 3, 4, 5}))
    else:
        print('no SELL rows')
    return 0


# -------------------------------------------------------------------------- main
def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError('expected an integer, got %r' % text)
    if value <= 0:
        raise argparse.ArgumentTypeError('expected a positive integer, got %r' % text)
    return value


def build_parser():
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--limit', type=positive_int, default=None, metavar='N',
                        help='max rows to show (default: per-command cap)')
    sub_shared = argparse.ArgumentParser(add_help=False)
    sub_shared.add_argument('--limit', type=positive_int, default=argparse.SUPPRESS,
                            metavar='N', help='max rows to show')

    parser = argparse.ArgumentParser(
        prog='cli.py', parents=[shared],
        description='Terminal view of the local WFM dashboard data (read-only, no network).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  cli.py status\n'
               '  cli.py prices "primed cont" --limit 5\n'
               '  cli.py item primed_continuity\n'
               '  cli.py deals --kind spread\n')
    subs = parser.add_subparsers(dest='command', metavar='<command>')

    def add(name, help_text):
        sp = subs.add_parser(name, parents=[sub_shared], help=help_text,
                             description=help_text)
        return sp

    add('status', 'plat, trades left, plan size, dataset counts')
    sp = add('prices', 'fuzzy name search over data/prices.json (default cap 25)')
    sp.add_argument('search', help='fuzzy item name or slug')
    sp = add('item', 'one item: all price fields + owned count/ducats/tags')
    sp.add_argument('slug', help='exact item slug')
    sp = add('owned', 'search owned inventory by name (default cap 25)')
    sp.add_argument('search', help='fuzzy item name or slug')
    add('picks', 'top rows from report.json sell_now (default 15)')
    sp = add('deals', 'top rows from deals.json (default 15)')
    sp.add_argument('--kind', choices=['spread', 'undercut'], default=None,
                    help='only this deal kind')
    add('plan', 'trader_plan.json rows')
    add('limits', 'trader_limits.json pretty print')
    add('sets', 'top set targets from sets.json (default 10)')
    add('ducats', 'ducat summary + top burn/sell rows (default 8 each)')
    return parser


HANDLERS = {'status': cmd_status, 'prices': cmd_prices, 'item': cmd_item,
            'owned': cmd_owned, 'picks': cmd_picks, 'deals': cmd_deals,
            'plan': cmd_plan, 'limits': cmd_limits, 'sets': cmd_sets,
            'ducats': cmd_ducats}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return HANDLERS[args.command](args)
    except MissingData as exc:
        print(str(exc))
        return 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('error reading dashboard data: %s: %s' % (type(exc).__name__, exc))
        return 1


if __name__ == '__main__':
    sys.exit(main())
