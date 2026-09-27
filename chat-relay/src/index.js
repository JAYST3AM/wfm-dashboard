/* WFM Trader chat relay - one Worker, one SQLite-backed Durable Object, one room.

   Jay (2026-09-27): "add a chat that snaps to the right of the home page. look into getting it so
   other people can chat with their profiles active."

   The dashboard itself is a local server, so there is no place for two people's dashboards to
   meet. This is that place: every dashboard points `chat_relay_url` at one deployment of this
   Worker and they all share the room. Nothing here needs a login - a message carries the profile
   stamp (name, rank, platform) that the sender's dashboard put on it, and the sender's client
   shows exactly that stamp before sending. Honest, not authenticated: it is a mates' room.

   Free tier (Workers Free + SQLite Durable Objects): 100k requests/day, 5M rows read/day,
   100k rows written/day, 5 GB - a room of friends polling every 10s is far inside this.

   Routes (all on the one room, name it with /r/<room>/ if you want more):
     GET  /messages?since=<id>   -> {rows:[{id, ts, who:{name,mr,platform,clan}, text}]}
     POST /messages {text, who}  -> {ok:true, row:{...}}   (429 when posting faster than 1.5s)
   CORS is open (the dashboards run on localhost origins that differ per user).

   Storage: the newest 500 messages, trimmed on write. */
const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, POST, OPTIONS',
  'access-control-allow-headers': 'content-type',
  'access-control-max-age': '86400',
};

const KEEP = 500;
const MAXLEN = 500;
const GAP_MS = 1500;

function jout(obj, code) {
  return new Response(JSON.stringify(obj), {
    status: code || 200,
    headers: Object.assign({ 'content-type': 'application/json', 'cache-control': 'no-store' }, CORS),
  });
}

function stamp(who) {
  const out = {};
  if (!who || typeof who !== 'object') return out;
  for (const [k, cap] of [['name', 24], ['platform', 12], ['clan', 24]]) {
    const v = who[k];
    if (typeof v === 'string' && v.trim()) out[k] = v.replace(/\s+/g, ' ').trim().slice(0, cap);
  }
  const mr = who.mr;
  if (typeof mr === 'number' && Number.isFinite(mr)) out.mr = Math.trunc(mr);
  else if (typeof mr === 'string' && /^\d+$/.test(mr.trim())) out.mr = parseInt(mr, 10);
  return out;
}

export class ChatRoom {
  constructor(state) {
    this.state = state;
    this.sql = state.storage.sql;
    this.seen = new Map();                       /* ip -> last post time, for the flood gap */
    this.sql.exec(`CREATE TABLE IF NOT EXISTS msgs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, who TEXT, text TEXT)`);
  }

  async fetch(req) {
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
    const url = new URL(req.url);

    if (req.method === 'GET') {
      const since = Math.max(0, parseInt(url.searchParams.get('since') || '0', 10) || 0);
      const rows = [...this.sql.exec(
        'SELECT id, ts, who, text FROM msgs WHERE id > ? ORDER BY id ASC LIMIT 200', since)];
      return jout({ rows: rows.map((r) => {
        let who = {};
        try { who = JSON.parse(r.who || '{}'); } catch (e) { who = {}; }
        return { id: r.id, ts: r.ts, who, text: r.text };
      }) });
    }

    if (req.method === 'POST') {
      let body = {};
      try { body = await req.json(); } catch (e) { return jout({ error: 'bad json' }, 400); }
      const text = String(body.text || '').replace(/\s+/g, ' ').trim().slice(0, MAXLEN);
      if (!text) return jout({ error: 'empty message' }, 400);
      const ip = req.headers.get('cf-connecting-ip') || 'local';
      const now = Date.now();
      if (now - (this.seen.get(ip) || 0) < GAP_MS) return jout({ error: 'slow down' }, 429);
      this.seen.set(ip, now);
      if (this.seen.size > 500) this.seen.clear();

      const who = stamp(body.who);
      const ts = Math.floor(now / 1000);
      this.sql.exec('INSERT INTO msgs (ts, who, text) VALUES (?, ?, ?)', ts, JSON.stringify(who), text);
      const id = [...this.sql.exec('SELECT last_insert_rowid() AS id')][0].id;
      /* trim on write so the room never grows without bound */
      this.sql.exec('DELETE FROM msgs WHERE id <= (SELECT MAX(id) FROM msgs) - ?', KEEP);
      return jout({ ok: true, row: { id, ts, who, text } }, 200);
    }

    return jout({ error: 'method not allowed' }, 405);
  }
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const parts = url.pathname.split('/').filter(Boolean);
    const room = (parts[0] === 'r' && parts[1]) ? parts[1].slice(0, 40) : 'tav';
    return env.ROOM.get(env.ROOM.idFromName(room)).fetch(req);
  },
};
