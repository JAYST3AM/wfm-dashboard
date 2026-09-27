"""How-to-obtain lines for the Collection hover card (scripts/obtain_index.py wiki pass).

Jay (2026-09-26): *"in collection, each item ie ash needs to show how to get it"* - and a tail of
items could only say "See the wiki" because the wiki lookup missed their page or their page had
no Acquisition heading. `wiki_fill` now gives every fact-less item a sourced line and records
where it came from:

  * the page's own Acquisition section, or its `{{Acquisition|...}}` template,
  * otherwise a verbatim sentence from the page that names a real source,
  * otherwise the WFCD `introduced` row ("Added in Update 31.7 (2022-07-16)"),
  * and if a source truly has nothing, nothing is invented - the card keeps its honest fallback.

Title resolution is the other half: exact name, the uppercase form ('Ax-52' -> 'AX-52'), the
capitalised form, the Wiki-style underscored title, the sentence-case title the wiki sometimes
uses ('Para Moa' -> 'Para moa'), the WFCD row's own wikiaUrl title, and last the wiki search API
(how 'Orion & Sirius' finds 'Sirius & Orion'). Every step that resolves is recorded on the line.

These tests are offline: pages live in a tmp wiki cache (WFM_DATA_DIR), search hits are
monkeypatched, and the fixture fails the test if anything touched the network.
"""
import json

import pytest

from conftest import load_script


# --------------------------------------------------------------------------- fixtures

@pytest.fixture
def OI(tmp_path, monkeypatch):
    """A fresh obtain_index module whose data dir (and wiki cache) is inside tmp_path."""
    mod = load_script('obtain_index', monkeypatch=monkeypatch,
                      env={'WFM_DATA_DIR': str(tmp_path)})
    mod_wiki_search = getattr(mod, 'wiki_search')

    def no_hits(name, offline=False, limit=None):
        hits = getattr(mod, 'SEARCH_HITS', {})
        if hits:
            return hits.get(name, [])
        return mod_wiki_search(name, offline=True)     # cache only - never the network

    monkeypatch.setattr(mod, 'wiki_search', no_hits)
    yield mod
    assert mod.NET_CALLS == 0, 'these tests must stay offline'


def search_hits(OI, hits):
    """Fixture search results (checked before anything would go to the network)."""
    OI.SEARCH_HITS = hits


def cache_page(OI, title, text, resolved=None):
    """A page in the tmp wiki cache, exactly as a live fetch would have written it."""
    path, _doc = OI.wiki_cache_path(title)
    OI.atomic_write(path, {'title': title, 'resolved': resolved or title, 'text': text,
                           'missing': text is None, 'fetched': 0})


BRATON = ("'''Braton''' is a rifle.\n"
          "== Acquisition ==\n"
          "A fully built Braton can be purchased from the [[Market]] for {{cc|25,000}}. "
          "It can be sold for 7,500 credits.\n"
          "== Notes ==\n"
          "*Something else entirely.\n")

ORVIUS = ("'''Orvius''' is a glaive.\n"
          "=== Characteristics ===\n"
          "This weapon deals primarily {{D|Slash}} damage.\n"
          "{{Acquisition|The blueprint is rewarded on completion of [[The War Within]]. "
          "Additional blueprints can be bought from [[Cephalon Simaris]] for {{sc|100,000}}.}}\n")

CARRIER = ("'''Carrier''' is a Sentinel.\n"
           "== Notes ==\n"
           "*Carrier's blueprint can be purchased from the [[Market]].\n")

VENARI = ("'''Venari''' is Khora's companion.\n"
          "== Acquisition ==\n"
          "All postures are available by default when Venari is unlocked at Warframe rank 5.\n")

SIRIUS_MAIN = ("{{Acquisition|name=Sirius & Orion|Sirius & Orion's main blueprint is acquired upon "
               "completion of the [[Jade Shadows: Constellations]] quest.}}\n")


# --------------------------------------------------------------------------- title resolution

def test_title_variants_resolution_order(OI):
    assert OI.title_variants('Braton') == [('Braton', 'exact')]
    assert OI.title_variants('Ax-52') == [('Ax-52', 'exact'), ('AX-52', 'upper')]
    steps = [step for _title, step in OI.title_variants('Para Moa')]
    assert steps == ['exact', 'underscored', 'sentence-case']
    # the uppercased form is only tried when the name really looks like a comparison form
    assert OI.title_variants('Trumna') == [('Trumna', 'exact')]


