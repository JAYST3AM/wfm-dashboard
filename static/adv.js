/* adv.js — the Advanced (verbose) switch.
 *
 * One knob in Settings ("Advanced") decides whether the dashboard shows its extra explanations:
 * setting hints, footnote sentences and long status notes. Off (the default) leaves labels, values
 * and status chips only. Every page loads this before its own script; the hidden copy is wrapped in
 * .explain, and style.css keys off <html data-adv="on">.
 *
 * Reading the knob: /api/config -> values.advanced (server-side, scripts/config.py). The switch
 * flips it live - the page does not need a reload.
 */
'use strict';
(function () {
  var on = false;
  function apply(v) {
    on = !!v;
    document.documentElement.dataset.adv = on ? 'on' : 'off';
    try {
      window.dispatchEvent(new CustomEvent('wfm-adv', { detail: { on: on } }));
    } catch (e) { /* older engines: no CustomEvent, the dataset is still set */ }
  }
  window.wfmAdv = {
    get on() { return on; },
    set: apply,
  };
  apply(false);                                  /* clean until the config answers */
  fetch('/api/config')
    .then(function (r) { return r.json(); })
    .then(function (j) { apply(j && j.values ? !!j.values.advanced : false); })
    .catch(function () { apply(false); });
})();
