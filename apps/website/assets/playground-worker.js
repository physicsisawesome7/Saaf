// Masks or restores whole files off the main thread for /playground.
// One Saaf session per file, so a value gets the same placeholder everywhere.
import { Saaf } from "/assets/saaf/index.js";

const CHUNK = 64 * 1024; // split at line ends near this size

self.onmessage = (e) => {
  try {
    if (e.data.type === "mask") {
      const delim = { ".csv": ",", ".tsv": "\t" }[(e.data.name.match(/\.[^.]+$/)?.[0] ?? "").toLowerCase()];
      if (delim) maskTable(e.data.text, e.data.policy, delim);
      else mask(e.data.text, e.data.policy);
    }
    else if (e.data.type === "restore") restore(e.data.text, e.data.entries);
  } catch (err) {
    self.postMessage({ type: "error", message: String(err?.message ?? err) });
  }
};

function mask(text, policy) {
  const saaf = new Saaf(policy);
  const t0 = performance.now();
  const out = [];
  const counts = {};
  const vault = new Map();
  let pos = 0;
  let lastTick = 0;
  while (pos < text.length) {
    let end = Math.min(text.length, pos + CHUNK);
    if (end < text.length) {
      const nl = text.indexOf("\n", end);
      end = nl === -1 ? text.length : nl + 1;
    }
    const r = saaf.mask(text.slice(pos, end));
    out.push(r.text);
    for (const a of r.applied) {
      counts[a.finding.entity] = (counts[a.finding.entity] ?? 0) + 1;
      if (a.token && !vault.has(a.token)) vault.set(a.token, { token: a.token, entity: a.finding.entity, original: a.finding.text });
    }
    pos = end;
    const now = performance.now();
    if (now - lastTick > 50) {
      self.postMessage({ type: "progress", done: pos / text.length });
      lastTick = now;
    }
  }
  const masked = out.join("");
  self.postMessage({
    type: "masked",
    masked,
    counts,
    vault: [...vault.values()],
    lines: text.split("\n").length,
    ms: performance.now() - t0,
  });
}

// CSV/TSV: mask cell by cell with the column header in front as context, so a
// checksum-valid number under "order_id" stays and one under "aadhaar" goes.
function maskTable(text, policy, delim) {
  const saaf = new Saaf(policy);
  const t0 = performance.now();
  const counts = {};
  const vault = new Map();
  const out = [];
  let headers = null;
  let lines = 0;
  let lastTick = 0;
  const record = (applied) => {
    for (const a of applied) {
      counts[a.finding.entity] = (counts[a.finding.entity] ?? 0) + 1;
      if (a.token && !vault.has(a.token)) vault.set(a.token, { token: a.token, entity: a.finding.entity, original: a.finding.text });
    }
  };
  for (const [row, term, at] of csvRows(text, delim)) {
    lines++;
    const cells = row.map(({ v, q }, j) => {
      let m = v;
      if (v.trim()) {
        const prefix = headers ? `${headers[j] ?? ""}: ` : "";
        const r = saaf.mask(prefix + v);
        if (r.text.startsWith(prefix)) {
          m = r.text.slice(prefix.length);
          record(r.applied);
        } else {
          const r2 = saaf.mask(v);
          m = r2.text;
          record(r2.applied);
        }
      }
      return q || m.includes(delim) || /["\r\n]/.test(m) ? `"${m.replace(/"/g, '""')}"` : m;
    });
    headers ??= row.map(({ v }) => v.trim());
    out.push(cells.join(delim) + term);
    const now = performance.now();
    if (now - lastTick > 50) {
      self.postMessage({ type: "progress", done: at / text.length });
      lastTick = now;
    }
  }
  self.postMessage({
    type: "masked", masked: out.join(""), counts, vault: [...vault.values()], lines, ms: performance.now() - t0, table: true,
  });
}

// Minimal RFC 4180 reader: quoted cells, doubled quotes, CRLF or LF.
function* csvRows(text, delim) {
  const n = text.length;
  let i = 0;
  while (i < n) {
    const row = [];
    let term = "";
    for (;;) {
      let v = "";
      let q = false;
      if (text[i] === '"') {
        q = true;
        i++;
        while (i < n) {
          if (text[i] === '"') {
            if (text[i + 1] === '"') { v += '"'; i += 2; continue; }
            i++;
            break;
          }
          v += text[i++];
        }
      }
      const s = i;
      while (i < n && text[i] !== delim && text[i] !== "\n" && text[i] !== "\r") i++;
      v += text.slice(s, i);
      row.push({ v, q });
      if (i < n && text[i] === delim) { i++; continue; }
      if (text[i] === "\r" && text[i + 1] === "\n") { term = "\r\n"; i += 2; }
      else if (i < n) term = text[i++];
      break;
    }
    yield [row, term, i];
  }
}

function restore(text, entries) {
  const saaf = new Saaf();
  for (const e of entries) {
    if (typeof e?.token === "string" && typeof e?.original === "string") saaf.store(e.token, String(e.entity ?? ""), e.original);
  }
  const r = saaf.restore(text);
  self.postMessage({ type: "restored", text: r.text, restored: r.restored, unknown: r.unknown });
}
