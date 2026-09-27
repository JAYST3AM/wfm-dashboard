/* Self-hosted icon sprite (Phosphor, MIT — see /icons/LICENSE).
 *
 * One file, no CDN, no build step: the sprite is fetched once and injected as <symbol>s, then any
 * element carrying the data-icon attribute grows an inline <svg><use> child. Colours come from the
 * host's currentColor, so icons follow the theme and the orange accent automatically.
 *
 *   <button class="btn" data-icon="arrows-clockwise">Refresh</button>
 *   <span data-icon="check-circle-fill" data-icon-size="14"></span>
 *
 * Names: the regular weight is "<name>", the fill weight is "<name>-fill" (see tools/build_icons.py
 * for the pinned list). Elements added later (app.js re-renders templates) are handled by a
 * MutationObserver, so a fresh view never needs an explicit render() call — but calling
 * window.wfmIcons.render(root) is supported and cheap.
 */
(function () {
  'use strict';
  var SPRITE = '/icons/phosphor.svg';
  var loaded = false;
  var boot = null;

  function iconEl(name, size) {
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'i');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    if (size) {
      svg.style.width = size + 'px';
      svg.style.height = size + 'px';
    }
    var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-' + name);
    svg.appendChild(use);
    return svg;
  }

  function render(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var nodes = scope.querySelectorAll('[data-icon]:not([data-icon-done])');
    for (var i = 0; i < nodes.length; i++) {
      var host = nodes[i];
      var name = host.getAttribute('data-icon');
      if (!name) { continue; }
      host.setAttribute('data-icon-done', '1');
      if (!loaded) { continue; }            /* boot() renders everything once the sprite lands */
      var label = (host.textContent || '').replace(/\s+/g, '');
      var svg = iconEl(name, host.getAttribute('data-icon-size'));
      /* SVGElement.className is a read-only SVGAnimatedString: always set the attribute */
      if (label) { svg.setAttribute('class', 'i i-before'); }
      host.insertBefore(svg, host.firstChild);
    }
  }

  function inject(text) {
    var holder = document.createElement('div');
    holder.setAttribute('class', 'i-sprite');
    holder.setAttribute('aria-hidden', 'true');
    holder.innerHTML = text;
    var first = document.body.firstChild;
    document.body.insertBefore(holder, first);
    loaded = true;
  }

  function start() {
    boot = fetch(SPRITE, { credentials: 'same-origin' })
      .then(function (res) { return res.ok ? res.text() : Promise.reject(new Error('sprite ' + res.status)); })
      .then(inject)
      .catch(function () { /* no sprite: the UI simply has no icons, never a broken image */ })
      .then(function () { render(document); watch(); });
  }

  function watch() {
    if (typeof MutationObserver !== 'function') { return; }
    var queued = false;
    var obs = new MutationObserver(function () {
      if (queued) { return; }
      queued = true;
      setTimeout(function () { queued = false; render(document); }, 0);
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  window.wfmIcons = {
    render: render,
    icon: function (name, size) { return iconEl(name, size).outerHTML; },
    ready: function () { return boot || Promise.resolve(); }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
