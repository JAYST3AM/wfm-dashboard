/* WFM Trader - the shared app shell (one source for every page's chrome).
 *
 * Before this file, index.html / collection.html / cards.html / settings.html / item.html each
 * hand-declared the same header (brand, chips, global search, sound button, theme button + its
 * 60-theme panel, the settings/back link, sync state, refresh, PNG), the same left rail and their
 * own copy of the nav pills - which is exactly how the five pages drifted apart.
 *
 * A page now declares WHAT IT IS and nothing else:
 *   <body data-shell="collection" data-shell-actions="">            <- no optional header actions
 *   <body class="shell-fit" data-shell="index" data-shell-actions="search syncState refresh png">
 * ...plus its own content, its own sub-nav (`.mainnav.subnav`, kept in the page) and its footer.
 * The registry below turns that declaration into the identical chrome on every page.
 *
 * ORDER (why this is a plain script and not a deferred one): it is loaded at the END of the body
 * but BEFORE the page's own scripts, so it runs during parse and the chrome is in the DOM before
 * app.js / collection.js / cards.js / settings.js / item.js touch it (#search, #searchDrop,
 * #refresh, #themeBtn, #themePanel, #themeName, #themeGrid, #syncState, #chips, #mainnav) and
 * before icons.js / sfx.js / theme.js dress it. Nothing here waits for DOMContentLoaded.
 *
 * Everything keeps the exact ids, classes, attributes and DOM position the hand-written markup
 * had: the header is the first child of <body> (index.html carried `body.shell-fit > header`),
 * the rail is the first child of .shellbody (left of <main> / .shellcol).
 */
'use strict';

