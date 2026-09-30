/* planner-stats.js - the "what does it produce" half of the planner page.
 *
 * Three cards on top of planner.js:
 *   #plStats    - every stat the engine answered, grouped, each with its delta against the
 *                 unmodded item and a click-through to its trace
 *   #plTraces   - the trace itself: base, each modifier (mod + rank + value), the final value
 *   #plElements - damage composition (combined elements and the mods that built them), the
 *                 multi-shot/crit expectations, DPS with its stated assumptions
 *
 * Every number here is printed straight from the last /api/planner/compute answer, and every
 * game rule (capacity, drain, tiers, DPS) is the engine's. The only figures this file derives
 * are the delta against the engine's own baseline answer and the bars' share of two engine
 * numbers - no rule of the game is re-implemented here.
 */
'use strict';

(function () {
  var P = window.WFMPlanner;
  if (!P) return;

  var fmt = P.fmt;

  // stat key -> {label, unit, group, hint}. Presentation only: the engine's trace carries its
  // own label and unit, and a stat with a trace always uses those.
  var WEAPON_STATS = [
    ['modded_base_damage', 'Modded base damage', 'flat', 'Offence',
      'the item\'s base damage after +damage mods'],
    ['damage_per_shot', 'Damage per shot', 'flat', 'Offence', 'per projectile x multishot'],
    ['per_projectile_total', 'Damage per projectile', 'flat', 'Offence', null],
    ['damage_per_shot_expected_crit', 'Damage per shot (crit expected)', 'flat', 'Offence',
      'weighted by the critical tiers'],
    ['burst_dps', 'Burst DPS', 'flat', 'Offence', 'average shot x effective fire rate'],
    ['sustained_dps', 'Sustained DPS', 'flat', 'Offence',
      'burst reduced by reload time'],
    ['critical_chance', 'Critical chance', 'percent', 'Critical', null],
    ['critical_multiplier', 'Critical multiplier', 'multiplier', 'Critical', null],
    ['critical_tier', 'Critical tier', 'tier', 'Critical',
      'how many guaranteed crits deep the build is'],
    ['critical_expected_multiplier', 'Expected crit multiplier', 'multiplier', 'Critical',
      'guaranteed tier + the chance of the next'],
    ['viral_amplifier', 'Viral amplifier', 'multiplier', 'Target',
      'viral-amplified damage to health'],
    ['damage_to_health_expected_crit', 'Damage per shot to health', 'flat', 'Target',
      'viral-amplified damage to health, crit-weighted'],
    ['status_chance', 'Status chance', 'percent', 'Status', null],
    ['status_procs_per_projectile', 'Procs per projectile', 'flat', 'Status',
      'status chance as expected procs'],
    ['status_expected_procs_per_shot', 'Expected procs per shot', 'flat', 'Status',
      'per projectile procs x multishot'],
    ['multishot', 'Multishot', 'multiplier', 'Cadence', null],
    ['multishot_extra_chance', 'Extra projectile chance', 'percent', 'Cadence',
      'chance of the next whole projectile'],
    ['fire_rate', 'Fire rate', 'rate', 'Cadence', 'rounds per second'],
    ['magazine_size', 'Magazine', 'flat', 'Cadence', null],
    ['reload_time', 'Reload time', 'seconds', 'Cadence', null]
  ];
  var FRAME_STATS = [
    ['health', 'Health', 'flat', 'Survivability', null],
    ['shield', 'Shield', 'flat', 'Survivability', null],
    ['armor', 'Armor', 'flat', 'Survivability', null],
    ['energy', 'Energy', 'flat', 'Survivability', null],
    ['sprint_speed', 'Sprint speed', 'flat', 'Survivability', null],
    ['ability_strength', 'Ability strength', 'percent', 'Abilities', null],
    ['ability_duration', 'Ability duration', 'percent', 'Abilities', null],
    ['ability_range', 'Ability range', 'percent', 'Abilities', null],
    ['ability_efficiency', 'Ability efficiency', 'percent', 'Abilities',
      'capped at 175% for cost'],
    ['ability_cost_multiplier', 'Ability cost multiplier', 'multiplier', 'Abilities', null]
  ];
  var EXTRA_GROUPS;
  // damage_<type> keys are read from the damage dict below, so the group is filled at render time.

  var DAMAGE_LABEL = { impact: 'Impact', puncture: 'Puncture', slash: 'Slash', heat: 'Heat',
    cold: 'Cold', electricity: 'Electricity', toxin: 'Toxin', blast: 'Blast',
    corrosive: 'Corrosive', gas: 'Gas', magnetic: 'Magnetic', radiation: 'Radiation',
    viral: 'Viral', true_damage: 'True' };

  function unitText(value, unit) {
    if (value === null || value === undefined) return '—';
    if (unit === 'percent') return fmt.pct(value);
    if (unit === 'multiplier') return fmt.multiplier(value);
    if (unit === 'seconds') return fmt.seconds(value);
    if (unit === 'rate') return fmt.num(value) + '/s';
    if (unit === 'tier') return 'T' + fmt.num(value);
    return fmt.num(value);
  }

  function statDefs(kind) {
    return kind === 'warframe' ? FRAME_STATS : WEAPON_STATS;
  }

  // ------------------------------------------------------------------ stat panel
  function renderStats() {
    var body = document.getElementById('plStatBody');
    if (!body) return;
    P.clear(body);
    var out = P.result();
    var equipment = P.equipment();
    var meta = document.getElementById('plStatsMeta');
    if (!equipment) {
      body.appendChild(el('div', { class: 'dim small', text: 'Pick equipment to see its stats.' }));
      if (meta) meta.textContent = '';
      return;
    }
    if (!out || !out.result) {
      // a refusal carries no numeric result but is still an answer: read the whole thing
      var full = P.answer ? P.answer() : null;
      var refused = full && full.validation && (full.validation.errors || []).length;
      var why = refused ? 'This build does not validate - see Validation.'
        : (P.error() ? 'No answer from the engine.' : 'loading…');
      body.appendChild(el('div', { class: 'dim small', text: why }));
      if (meta) meta.textContent = '';
      var view = document.getElementById('plStatsView');
      if (view) view.hidden = true;
      return;
    }
    var stats = out.result.stats || {};
    var traces = out.result.traces || {};
    var baseline = (out.baseline && out.baseline.stats) || {};
    var isFrameish = Object.prototype.hasOwnProperty.call(stats, 'health') &&
      !Object.prototype.hasOwnProperty.call(stats, 'modded_base_damage');
    var defs = statDefs(isFrameish ? 'warframe' : equipment.kind);
    var groups = [];
    defs.forEach(function (def) {
      if (!Object.prototype.hasOwnProperty.call(stats, def[0])) return;
      var group = null;
      for (var i = 0; i < groups.length; i++) if (groups[i].name === def[3]) group = groups[i];
      if (!group) { group = { name: def[3], rows: [] }; groups.push(group); }
      group.rows.push({ key: def[0], label: def[1], unit: def[2], hint: def[4] });
    });
    // the per-damage-type rows come out of the damage dict, not a fixed list
    var damageRows = [];
    var damageSplit = (out.result.damage && out.result.damage.per_projectile) || {};
    Object.keys(damageSplit).forEach(function (element) {
      damageRows.push({ key: 'damage_' + element,
        label: (DAMAGE_LABEL[element] || fmt.label(element)) + ' damage', unit: 'flat',
        hint: 'per projectile', element: element });
    });
    if (damageRows.length) groups.push({ name: 'Damage types', rows: damageRows });
    // anything the engine answered that no table above covers
    var covered = {};
    groups.forEach(function (g) { g.rows.forEach(function (r) { covered[r.key] = true; }); });
    var extra = Object.keys(stats).sort().filter(function (k) {
      return !covered[k] && stats[k] !== null && stats[k] !== undefined;
    });
    if (extra.length) {
      groups.push({ name: 'Other', rows: extra.map(function (k) {
        return { key: k, label: (traces[k] && traces[k].label) || fmt.label(k),
          unit: (traces[k] && traces[k].unit) || 'flat', hint: null };
      }) });
    }

    groups.forEach(function (group) {
      var wrap = el('div', { class: 'pl-stat-group' });
      wrap.appendChild(el('div', { class: 'pl-sg-head', text: group.name }));
      group.rows.forEach(function (row) {
        wrap.appendChild(statRow(row, stats[row.key], baseline[row.key],
          !!traces[traceKeyFor(row.key)]));
      });
      body.appendChild(wrap);
    });

    var traced = Object.keys(traces).length;
    if (meta) {
      meta.textContent = '· ' + Object.keys(stats).length + ' values · ' + traced +
        ' with a trace';
    }
    var view = document.getElementById('plStatsView');
    if (view) view.hidden = false;
    // One predictable default so the Why panel is not an empty box on load: the value a player
    // reads first - health for a frame, damage for a weapon. Any click replaces it from then on.
    if (!P.storage().ui.trace) {
      var want = isFrameish
        ? ['health', 'shield', 'armour', 'armor'] : ['base_damage', 'modded_base_damage', 'damage'];
      for (var wi = 0; wi < want.length; wi++) {
        var traceKey = traceKeyFor(want[wi]);
        if (traceKey && traces[traceKey]) { openTrace(traceKey); break; }
      }
    }
    highlightTraced();
  }

  // A stat row and the engine's trace for it do not always share a key (the engine traces
  // 'damage' and 'impact'; the stat dict carries 'modded_base_damage' and 'damage_impact').
  var TRACE_ALIAS = { modded_base_damage: 'damage', damage_impact: 'impact',
    damage_puncture: 'puncture', damage_slash: 'slash', critical_expected_multiplier: null,
    multishot_extra_chance: null };

  function traceKeyFor(statKey) {
    var out = TRACE_ALIAS.hasOwnProperty(statKey) ? TRACE_ALIAS[statKey] : statKey;
    return out || null;
  }

  function statRow(row, value, baseValue, hasTrace) {
    var delta = null;
    if (baseValue !== null && baseValue !== undefined && value !== null && value !== undefined &&
        Number(baseValue) !== Number(value)) {
      delta = Number(value) - Number(baseValue);
    }
    var node = el('button', { class: 'pl-stat-row' + (hasTrace ? ' has-trace' : ''),
      type: 'button', 'data-stat': row.key,
      'aria-pressed': P.storage().ui.trace === row.key ? 'true' : 'false',
      title: (row.hint ? row.hint + ' · ' : '') + (hasTrace ? 'click for the trace'
        : 'the engine reports this value without a breakdown') });
    node.appendChild(el('span', { class: 'pl-stat-name', text: row.label }));
    node.appendChild(el('span', { class: 'pl-stat-val' + (delta !== null ? ' changed' : ''),
      text: unitText(value, row.unit) }));
    if (delta !== null && row.unit !== 'tier') {
      node.appendChild(el('span', { class: 'pl-stat-delta ' + (delta > 0 ? 'up' : 'down'),
        text: (delta > 0 ? '+' : '') + fmt.num(delta) + (row.unit === 'percent' ? '%' : ''),
        title: 'difference from the unmodded item (' + unitText(baseValue, row.unit) + ')' }));
    } else {
      node.appendChild(el('span', { class: 'pl-stat-delta',
        text: baseValue !== null && baseValue !== undefined && baseValue !== value
          ? 'vs ' + unitText(baseValue, row.unit) : '' }));
    }
    if (hasTrace) {
      node.addEventListener('click', function () { openTrace(traceKeyFor(row.key)); });
    }
    return node;
  }

  function highlightTraced() {
    var rows = document.querySelectorAll('#plStatBody .pl-stat-row');
    Array.prototype.forEach.call(rows, function (node) {
      // the stat key and the trace key are not always the same word (modded_base_damage -> damage),
      // so a row highlights when its TRACE is the selected one, not only when the keys match
      node.setAttribute('aria-pressed',
        traceKeyFor(node.getAttribute('data-stat')) === P.storage().ui.trace ? 'true' : 'false');
    });
    var label = document.getElementById('plTraceStat');
    if (label) {
      var stat = P.storage().ui.trace;
      var trace = stat && ((P.result() || {}).result || {}).traces
        ? ((P.result().result || {}).traces || {})[stat] : null;
      label.textContent = trace ? '· ' + (trace.label || fmt.label(stat)) : '';
    }
  }

  // ------------------------------------------------------------------ trace
  function openTrace(stat) {
    P.storage().ui.trace = stat;
    P.save();
    renderTrace();
    highlightTraced();
  }

  function renderTrace() {
    var box = document.getElementById('plTraceBody');
    if (!box) return;
    P.clear(box);
    var stat = P.storage().ui.trace;
    var out = P.result();
    var traces = (out && out.result && out.result.traces) || {};
    var trace = stat ? traces[stat] : null;
    var copyBtn = document.getElementById('plTraceCopy');
    if (!trace) {
      box.appendChild(el('div', { class: 'dim small',
        text: stat ? 'The engine reports ' + fmt.label(stat) + ' without a step-by-step trace.'
          : 'Pick a stat for its trace.' }));
      if (copyBtn) copyBtn.hidden = true;
      return;
    }
    if (copyBtn) copyBtn.hidden = false;
    box.appendChild(el('div', { class: 'pl-tr-label',
      text: (trace.label || fmt.label(stat)) + (trace.unit === 'percent' ? ' (%)' : '') }));
    var baseLine = el('div', { class: 'pl-tr-line' }, [
      el('span', { class: 'pl-tr-src', text: 'Base' }),
      el('span', { class: 'pl-tr-val', text: unitText(trace.base, trace.unit) })
    ]);
    box.appendChild(baseLine);
    (trace.modifiers || []).forEach(function (m) {
      var src = el('span', { class: 'pl-tr-src' });
      src.appendChild(el('span', { class: 'mod',
        text: (m.mod_name || m.source || 'mod') + (m.rank !== null && m.rank !== undefined
          ? ' R' + m.rank : '') }));
      var tail = m.source && m.mod_name && m.source !== m.mod_name ? ' (' + m.source + ')' : '';
      if (tail) src.appendChild(document.createTextNode(tail));
      var value = m.unit === 'percent' ? '+' + fmt.num(m.value) + '%'
        : fmt.signed(m.value, m.unit === 'percent' ? 'percent' : 'flat');
      box.appendChild(el('div', { class: 'pl-tr-line' }, [
        src, el('span', { class: 'pl-tr-val', text: value })
      ]));
    });
    if (trace.intermediate !== null && trace.intermediate !== undefined &&
        trace.intermediate !== trace.final) {
      box.appendChild(el('div', { class: 'pl-tr-line' }, [
        el('span', { class: 'pl-tr-src', text: trace.intermediate_label || 'Before the final step' }),
        el('span', { class: 'pl-tr-val', text: fmt.num(trace.intermediate) })
      ]));
    }
    box.appendChild(el('div', { class: 'pl-tr-final' }, [
      el('span', { text: 'Final' }),
      el('span', { text: unitText(trace.final, trace.unit) })
    ]));
    (trace.notes || []).forEach(function (note) {
      box.appendChild(el('div', { class: 'pl-tr-note', text: note }));
    });
    if (!(trace.modifiers || []).length && !(trace.notes || []).length) {
      box.appendChild(el('div', { class: 'pl-tr-note',
        text: 'Nothing modifies this value on this build.' }));
    }
    var copy = document.getElementById('plTraceCopy');
    if (copy) {
      copy.onclick = function () {
        var text = traceText(trace);
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text);
        }
        if (window.console) console.log(text);
      };
    }
  }

  // Plain-text form of the engine's trace, for the clipboard and the console.
  function traceText(trace) {
    var lines = [trace.label || ''];
    lines.push('Base: ' + fmt.num(trace.base));
    (trace.modifiers || []).forEach(function (m) {
      var value = m.unit === 'percent' ? '+' + fmt.num(m.value) + '%' : fmt.signed(m.value);
      lines.push((m.mod_name || m.source || 'mod') +
        (m.rank !== null && m.rank !== undefined ? ' R' + m.rank : '') + ': ' + value);
    });
    if (trace.intermediate !== null && trace.intermediate !== undefined) {
      lines.push('Intermediate: ' + fmt.num(trace.intermediate));
    }
    lines.push('Final: ' + fmt.num(trace.final));
    (trace.notes || []).forEach(function (n) { lines.push('note: ' + n); });
    return lines.join('\n');
  }

  // ------------------------------------------------------------------ damage + elements
  function renderElements() {
    var card = document.getElementById('plElements');
    var box = document.getElementById('plElemBody');
    var meta = document.getElementById('plDamageMeta');
    if (!card || !box) return;
    P.clear(box);
    var out = P.result();
    var damage = out && out.result && out.result.damage;
    if (!damage) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    var split = damage.per_projectile || {};
    var elements = Object.keys(split);
    // The engine already publishes the per-projectile total: use its number for the bar's
    // denominator rather than re-adding the parts, so one quantity has one source.
    var total = Number(damage.per_projectile_total) || 0;
    if (meta) {
      meta.textContent = '· ' + elements.length + ' type' + (elements.length === 1 ? '' : 's') +
        ' · ' + fmt.num(damage.per_projectile_total) + ' per projectile';
    }
    // the split bar: one segment per damage type, width from the engine's own amounts
    var bar = el('div', { class: 'pl-elem-bar', role: 'img',
      'aria-label': 'Damage split: ' + elements.map(function (k) {
        return (DAMAGE_LABEL[k] || k) + ' ' + fmt.num(split[k]);
      }).join(', ') });
    elements.forEach(function (k) {
      var share = total > 0 ? Math.round(Number(split[k]) / total * 1000) / 10 : 0;
      bar.appendChild(el('i', { 'data-d': k, style: 'width:' + share + '%',
        title: (DAMAGE_LABEL[k] || k) + ' ' + fmt.num(split[k]) + ' (' + share + '%)' }));
    });
    box.appendChild(bar);
    var legend = el('div', { class: 'pl-elem-legend' });
    elements.forEach(function (k) {
      var share = total > 0 ? Math.round(Number(split[k]) / total * 1000) / 10 : 0;
      legend.appendChild(el('span', { class: 'pl-elem-key' }, [
        el('span', { class: 'pl-elem-swatch', 'data-d': k }),
        document.createTextNode((DAMAGE_LABEL[k] || fmt.label(k)) + ' '),
        el('b', { text: fmt.num(split[k]) }),
        document.createTextNode(' ' + share + '%')
      ]));
    });
    box.appendChild(legend);
    // what built each type: the mods, in the engine's own combination order
    var types = (damage.composition && damage.composition.types) || [];
    types.forEach(function (type) {
      var sources = (type.sources || []).map(function (s) {
        return (s.mod_name || s.source) + (s.rank !== null && s.rank !== undefined
          ? ' R' + s.rank : '');
      }).join(' + ');
      var line = el('div', { class: 'pl-dmg-split' });
      line.appendChild(el('span', { 'data-d': type.element, text: (DAMAGE_LABEL[type.element] ||
        fmt.label(type.element)) }));
      line.appendChild(document.createTextNode(' ' + fmt.num(type.amount) +
        (type.combined_from && type.combined_from.length
          ? ' ← ' + type.combined_from.map(function (e) { return DAMAGE_LABEL[e] || e; }).join(' + ')
          : '') +
        (sources ? ' · ' + sources : '')));
      box.appendChild(line);
    });
    ((damage.composition && damage.composition.notes) || []).forEach(function (note) {
      box.appendChild(el('div', { class: 'pl-tr-note', text: note }));
    });
    // the expectations: crit, status and the DPS pair with the engine's assumptions
    var dps = out.result.dps || {};
    var bits = [];
    if (dps.burst && dps.burst.supported) {
      bits.push('burst ' + fmt.num(dps.burst.value) +
        (dps.burst.formula ? ' (' + dps.burst.formula + ')' : ''));
    }
    if (dps.sustained && dps.sustained.supported) {
      bits.push('sustained ' + fmt.num(dps.sustained.value));
    } else if (dps.sustained && dps.sustained.supported === false) {
      bits.push('sustained not modelled for this trigger');
    }
    var crit = out.result.crit || {};
    if (crit.over_100) {
      bits.push('crit over 100% → tier ' + fmt.num(crit.tier));
    }
    var status = out.result.status || {};
    if (status.over_100) {
      bits.push('status over 100% → ' + fmt.num(status.expected_procs_per_shot) + ' procs/shot');
    }
    if (bits.length) {
      box.appendChild(el('div', { class: 'pl-dmg-split', text: bits.join(' · ') }));
    }
    ((dps.assumptions) || []).forEach(function (a) {
      box.appendChild(el('div', { class: 'pl-tr-note', text: 'assumes: ' + a }));
    });
  }

  // ------------------------------------------------------------------ capacity detail
  // The engine's own capacity breakdown: how the total is built and what each slot was
  // charged (matched slots halve, a wrong polarity costs more, an Aura pays out).
  var RULE_TEXT = { matching: 'matched', mismatched: 'wrong polarity',
    mismatched_umbra: 'wrong polarity (Umbra)', vacant: 'vacant', unpolarised_mod: 'no polarity' };

  function renderCapDetail() {
    var body = document.getElementById('plCapBody');
    var meta = document.getElementById('plCapDetailMeta');
    if (!body) return;
    P.clear(body);
    var out = P.result();
    var cap = out && out.capacity && out.capacity.capacity;
    if (!cap) {
      body.appendChild(el('div', { class: 'dim small', text: 'No build to price yet.' }));
      if (meta) meta.textContent = '';
      return;
    }
    // the engine states what is left; the page never subtracts to find out
    var remaining = (out.capacity.drain || {}).remaining;
    if (remaining === undefined || remaining === null) remaining = null;
    var rows = [];
    rows.push(['Rank ' + fmt.num(cap.equipment_rank) + '/' + fmt.num(cap.max_rank),
      'the item\'s own capacity', fmt.num(cap.rank_capacity)]);
    if (cap.orokin_doubled) {
      rows.push(['Catalyst / Reactor', 'doubles the rank capacity',
        fmt.num(cap.doubled_capacity)]);
    }
    if (cap.minimum_from_mastery) {
      rows.push(['Mastery ' + fmt.num(cap.mastery_rank),
        cap.floored_by_mastery ? 'floor applies (higher than the doubled capacity)'
          : 'minimum capacity, not doubled', fmt.num(cap.minimum_from_mastery)]);
    }
    if (cap.aura_bonus) rows.push(['Aura', 'aura capacity bonus', '+' + fmt.num(cap.aura_bonus)]);
    if (cap.stance_bonus) {
      rows.push(['Stance', 'stance capacity bonus', '+' + fmt.num(cap.stance_bonus)]);
    }
    rows.forEach(function (row) {
      body.appendChild(el('div', { class: 'pl-cd-row' }, [
        el('span', { class: 'pl-cd-key', text: row[0] }),
        el('span', { class: 'pl-cd-note', text: row[1] }),
        el('span', { class: 'pl-cd-val', text: row[2] })
      ]));
    });
    body.appendChild(el('div', { class: 'pl-cd-row pl-cd-total' }, [
      el('span', { class: 'pl-cd-key', text: 'Total' }),
      el('span', { class: 'pl-cd-note', text: fmt.num(out.capacity_used) + ' used of '
        + fmt.num(cap.total) }),
      el('span', { class: 'pl-cd-val', text: remaining === null ? '—'
        : fmt.num(remaining) + ' free' })
    ]));
    var slots = ((out.capacity.drain || {}).per_slot) || [];
    var priced = slots.filter(function (s) { return s.mod_name; });
    if (meta) meta.textContent = '· ' + priced.length + ' mod' + (priced.length === 1 ? '' : 's');
    body.appendChild(el('div', { class: 'pl-cd-head',
      text: 'what each slot was charged' }));
    var empty = slots.filter(function (s) { return !s.mod_name && s.kind !== 'exilus'; }).length;
    slots.forEach(function (slot) {
      var label = slot.kind === 'normal' ? 'Slot ' + (slot.index + 1) : P.slotLabel[slot.kind];
      var isAura = slot.kind === 'aura' || slot.kind === 'stance';
      if (!slot.mod_name) {
        if (empty > 4 && slot.kind === 'normal' && slot.index > 1) return;   // keep the list short
        body.appendChild(el('div', { class: 'pl-cd-slot pl-cd-empty' }, [
          el('span', { class: 'pl-cd-slotname', text: label }),
          el('span', { class: 'pl-cd-mod', text: slot.kind === 'exilus' ? 'locked'
            : 'empty - charges nothing' })
        ]));
        return;
      }
      body.appendChild(el('div', { class: 'pl-cd-slot' }, [
        el('span', { class: 'pl-cd-slotname', text: label }),
        el('span', { class: 'pl-cd-mod', text: slot.mod_name }),
        el('span', { class: 'pl-cd-rule',
          'data-r': slot.rule, text: RULE_TEXT[slot.rule] || slot.rule }),
        // charged first, then what it would have cost with no polarity help
        el('span', { class: 'pl-cd-val', text: (isAura ? '+' : '')
          + fmt.num(isAura ? slot.contribution : slot.adjusted_drain) +
          (slot.adjustment || isAura ? ', was ' + fmt.num(slot.raw_drain) : '') })
      ]));
    });
    if (empty > 4) {
      body.appendChild(el('div', { class: 'pl-cd-slot pl-cd-empty' }, [
        el('span', { class: 'pl-cd-slotname', text: '+' + (empty - 2) + ' more' }),
        el('span', { class: 'pl-cd-mod', text: 'empty slots, charging nothing' })
      ]));
    }
    // Forma: which slots this config rewrites against the item's own polarities.
    var changes = P.polarityChanges ? P.polarityChanges() : [];
    body.appendChild(el('div', { class: 'pl-cd-head',
      text: changes.length ? changes.length + ' forma spent on this config'
        : 'no forma - the item\'s own polarities' }));
    changes.forEach(function (c) {
      body.appendChild(el('div', { class: 'pl-cd-slot pl-cd-forma' }, [
        el('span', { class: 'pl-cd-slotname', text: c.label }),
        el('span', { class: 'pl-cd-mod', text: (c.polarity
          ? 'set to ' + (P.polarityShort[c.polarity] || c.polarity)
          : 'polarity cleared') + ' (item: '
          + (c.base ? (P.polarityShort[c.base] || c.base) : 'none') + ')' }),
        el('span', { class: 'pl-cd-rule', 'data-r': 'forma', text: '1 forma' })
      ]));
    });
  }

  // ------------------------------------------------------------------ wiring
  function refresh() {
    renderStats();
    renderTrace();
    renderElements();
    renderCapDetail();
    if (window.wfmIcons && window.wfmIcons.render) {
      window.wfmIcons.render(document.getElementById('plStats'));
    }
  }

  function el(tag, attrs, kids) { return P.el(tag, attrs, kids); }

  P.on('result', refresh);
  P.on('equipment', refresh);
  P.on('library', function () { highlightTraced(); });
  P.on('ready', refresh);
  if (document.readyState !== 'loading') refresh();
})();
