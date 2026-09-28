/* First-run build states (#firstRun) - the setup's real progress, told honestly.

   docs/trading-session-workflow.md §9: the first build takes 20-40 minutes and the app must not look
   dead while it happens. The scripts cannot report a percentage, so this shows the four truthful
   states instead - waiting, running, complete (with how long ago), failed (with the reason the last
   run gave) - and it says which parts of the app are already usable, because every screen renders
   from its own file as soon as that file exists.

   One GET when the first-run card is actually on screen, no timer: the card is only painted while
   there is no data at all (app.js renderFirstRun), and the header's Refresh button re-reads it. */

const BUILD_ICON = { complete: 'check', running: 'lightning', failed: 'alert', waiting: 'hourglass' };

function buildAge(sec) {
  if (sec === null || sec === undefined) return '';
  const m = Math.floor((Number(sec) || 0) / 60);
  if (m < 1) return 'just now';
  if (m < 60) return m + 'm ago';
  const h = Math.floor(m / 60);
  return h < 48 ? h + 'h ago' : Math.floor(h / 24) + 'd ago';
}

function buildRow(row) {
  const state = String(row.state || 'waiting');
  const tail = state === 'complete' ? buildAge(row.age_s) : (row.detail || '');
  return `
    <div class="picks-note buildrow" data-state="${escHtml(state)}">
      <span class="buildmark" data-icon="${escHtml(BUILD_ICON[state] || 'hourglass')}"></span>
      <b>${escHtml(row.label || row.key || '')}</b>
      <span class="dim">${escHtml(state)}</span>
      <span class="dim">${escHtml(tail)}</span>
    </div>`;
}

async function renderBuildStates() {
  const host = document.getElementById('buildList');
  if (!host) return;
  try {
    const j = await fetch('/api/build').then(r => r.json());
    const rows = (j && j.rows) || [];
    host.innerHTML = rows.length ? rows.map(buildRow).join('') : '';
    const done = (j && j.complete) || 0, total = (j && j.total) || rows.length;
    const meta = document.getElementById('buildMeta');
    if (meta) sbits(meta, rows.length ? ['· ' + done + ' of ' + total + ' ready'] : []);
    if (window.iconRepaint) iconRepaint();
  } catch (err) {
    host.innerHTML = '';       /* no answer, no claim: the Refresh hint below still applies */
  }
}