(function () {
  /* ---- what each page is -----------------------------------------------------------------
     sub    the brand's quiet suffix
     prefix what a hash view link needs from here ('' on the SPA, '/' on the sub-pages)
     active the rail pill that owns the page ('' = none - the SPA follows its own hash)
     hash   true on the SPA: the rail marks the pill the hash router will show
     link   the one contextual link the header carries besides the rail */
  var PAGES = {
    index: {
      sub: 'local', prefix: '', active: '', hash: true,
      link: { href: '/settings.html', label: 'Settings', icon: 'gear-six', id: 'settingsBtn',
              title: 'Trading rules, appearance, updates, accounts' },
    },
    collection: {
      sub: 'collection log', prefix: '/', active: 'collection',
      link: { href: '/', label: 'Dashboard', icon: 'arrow-left' },
    },
    cards: {
      sub: 'mod cards', prefix: '/', active: 'collection',
      link: { href: '/', label: 'Dashboard', icon: 'arrow-left' },
    },
    settings: {
      sub: 'settings', prefix: '/', active: 'more',
      link: { href: '/', label: 'Dashboard', icon: 'arrow-left' },
    },
    item: {
      sub: 'item price', prefix: '/', active: '',
      link: { href: '/#inventory', label: 'Inventory', icon: 'arrow-left' },
    },
  };

  /* the primary rail: the seven destinations, one order, the same icons on every page */
  var RAIL = [
    ['home', '#home', 'house', 'Home'],
    ['inventory', '#inventory', 'package', 'Inventory'],
    ['trade', '#trade', 'tag', 'Trade'],
    ['collection', '/collection.html', 'squares-four', 'Collection'],
    ['mastery', '#mastery', 'trophy', 'Mastery'],
    ['player', '#player', 'user', 'Player'],
    ['more', '#more', 'dots-three-circle', 'More'],
  ];

  /* the same aliases app.js routes with, so the rail pre-marks the pill the router will show */
  var ALIAS = { home: 'home', inventory: 'inventory', trade: 'trade', more: 'more', player: 'player',
    mastery: 'mastery', history: 'trade', trader: 'trade', market: 'more',
    collection: 'collection', cards: 'collection' };

  function hashView() {
    var raw = String(location.hash || '').replace(/^#/, '').split('?')[0].split('/')[0];
    return ALIAS[raw] || 'home';
  }

  function pageKey() {
    var body = document.body || document.documentElement;
    var key = (body.getAttribute && body.getAttribute('data-shell')) || '';
    if (PAGES[key]) return key;
    var file = (location.pathname || '').split('/').pop().replace('.html', '');
    return PAGES[file] ? file : '';
  }

  function actionsFor() {
    var body = document.body || document.documentElement;
    var raw = (body.getAttribute && body.getAttribute('data-shell-actions')) || '';
    var want = {};
    raw.split(/[\s,]+/).forEach(function (k) { if (k) want[k] = true; });
    return want;
  }

  function headerHTML(pg, want) {
    var h = [];
    h.push('<header>');
    h.push('<div class="brand"><span class="logo"><img src="/favicon.png" alt=""></span> WFM Trader ');
    h.push('<span class="sub">' + pg.sub + '</span></div>');
    /* the chips container is shared chrome; whatever script owns the numbers fills it (#chips) */
    h.push('<div class="chips" id="chips"></div>');
    h.push('<div class="actions">');
    if (want.search) {
      h.push('<div class="search"><span class="si" data-icon="magnifying-glass"></span>');
      h.push('<input id="search" type="text" placeholder="Search any item\u2026" autocomplete="off"');
      h.push(' aria-label="Search all items" aria-expanded="false" aria-controls="searchDrop">');
      h.push('<div id="searchDrop" class="sdrop hidden" role="listbox" aria-label="Search results"></div>');
      h.push('</div>');
    }
    /* both speaker weights ship on every page: the CSS swaps them on sfx.js's .muted class */
    h.push('<button id="soundBtn" class="btn icon" title="Click sounds" aria-label="Click sounds"');
    h.push(' aria-pressed="true"><span data-icon="speaker-high"></span>');
    h.push('<span data-icon="speaker-slash"></span></button>');
    h.push('<button id="themeBtn" class="btn icon" title="Change theme" aria-expanded="false"');
    h.push(' aria-controls="themePanel" data-icon="palette">Theme</button>');
    if (pg.link) {
      h.push('<a class="btn"' + (pg.link.id ? ' id="' + pg.link.id + '"' : '') +
        ' href="' + pg.link.href + '"' + (pg.link.title ? ' title="' + pg.link.title + '"' : '') +
        ' data-icon="' + pg.link.icon + '">' + pg.link.label + '</a>');
    }
    if (want.syncState) h.push('<span id="syncState" class="dim small" data-icon="arrows-clockwise"></span>');
    if (want.refresh) h.push('<button id="refresh" class="btn primary" data-icon="arrows-clockwise">Refresh</button>');
    if (want.png) {
      h.push('<button id="btnExportPng" class="btn" title="Save top recommendations as a PNG"');
      h.push(' data-icon="download-simple">PNG</button>');
    }
    h.push('</div>');
    h.push('<div id="themePanel" class="theme-panel hidden">');
    h.push('<div class="tp-head">Choose a theme <span id="themeName" class="dim"></span></div>');
    h.push('<div id="themeGrid" class="tp-grid"></div>');
    h.push('</div>');
    h.push('</header>');
    return h.join('');
  }

  function railHTML(pg) {
    var active = pg.hash ? hashView() : pg.active;
    var h = ['<aside class="side" aria-label="Primary">',
      '<nav class="mainnav sidenav" id="mainnav" aria-label="Primary">'];
    RAIL.forEach(function (p) {
      var v = p[0], href = v === 'collection' ? p[1] : pg.prefix + p[1];
      var on = v === active;
      h.push('<a href="' + href + '" class="navpill' + (on ? ' active' : '') + '" data-v="' + v + '"' +
        ' data-icon="' + p[2] + '"' + (on ? ' aria-current="page"' : '') + '>' + p[3] + '</a>');
    });
    h.push('</nav>');
    h.push('</aside>');
    return h.join('');
  }

  function node(html) {
    var t = document.createElement('template');
    t.innerHTML = html;
    return t.content;
  }

  function mount() {
    var key = pageKey();
    if (!key) {
      if (window.console && console.warn) {
        console.warn('shell.js: no data-shell="<page>" on <body> - the chrome was not rendered');
      }
      return false;
    }
    var pg = PAGES[key], want = actionsFor();
    var body = document.body;
    var host = document.querySelector('.shellbody');
    var head = headerHTML(pg, want);
    var rail = host ? railHTML(pg) : '';
    if (document.querySelector('body > header') || document.getElementById('mainnav')) {
      return false;                     /* already the shell - never render twice */
    }
    body.insertBefore(node(head), body.firstChild);
    if (host) host.insertBefore(node(rail), host.firstChild);
    return true;
  }

  /* one last piece of the chrome: the theme panel's open/close wiring. index (app.js), collection,
     cards (their own wfmInitThemeUI call) and settings (settings.js) each wire it themselves and
     raise window.wfmThemeUI - a page that does not (item.html had an inert button) gets the same
     behaviour from here, so the button means the same thing on every page. */
  function wireThemePanel() {
    if (window.wfmThemeUI || !window.wfmInitThemeUI) return;
    window.wfmInitThemeUI();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wireThemePanel);
  else wireThemePanel();

  /* public: the tests and the QA harness read the registry; pages never call this themselves.
     `mountedAt` records the document's readyState when mount() ran - it stays 'loading' because
     this script executes during parse, which is exactly the ordering the page scripts need. */
  window.wfmShell = { PAGES: PAGES, RAIL: RAIL, ALIAS: ALIAS, mount: mount,
    headerHTML: headerHTML, railHTML: railHTML, hashView: hashView, pageKey: pageKey,
    actions: actionsFor, mountedAt: document.readyState, mounted: mount() };
})();