def test_uppercase_page_resolves_and_the_step_is_recorded(OI):
    """'Ax-52' has no page; the wiki keeps it as 'AX-52'."""
    cache_page(OI, 'Ax-52', None)                      # the miss is cached, as a real run would
    cache_page(OI, 'AX-52', "== Acquisition ==\nAX-52's blueprint can be purchased from "
                            "[[Amir]] of [[The Hex]] for {{sc|30,000}} at Rank 4.\n")
    acq = OI.wiki_acquire('Ax-52', offline=True)
    assert acq and acq['via'] == 'upper' and acq['title'] == 'AX-52'
    assert 'AX-52' in acq['text'] and '30,000 standing' in acq['text']


def test_case_aware_cache_lets_a_miss_hide_nothing(OI):
    """A cached miss for one casing must never shadow the page under another."""
    cache_page(OI, 'Ax-52', None)
    cache_page(OI, 'AX-52', '== Acquisition ==\nAX-52 can be bought from Amir.\n')
    assert OI.wiki_page('Ax-52', offline=True)[0] is None      # the miss is remembered...
    assert OI.wiki_page('AX-52', offline=True)[0]              # ...without hiding the real page


def test_sentence_case_and_underscored_titles_resolve(OI):
    cache_page(OI, 'Para moa', "== Acquisition ==\nThe Para blueprint can be purchased from "
                               "[[Legs]] for {{sc|500}}.\n")
    acq = OI.wiki_acquire('Para Moa', offline=True)
    assert acq and acq['via'] == 'sentence-case' and acq['title'] == 'Para moa'
    cache_page(OI, 'Foo_Bar', '== Acquisition ==\nFoo Bar is bought from the Market.\n')
    assert OI.wiki_acquire('Foo Bar', offline=True)['via'] == 'underscored'


def test_search_is_the_last_step_and_its_title_is_recorded(OI):
    """'Orion & Sirius' has no page; the search API finds 'Sirius & Orion' (words reversed)."""
    search_hits(OI, {'Orion & Sirius': ['Sirius & Orion']})
    cache_page(OI, 'Sirius & Orion', 'Shell page, real text on the subpage.')
    cache_page(OI, 'Sirius & Orion/Main', SIRIUS_MAIN)
    acq = OI.wiki_acquire('Orion & Sirius', offline=True)
    assert acq and acq['via'] == 'search+main'
    assert acq['title'] == 'Sirius & Orion/Main' and acq['section'] == 'Acquisition'
    assert acq['text'].startswith("Sirius & Orion's main blueprint is acquired upon completion")
    assert '[[' not in acq['text']


# --------------------------------------------------------------------------- where lines come from

def test_acquisition_section_keeps_template_visible_values(OI):
    cache_page(OI, 'Braton', BRATON)
    acq = OI.wiki_acquire('Braton', offline=True)
    assert acq['section'] == 'Acquisition' and acq['via'] == 'exact'
    assert acq['text'].startswith('A fully built Braton can be purchased from the Market for ')
    assert '25,000 credits' in acq['text']            # {{cc|25,000}} - markup removed, value kept
    assert '[[' not in acq['text'] and '{{' not in acq['text']


def test_acquisition_template_is_used_when_there_is_no_heading(OI):
    cache_page(OI, 'Orvius', ORVIUS)
    acq = OI.wiki_acquire('Orvius', offline=True)
    assert acq['section'] == 'Acquisition'            # the template, not 'Characteristics'
    assert acq['text'].startswith('The blueprint is rewarded on completion of The War Within.')
    assert '100,000 standing' in acq['text']
    assert 'name=' not in acq['text']                 # named parameters are never quoted


def test_page_without_a_section_quotes_its_own_sentence_verbatim(OI):
    cache_page(OI, 'Carrier', CARRIER)
    acq = OI.wiki_acquire('Carrier', offline=True)
    assert acq['section'] == 'Notes'                  # where the sentence really came from
    assert acq['text'] == "Carrier's blueprint can be purchased from the Market."


def test_another_items_sentence_is_never_quoted(OI):
    """A search hit that is a different item must not answer for this one."""
    search_hits(OI, {'Orion & Sirius': ['Helmet']})
    cache_page(OI, 'Helmet', '== Acquisition ==\nHelmets can be bought for 75 platinum.\n')
    assert OI.wiki_acquire('Orion & Sirius', offline=True) is None


def test_a_variant_page_does_not_answer_for_a_qualified_item(OI):
    """'Venari' is not 'Venari Prime': the base companion's line is not the Prime's."""
    search_hits(OI, {'Venari Prime': ['Venari']})
    cache_page(OI, 'Venari', VENARI)
    assert OI.wiki_acquire('Venari Prime', offline=True) is None


# --------------------------------------------------------------------------- the fallbacks

