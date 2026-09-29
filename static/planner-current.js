// Current Loadout: what the game save says the player is actually using, read-only.
//
// Data comes from /api/planner/current (the server reads the local AlecaFrame save and caches the
// translated snapshot) and the numbers come from the normal /api/planner/compute route - this file
// does no Warframe arithmetic and never writes to the snapshot. Cloning hands a plain document to
// the planner; the imported state itself is server-side and out of reach of the page.
(function () {
  'use strict';

  var P = window.WFMPlanner;
  if (!P) return;

  var current = null;          // the last /api/planner/current payload
  var selected = null;         // the category whose detail is open
  var detailFor = {};          // engine answer per category: any re-render shows the last one
  var busy = false;

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
        if (k === 'text') node.textContent = attrs[k];
        else if (k === 'class') node.className = attrs[k];
        else if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
      }
    }
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }

  var ORDER = ['warframe', 'primary', 'secondary', 'melee', 'companion', 'companion_weapon'];
  var LABEL = { warframe: 'Warframe', primary: 'Primary', secondary: 'Secondary', melee: 'Melee',
    companion: 'Companion', companion_weapon: 'Companion weapon' };

  function value(block) { return block && block.value !== undefined ? block.value : null; }

  function rankText(category) {
    var block = current.categories[category].equipment_rank || {};
    if (block.value === null || block.value === undefined) return 'Rank unknown';
    return 'Rank ' + block.value;
  }

  function configText(category) {
    var block = current.categories[category].config || {};
    if (!block.label) return 'Config unknown';
    return 'Config ' + block.label;
  }

  // ------------------------------------------------------------------ the card

  function render() {
    var card = $('plCurrent');
    if (!card) return;
    var body = $('plCurrentList');
    var meta = $('plCurrentMeta');
    var note = $('plCurrentNote');
    var actions = $('plCurrentActions');
    if (!body) return;
    clear(body);

    var state = current ? current.state : 'loading';
    if (state === 'loading') {
      card.hidden = false;
      if (meta) meta.textContent = 'Reading the local save…';
      if (note) note.textContent = '';
      if (actions) actions.hidden = true;
      return;
    }
    if (state !== 'ok') {
      // §16: every failure mode is named, and a previous snapshot is shown only as last-known
      card.hidden = false;
      if (meta) meta.textContent = '';
      if (actions) actions.hidden = true;
      var line = el('p', { class: 'pl-cur-state', text: current.error || 'Current build unavailable' });
      body.appendChild(line);
      if (current.detail && current.detail.expected) {
        body.appendChild(el('p', { class: 'dim small', text: 'Looked for ' + current.detail.expected }));
      }
      if (current.last_good && current.last_good.snapshot) {
        body.appendChild(el('p', { class: 'dim small',
          text: 'Showing the last import from ' + agoText(current.last_good.read_at) }));
        current = { state: 'ok', snapshot: current.last_good.snapshot, last_good: true };
        render();
      }
      if (note) note.textContent = '';
      return;
    }

    card.hidden = false;
    var snap = current.snapshot;
    var cats = snap.categories || {};
    if (meta) {
      meta.textContent = '';
      meta.appendChild(el('span', { class: 'dim small', text: snap.freshness ? snap.freshness.label : '' }));
    }
    ORDER.forEach(function (category) {
      var imported = cats[category];
      if (!imported) return;
      var eq = value(imported.equipment) || {};
      var row = el('button', { class: 'pl-cur-row', type: 'button',
        'data-category': category, 'aria-pressed': selected === category ? 'true' : 'false',
        title: 'Show the imported ' + LABEL[category].toLowerCase() + ' build' });
      row.appendChild(el('span', { class: 'pl-cur-kind', text: LABEL[category] }));
      row.appendChild(el('span', { class: 'pl-cur-name' + (eq.slug ? '' : ' unknown'),
        text: eq.name || 'Unknown item' }));
      row.appendChild(el('span', { class: 'pl-cur-tags dim small',
        text: configText(category) + ' · ' + rankText(category) }));
      row.addEventListener('click', function () { select(category); });
      body.appendChild(row);
    });
    if (!body.childNodes.length) {
      body.appendChild(el('p', { class: 'pl-cur-state',
        text: 'Current build not available from this data source.' }));
    }

    if (actions) {
      actions.hidden = false;
      var view = $('plCurrentView');
      var cloneBtn = $('plCurrentClone');
      if (view) view.disabled = !selected;
      if (cloneBtn) cloneBtn.disabled = !selected;
    }
    if (note) note.textContent = (snap.freshness && snap.freshness.warning) || '';
    renderDetail();
  }

  function agoText(ts) {
    if (!ts) return 'an unknown time ago';
    var age = Math.max(0, Math.floor(Date.now() / 1000) - ts);
    if (age < 5400) return Math.floor(age / 60) + ' minutes ago';
    if (age < 172800) return Math.floor(age / 3600) + ' hours ago';
    return Math.floor(age / 86400) + ' days ago';
  }

  // ------------------------------------------------------------------ the detail

  function select(category) {
    selected = category === selected ? null : category;
    if (selected) delete detailFor[selected];
    render();
    if (selected) computeDetail();
  }

  function slotKey(entry) {
    return (entry.kind || 'normal') + ':' + entry.index;
  }

  function buildFor(category) {
    // the imported build in the shape every other planner call uses - translation only, no maths
    var imported = current.snapshot.categories[category];
    var cfg = configBlock(imported);
    if (!cfg) return null;
    // the engine's own slot contract, exactly as the page's build() writes it
    var slots = (cfg.slots || []).map(function (entry) {
      var mod = entry.mod || {};
      var filled = mod.uniqueName
        ? (entry.mod_rank === null || entry.mod_rank === undefined
          ? { id: mod.uniqueName } : { id: mod.uniqueName, rank: entry.mod_rank })
        : null;
      var slot = { kind: entry.kind,
        index: entry.kind === 'normal' ? entry.index : null,   // aura/exilus/stance take no index
        polarity: entry.polarity || null, mod: filled };
      if (entry.kind === 'exilus') slot.unlocked = false;   // unknown in the source: stated, not hidden
      return slot;
    });
    var eq = value(imported.equipment) || {};
    var out = { config: cfg.label || 'A', equipment_id: eq.uniqueName, slots: slots,
      orokin: false, exilus_unlocked: false, mastery_rank: P.storage().mastery_rank };
    var rank = value(imported.equipment_rank);
    if (rank !== null && rank !== undefined) out.equipment_rank = rank;
    return out;
  }

  function configBlock(imported) {
    var active = imported.config || {};
    var list = imported.configs || [];
    if (active.value !== null && active.value !== undefined) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].index === active.value) return list[i];
      }
    }
    return list.length ? list[0] : null;
  }

  function computeDetail() {
    var category = selected;
    var body = $('plCurrentDetail');
    if (!body) return;
    clear(body);
    body.appendChild(el('p', { class: 'dim small', text: 'Calculating from the engine…' }));
    var build = buildFor(category);
    if (!build) {
      clear(body);
      body.appendChild(el('p', { class: 'pl-cur-state',
        text: 'Current build not available from this data source.' }));
      return;
    }
    P.api.compute(build).then(function (out) {
      detailFor[category] = out || null;
      if (selected === category) renderDetail();
    }).catch(function () {
      detailFor[category] = null;
      if (selected === category) renderDetail();
    });
  }

  function renderDetail() {
    var body = $('plCurrentDetail');
    if (!body) return;
    clear(body);
    var detail = selected ? (detailFor[selected] || null) : null;   // one answer per category
    if (!selected) {
      body.appendChild(el('p', { class: 'dim small', text: 'Pick a slot above for its build.' }));
      return;
    }
    var imported = current.snapshot.categories[selected];
    var cfg = configBlock(imported);
    var eq = value(imported.equipment) || {};
    var head = el('div', { class: 'pl-cur-dhead' });
    head.appendChild(el('span', { class: 'pl-cur-dname', text: eq.name || 'Unknown item' }));
    head.appendChild(el('span', { class: 'dim small', text: (cfg && cfg.label ? 'Config ' + cfg.label
      : 'Current configuration') + ' · ' + rankText(selected) }));
    body.appendChild(head);

    if (!cfg) {
      body.appendChild(el('p', { class: 'pl-cur-state',
        text: 'Current build not available from this data source.' }));
      return;
    }
    if (cfg.mods_available === false) {
      body.appendChild(el('p', { class: 'dim small',
        text: 'No mods are installed in this configuration.' }));
    }

    var list = el('div', { class: 'pl-cur-mods' });
    (cfg.slots || []).forEach(function (entry) {
      var mod = entry.mod || {};
      var row = el('div', { class: 'pl-cur-mod' + (mod.uniqueName ? '' : ' unknown') });
      row.appendChild(el('span', { class: 'pl-cur-slot', text: slotLabel(entry) }));
      row.appendChild(el('span', { class: 'pl-cur-mname', text: mod.name || 'Unknown mod' }));
      row.appendChild(el('span', { class: 'pl-cur-mrank dim small',
        text: entry.mod_rank === null || entry.mod_rank === undefined
          ? 'rank unknown' : 'R' + entry.mod_rank }));
      row.appendChild(el('span', { class: 'pl-cur-mpol dim small', text: entry.polarity || '' }));
      list.appendChild(row);
    });
    body.appendChild(list);

    (cfg.unsupported || []).forEach(function (entry) {
      var mod = entry.mod || {};
      body.appendChild(el('div', { class: 'pl-cur-mod unsupported' }, [
        el('span', { class: 'pl-cur-slot', text: slotLabel(entry) }),
        el('span', { class: 'pl-cur-mname', text: mod.name || 'Not in the catalogue' }),
        el('span', { class: 'dim small', text: entry.unsupported || 'not imported' })
      ]));
    });

    body.appendChild(el('p', { class: 'dim small',
      text: 'Capacity assumes no Catalyst or Exilus.' }));
    var facts = el('div', { class: 'pl-cur-facts' });
    var forma = imported.forma_count || {};
    facts.appendChild(el('span', { class: 'dim small', text: forma.value === null || forma.value === undefined
      ? 'Forma unknown' : 'Forma ' + forma.value }));
    facts.appendChild(el('span', { class: 'dim small', text: 'Catalyst unknown' }));
    facts.appendChild(el('span', { class: 'dim small', text: 'Exilus unknown' }));
    body.appendChild(facts);

    if (detail) {
      var read = (cfg.slots || []).filter(function (s) { return (s.mod || {}).uniqueName; }).length;
      var verdict = el('div', { class: 'pl-cur-verdict' });
      verdict.appendChild(el('span', { class: 'dim small', text: read + ' mods read' }));
      var unsupported = (detail.unsupported && (detail.unsupported.mods || []).length) || 0;
      verdict.appendChild(el('span', { class: 'dim small',
        text: unsupported + ' with unmodelled effects' }));
      var errors = (detail.validation && (detail.validation.errors || []).length) || 0;
      verdict.appendChild(el('span', { class: 'dim small',
        text: errors ? errors + (errors === 1 ? ' validation issue' : ' validation issues')
          : 'build validates' }));
      // the engine's drain block: total is the charge used, remaining is what is left of capacity
      var drain = detail.capacity && detail.capacity.drain;
      if (drain && typeof drain.total === 'number' && typeof drain.remaining === 'number') {
        detail.capacityCheck = 'Drain ' + drain.total + ' · capacity ' + (drain.total + drain.remaining);
      }
      body.appendChild(verdict);
      (detail.validation && detail.validation.errors || []).slice(0, 4).forEach(function (e) {
        body.appendChild(el('p', { class: 'pl-cur-state', text: e.code + ' · ' + (e.message || '') }));
      });
      if (detail.capacityCheck) {
        body.appendChild(el('p', { class: 'dim small', text: detail.capacityCheck }));
      }
      if (errors) withCatalyst(selected, body);
    }
  }

  // A build that overflows without a Catalyst is the honest reading of a source that never
  // records one - so the page asks the engine the other question too and says it is a hypothetical.
  function withCatalyst(category, body) {
    var build = buildFor(category);
    if (!build) return;
    build.orokin = true;
    P.api.compute(build).then(function (out) {
      if (selected !== category || !out) return;
      var errors = (out.validation && (out.validation.errors || [])) || [];
      var line = errors.length
        ? 'Still short with a Catalyst · ' + errors[0].code
        : 'Fits with a Catalyst installed';
      body.appendChild(el('p', { class: 'dim small', text: line }));
    }).catch(function () { /* the hypothesis is optional; its absence is not an error */ });
  }

  function slotLabel(entry) {
    if (entry.kind === 'aura') return 'Aura';
    if (entry.kind === 'exilus') return 'Exilus';
    if (entry.kind === 'stance') return 'Stance';
    if (entry.save_index !== null && entry.save_index !== undefined) return String(entry.save_index + 1);
    return '-';
  }

  // ------------------------------------------------------------------ clone

  function clone() {
    if (busy || !selected) return;
    var note = $('plCurrentNote');
    var select_ = $('plCurrentConfig');
    var configName = (select_ && select_.value) || 'A';
    busy = true;
    if (note) note.textContent = 'Cloning…';
    P.api.cloneCurrent({ category: selected, config: configName,
      mastery_rank: P.storage().mastery_rank })
      .then(function (out) {
        busy = false;
        if (!out || out.ok === false) {
          if (note) note.textContent = (out && out.error) || 'Clone failed';
          return;
        }
        if (!P.adopt(out.doc)) {              // a copy enters the planner; nothing moves on the server
          if (note) note.textContent = 'The planner rejected the cloned build';
          return;
        }
        render();                             // renders first: the clone note is the last word
        if (note) {
          var missing = (out.unknown_fields || []).length;
          note.textContent = 'Cloned to Config ' + configName + (missing
            ? ' · ' + missing + ' fields not in the source' : '');
        }
      }).catch(function () {
        busy = false;
        if (note) note.textContent = 'Clone failed';
      });
  }

  // ------------------------------------------------------------------ wiring

  function load(force) {
    P.api.current(!!force)
      .then(function (out) {
        current = out || { state: 'malformed', error: 'no payload' };
        if (!current.snapshot) current.snapshot = null;
        if (current.state === 'ok' && current.snapshot) {
          current.categories = current.snapshot.categories || {};
        }
        render();
        if (selected) computeDetail();
      }).catch(function () {
        current = { state: 'malformed', error: 'The planner could not reach its own server.' };
        render();
      });
  }

  function init() {
    var refresh = $('plCurrentRefresh');
    if (refresh) refresh.addEventListener('click', function () { load(true); });
    var cloneBtn = $('plCurrentClone');
    if (cloneBtn) cloneBtn.addEventListener('click', clone);
    var view = $('plCurrentView');
    if (view) view.addEventListener('click', function () {
      if (!selected && current && current.snapshot) {
        var cats = current.snapshot.categories || {};
        for (var i = 0; i < ORDER.length; i++) {
          if (cats[ORDER[i]]) { select(ORDER[i]); return; }
        }
      }
      var box = $('plCurrentDetail');
      if (box && box.scrollIntoView) box.scrollIntoView({ block: 'nearest' });
    });
    load(false);
  }

  P.on('ready', function () { current = null; selected = null; detailFor = {}; load(false); });
  P.on('storage', function () { /* the imported card is not derived from planner storage */ });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