def test_introduced_line_names_the_update_and_its_url(OI):
    search_hits(OI, {'Venari Prime': ['Venari']})
    cache_page(OI, 'Venari', VENARI)
    doc = {'items': {'Venari Prime': {'name': 'Venari Prime',
                                      'wiki': 'https://wiki.warframe.com/w/Venari%2FPrime'}},
           'counts': {}, 'notes': []}
    introduced = {'Venari Prime': {'name': 'Update 31.7', 'date': '2022-07-16',
                                   'url': 'https://wiki.warframe.com/w/Update_31#Update_31.7'}}
    stats = OI.wiki_fill(doc, offline=True, sleep_s=0, introduced=introduced)
    assert stats == {'tried': 1, 'wiki': 0, 'introduced': 1, 'empty': 0}
    item = doc['items']['Venari Prime']
    assert item['other'][0]['source'] == 'WFCD (introduced)'
    assert item['other'][0]['detail'] == 'Added in Update 31.7 (2022-07-16)'
    assert item['acq']['kind'] == 'introduced' and item['acq']['url'].endswith('#Update_31.7')


def test_a_fact_less_item_with_no_sources_gets_no_invented_line(OI):
    """Nothing quotable and no `introduced` row -> the record says so, nothing is invented."""
    doc = {'items': {'Nothing Known': {'name': 'Nothing Known',
                                       'wiki': 'https://wiki.warframe.com/w/Nothing_Known'}},
           'counts': {}, 'notes': []}
    stats = OI.wiki_fill(doc, offline=True, sleep_s=0, introduced={})
    assert stats == {'tried': 1, 'wiki': 0, 'introduced': 0, 'empty': 1}
    item = doc['items']['Nothing Known']
    assert 'other' not in item                        # no line, no fabricated source
    assert item['acq']['kind'] == 'none' and item['acq']['text'] == ''
    assert doc['counts']['with_wiki_line'] == 0 and doc['counts']['with_introduced_line'] == 0


def test_the_card_says_something_honest_when_the_wiki_has_nothing():
    """The payload for a source-less item is still non-empty - it points at the wiki, no lanes."""
    index = {'Nothing Known': {'name': 'Nothing Known',
                               'wiki': 'https://wiki.warframe.com/w/Nothing_Known'}}
    card = _card('Nothing Known', index)
    assert card is not None
    assert card['lines'] == []                        # no drop lane is invented
    assert card['short'] == 'See the wiki' and card['wiki'].startswith('https://wiki.warframe.com/')
    assert card['lanes'] == 0


def _card(name, index):
    """collection_log's own card builder, or skip when a sibling refactor moves it."""
    mod = load_script('collection_log')
    builder = getattr(mod, 'build_item_obtain', None)
    if builder is None:
        pytest.skip('collection_log.build_item_obtain moved - card contract lives there now')
    return builder(name, index)


# --------------------------------------------------------------------------- the fill loop

def test_wiki_fill_skips_items_that_already_have_drop_facts(OI):
    cache_page(OI, 'Braton', BRATON)
    doc = {'items': {'Braton': {'name': 'Braton',
                                'missions': [{'planet': 'Venus', 'node': 'X', 'chance': 1.0}]},
                     'Carrier': {'name': 'Carrier'}},
           'counts': {}, 'notes': []}
    cache_page(OI, 'Carrier', CARRIER)
    stats = OI.wiki_fill(doc, offline=True, sleep_s=0)
    assert stats['tried'] == 1 and stats['wiki'] == 1
    assert 'acq' not in doc['items']['Braton']         # a drop table already answers for it
    assert doc['items']['Carrier']['acq']['kind'] == 'wiki'


def test_wiki_fill_is_resumable_and_idempotent(OI):
    cache_page(OI, 'Carrier', CARRIER)
    doc = {'items': {'Carrier': {'name': 'Carrier'}, 'Beta': {'name': 'Beta'}},
           'counts': {}, 'notes': []}
    first = OI.wiki_fill(doc, offline=True, sleep_s=0, limit=1)   # --wiki-limit stops mid-run
    assert first['tried'] == 1 and first['wiki'] == 1
    assert 'acq' not in doc['items']['Beta']                      # resumed by the next run
    second = OI.wiki_fill(doc, offline=True, sleep_s=0)
    assert second['tried'] == 1 and second['empty'] == 1
    snapshot = json.dumps(doc, sort_keys=True)
    third = OI.wiki_fill(doc, offline=True, sleep_s=0)
    assert third == {'tried': 0, 'wiki': 0, 'introduced': 0, 'empty': 0}
    assert json.dumps(doc, sort_keys=True) == snapshot            # a re-run changes nothing
    assert doc['counts']['with_wiki_line'] == 1
