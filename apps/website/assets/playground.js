// safearly.com/playground: chat with a real model through Saaf, or mask a file.
// Everything runs in this tab. Provider calls go straight from the browser to
// the provider the user picked; keys live only in memory. No analytics.

import { Saaf, tokenPattern, verhoeffCheckDigit, VERSION, defaultSpec } from "/assets/saaf/index.js";

document.documentElement.classList.remove("no-js");
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SPEC = defaultSpec();
const ISSUES = "https://github.com/physicsisawesome7/Saaf/issues/new?template=detection.yml";

// --- header menu (same behaviour as the home page) ---------------------------
const top = document.querySelector(".top");
const onScroll = () => top?.classList.toggle("scrolled", window.scrollY > 8);
window.addEventListener("scroll", onScroll, { passive: true });
$("menu")?.addEventListener("click", () => {
  const open = $("links").classList.toggle("open");
  $("menu").setAttribute("aria-expanded", String(open));
});

// --- providers -----------------------------------------------------------------
const PROVIDERS = {
  sim: { name: "Simulated model" },
  openai: {
    name: "OpenAI", base: "https://api.openai.com/v1", kind: "openai", key: true,
    models: ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
    hint: "Your browser sends the masked text straight to api.openai.com with this key.",
  },
  anthropic: {
    name: "Anthropic", kind: "anthropic", key: true,
    models: ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
    hint: "Your browser sends the masked text straight to api.anthropic.com with this key.",
  },
  gemini: {
    name: "Google Gemini", kind: "gemini", key: true,
    models: ["gemini-2.5-flash", "gemini-2.5-pro"],
    hint: "Your browser sends the masked text straight to generativelanguage.googleapis.com with this key.",
  },
  openrouter: {
    name: "OpenRouter", base: "https://openrouter.ai/api/v1", kind: "openai", key: true,
    models: ["openai/gpt-4.1-mini", "anthropic/claude-haiku-5-5", "meta-llama/llama-3.3-70b-instruct", "sarvamai/sarvam-m"],
    hint: "One key, hundreds of models, including Indian ones. Requests go straight to openrouter.ai.",
  },
  ollama: {
    name: "Ollama", kind: "openai", url: "http://localhost:11434", suffix: "/v1", key: false,
    models: ["llama3.2", "qwen2.5", "gemma3"],
    hint: 'Runs fully offline. Start Ollama with <code>OLLAMA_ORIGINS=https://safearly.com</code> so this page may call it. Your browser may ask to allow access to devices on your network.',
  },
  gateway: {
    name: "Saaf gateway", kind: "openai", url: "http://localhost:8787", suffix: "/v1", key: "optional", gateway: true,
    models: ["gpt-4.1-mini", "gpt-4o-mini"],
    hint: 'The production setup: your raw text goes to <em>your</em> gateway, which masks it, calls the provider and restores the reply. Start it with <code>SAAF_CORS_ORIGINS=https://safearly.com</code> (see <a href="https://github.com/physicsisawesome7/Saaf/blob/main/docs/try-it.md">try it</a>). The key is passed through to the provider.',
  },
};

const SYSTEM_PROMPT =
  "Some values in the user's messages were replaced with placeholders such as [AADHAAR_1] or [PHONE_IN_2] " +
  "to protect privacy. Treat each placeholder as the real value it stands for. When you refer to one, copy the " +
  "placeholder exactly, including the square brackets. Never guess or invent the hidden value. Be concise.";

// --- settings (remembered; keys are not) -----------------------------------------
const DEFAULTS = { provider: "sim", models: {}, urls: {}, mode: "enforce", threshold: 0.5, rules: {} };
let settings = { ...DEFAULTS };
try {
  settings = { ...DEFAULTS, ...JSON.parse(localStorage.getItem("saaf-playground") || "{}") };
} catch { /* private mode: defaults */ }
const keys = {}; // provider -> key, memory only
const save = () => {
  try { localStorage.setItem("saaf-playground", JSON.stringify(settings)); } catch { /* ignore */ }
};

function policy() {
  const entities = {};
  for (const [id, action] of Object.entries(settings.rules)) if (action !== "mask") entities[id] = { action };
  return { mode: settings.mode, threshold: Number(settings.threshold), entities };
}
const actionFor = (id) => settings.rules[id] ?? "mask";
const labelOf = (id) => SPEC.byId.get(id)?.label ?? id;

// --- session state ---------------------------------------------------------------
let saaf;
let turns = [];      // {role:"user", original, masked, applied, blocked, shadow, ms} | {role:"assistant", raw, shown, ...}
let evidence = [];
let busy = false;
let view = "you";

function newSession(note) {
  saaf = new Saaf(policy());
  turns = [];
  evidence = [];
  $("thread").innerHTML = "";
  $("thread").append(emptyState(note));
  $("why-card").hidden = true;
  renderStats();
  renderPreview();
}
function emptyState(note) {
  const d = document.createElement("div");
  d.className = "empty";
  d.innerHTML = note
    ? `<p>${esc(note)}</p>`
    : "<p><strong>Try a sample</strong> or type your own message. Use made-up values, not real ones.</p>";
  return d;
}

// --- settings UI -------------------------------------------------------------------
function renderProvider() {
  const p = PROVIDERS[settings.provider];
  $("provider").value = settings.provider;
  const sim = settings.provider === "sim";
  $("model-fields").hidden = sim;
  $("sim-hint").hidden = !sim;
  if (sim) return;
  $("model").value = settings.models[settings.provider] ?? p.models[0];
  $("model-list").innerHTML = p.models.map((m) => `<option value="${esc(m)}">`).join("");
  $("key-row").hidden = !p.key;
  $("api-key").value = keys[settings.provider] ?? "";
  $("api-key").placeholder = p.key === "optional" ? "Optional: passed to the upstream provider" : "Paste a key (kept in memory only)";
  $("url-row").hidden = !p.url;
  $("base-url").value = settings.urls[settings.provider] ?? p.url ?? "";
  $("provider-hint").innerHTML = p.hint;
}
$("provider").addEventListener("change", (e) => {
  settings.provider = e.target.value;
  save();
  renderProvider();
});
$("model").addEventListener("change", (e) => {
  settings.models[settings.provider] = e.target.value.trim();
  save();
});
$("base-url").addEventListener("change", (e) => {
  const v = e.target.value.trim().replace(/\/+$/, "");
  if (!/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(v)) {
    e.target.value = settings.urls[settings.provider] ?? PROVIDERS[settings.provider].url;
    alert("For safety this page only talks to services on this computer: http://localhost:<port>.");
    return;
  }
  settings.urls[settings.provider] = v;
  save();
});
$("api-key").addEventListener("input", (e) => (keys[settings.provider] = e.target.value.trim()));
$("key-toggle").addEventListener("click", () => {
  const show = $("api-key").type === "password";
  $("api-key").type = show ? "text" : "password";
  $("key-toggle").setAttribute("aria-pressed", String(show));
});

function renderPolicy() {
  document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === settings.mode)));
  $("mode-hint").textContent =
    settings.mode === "shadow"
      ? "Shadow: nothing is changed. Saaf only reports what it would have masked. Good for a first week in production."
      : "Enforce: values are replaced with placeholders before sending.";
  $("threshold").value = settings.threshold;
  $("thr-out").textContent = Number(settings.threshold).toFixed(2);
  const changed = Object.values(settings.rules).filter((a) => a !== "mask").length;
  $("ent-summary").textContent = `${SPEC.entities.length} types${changed ? `, ${changed} changed` : ""}`;
}
function buildRules() {
  $("ent-rules").innerHTML = SPEC.entities
    .map(
      (e) => `<label class="ent-rule"><span>${esc(e.label)}<span class="sev">${esc(e.id)}</span></span>
      <select data-ent="${esc(e.id)}">${["mask", "block", "warn", "allow"]
        .map((a) => `<option value="${a}"${actionFor(e.id) === a ? " selected" : ""}>${a[0].toUpperCase() + a.slice(1)}</option>`)
        .join("")}</select></label>`,
    )
    .join("");
}
function policyChanged() {
  save();
  renderPolicy();
  const had = turns.length > 0;
  newSession(had ? "Policy changed, so a new session started: placeholders from the old one would not match." : undefined);
}
document.querySelectorAll("[data-mode]").forEach((b) =>
  b.addEventListener("click", () => {
    if (settings.mode === b.dataset.mode) return;
    settings.mode = b.dataset.mode;
    policyChanged();
  }),
);
$("threshold").addEventListener("input", (e) => ($("thr-out").textContent = Number(e.target.value).toFixed(2)));
$("threshold").addEventListener("change", (e) => {
  settings.threshold = Number(e.target.value);
  policyChanged();
});
$("ent-rules").addEventListener("change", (e) => {
  const id = e.target.dataset.ent;
  if (!id) return;
  if (e.target.value === "mask") delete settings.rules[id];
  else settings.rules[id] = e.target.value;
  policyChanged();
});
$("reset").addEventListener("click", () => newSession("New session started. Earlier placeholders are forgotten."));

// --- tabs ----------------------------------------------------------------------------
const tabs = [$("tab-chat"), $("tab-files")];
function selectTab(t) {
  for (const x of tabs) {
    const on = x === t;
    x.setAttribute("aria-selected", String(on));
    x.tabIndex = on ? 0 : -1;
    $(x.getAttribute("aria-controls")).hidden = !on;
  }
  $("model-card").hidden = t.id === "tab-files";
  $("session-card").hidden = t.id === "tab-files";
}
tabs.forEach((t, i) => {
  t.addEventListener("click", () => selectTab(t));
  t.addEventListener("keydown", (e) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    const n = tabs[(i + d + tabs.length) % tabs.length];
    selectTab(n);
    n.focus();
  });
});

// --- samples (all values are synthetic and checksum-valid) ---------------------------------
const SAMPLES = {
  kyc:
    "Please check this customer's KYC and tell me what is missing.\n" +
    "Name: Smt. Lakshmi Iyer\nAadhaar: 2345 6789 0124\nPAN: ABCPE1234F\nGSTIN: 27ABCPE1234F1ZB\n" +
    "Mobile: +91 98765 43210\nUPI: lakshmi.iyer@okaxis",
  hinglish:
    "bhai mera adhaar २३४५ ६७८९ ०१२४ hai aur pan abcpe1234f. phonepe pe 9876543210@ybl bhej do, " +
    "aur whatsapp karo 987 654 3210. Ek short message likh do confirm karne ke liye.",
  loan:
    "Hi, draft a short loan sanction email for Mr. Arjun Mehta (PAN ABCPE1234F). Salary is credited to " +
    "a/c no 50100234567891, IFSC HDFC0001234. Reach him on +91 98765 43210 or arjun.mehta@example.in.",
  ocr: "Text from a scanned card, please extract the fields:\nAADHAAR: 2345 67B9 O124\nPAN card: ABCPE12B4F\nDOB: 14/08/1990",
  indic:
    "मेरा नाम राहुल वर्मा है, आधार २३४५ ६७८९ ०१२४ और मोबाइल ९८७६५४३२१०।\n" +
    "என் பெயர் கவிதா, தொலைபேசி 98765 43210. Reply in English with a one-line summary.",
  spelled:
    "Caller said: mera aadhaar hai do teen char paanch chhe saat aath nau shunya ek do char. " +
    "Callback number nine eight seven six five four three two one zero. Summarise the call.",
  negatives:
    "Order ID 234567890124 shipped via AWB 987654321012. Invoice INV-2024-000123, NEFT ref 345678901234, " +
    "qty 12, txn id 9876543210. Which of these numbers should I share with the courier?",
};
document.querySelectorAll("[data-sample]").forEach((b) =>
  b.addEventListener("click", () => {
    $("msg").value = SAMPLES[b.dataset.sample];
    renderPreview();
    $("msg").focus();
  }),
);

// --- rendering helpers -------------------------------------------------------------------
function markFindings(text, applied) {
  let html = "";
  let pos = 0;
  for (const a of [...applied].sort((x, y) => x.finding.start - y.finding.start)) {
    const f = a.finding;
    if (f.start < pos) continue;
    html += esc(text.slice(pos, f.start));
    html += `<mark title="${esc(labelOf(f.entity))} · score ${f.score.toFixed(2)} · ${a.action}">${esc(text.slice(f.start, f.end))}<small>${esc(f.entity)}</small></mark>`;
    pos = f.end;
  }
  return html + esc(text.slice(pos));
}
function highlight(text, rx, cls) {
  if (!rx) return esc(text);
  let html = "";
  let pos = 0;
  for (const m of text.matchAll(rx)) {
    if (!m[0]) continue;
    html += esc(text.slice(pos, m.index)) + `<span class="${cls}">${esc(m[0])}</span>`;
    pos = m.index + m[0].length;
  }
  return html + esc(text.slice(pos));
}
function tokenRx() {
  const toks = saaf.tokens();
  return toks.length ? new RegExp(toks.map((t) => `(?:${tokenPattern(t)})`).join("|"), "gi") : null;
}
function valueRx() {
  const vals = [...new Set(turns.flatMap((t) => (t.applied ?? []).filter((a) => a.token).map((a) => a.finding.text)))];
  if (!vals.length) return null;
  return new RegExp(vals.sort((a, b) => b.length - a.length).map((v) => v.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&")).join("|"), "g");
}

function bubble(turn) {
  const el = document.createElement("div");
  el.className = `bubble ${turn.role === "user" ? "user" : "bot"}`;
  turn.el = el;
  paint(turn);
  const empty = $("empty") ?? $("thread").querySelector(".empty");
  empty?.remove();
  $("thread").append(el);
  $("thread").scrollTop = $("thread").scrollHeight;
  return el;
}

function paint(turn) {
  const el = turn.el;
  if (!el) return;
  const model = view === "model";
  let who;
  let body;
  const meta = [];
  if (turn.role === "user") {
    who = model ? "Model received" : "You";
    if (turn.blocked) {
      el.classList.add("blocked");
      body = markFindings(turn.original, turn.applied);
      meta.push(`Not sent: policy blocks ${[...new Set(turn.applied.filter((a) => a.action === "block").map((a) => a.finding.entity))].join(", ")}. Nothing left this tab.`);
    } else if (model) {
      body = turn.gateway ? markFindings(turn.original, turn.applied) : highlight(turn.masked, tokenRx(), "tk");
      if (turn.gateway) meta.push("Raw text went to your gateway; it masks before calling the provider");
    } else {
      body = markFindings(turn.original, turn.applied);
    }
    const masked = turn.applied.filter((a) => a.token).length;
    if (turn.shadow && turn.applied.length) meta.push(`Shadow: ${turn.applied.length} would be masked, sent unchanged`);
    else if (masked) meta.push(`${masked} masked`);
    const warned = turn.applied.filter((a) => a.action === "warn").length;
    if (warned) meta.push(`${warned} warned, sent as is`);
    meta.push(`scan ${turn.ms.toFixed(1)} ms`);
  } else {
    who = model ? `${turn.provider} wrote` : turn.provider;
    if (turn.error) {
      el.classList.add("err");
      body = esc(turn.error);
    } else if (model) {
      body = turn.gateway ? esc("(The raw reply stays on your gateway, which restores it before it reaches this tab.)") : highlight(turn.raw, tokenRx(), "tk");
    } else {
      body = highlight(turn.shown, valueRx(), "rv");
    }
    if (turn.done && !turn.error) {
      if (turn.restored) meta.push(`${turn.restored} restored`);
      if (turn.unknown?.length) meta.push(`${turn.unknown.length} unknown placeholder(s) left as is`);
      if (turn.gatewayEntities) meta.push(`gateway masked: ${turn.gatewayEntities}`);
      if (turn.ms) meta.push(`${(turn.ms / 1000).toFixed(1)} s`);
    }
  }
  el.innerHTML =
    `<div class="who">${esc(who)}</div><div class="${turn.role === "assistant" && !turn.done ? "cursor" : ""}">${body}</div>` +
    (meta.length ? `<div class="meta">${meta.map((m) => `<span>${esc(m)}</span>`).join("")}</div>` : "");
}
const repaint = () => turns.forEach(paint);

document.querySelectorAll("[data-view]").forEach((b) =>
  b.addEventListener("click", () => {
    view = b.dataset.view;
    document.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("thread").classList.toggle("view-model", view === "model");
    $("thread-note").textContent =
      view === "model" ? "This is everything the model received and wrote. Real values never reached it." : "Switch to see exactly what the model received and wrote.";
    repaint();
  }),
);

function renderStats() {
  const users = turns.filter((t) => t.role === "user");
  const sent = users.filter((t) => !t.blocked);
  const masked = sent.reduce((n, t) => n + t.applied.filter((a) => a.token).length, 0);
  const stats = [
    ["Messages sent", sent.length],
    ["Values masked", masked],
    ["Distinct placeholders", saaf ? saaf.tokens().length : 0],
    ["Blocked", users.length - sent.length],
    ["Engine", `saaf-js ${VERSION}`],
  ];
  $("session-stats").innerHTML = stats.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

// --- live preview while typing ---------------------------------------------------------------
let previewTimer = 0;
function renderPreview() {
  const text = $("msg").value;
  if (!text.trim()) {
    $("preview").innerHTML = "";
    $("preview-note").textContent = "Nothing detected yet.";
    return;
  }
  const t0 = performance.now();
  const found = saaf.scan(text);
  const ms = performance.now() - t0;
  const applied = found.map((f) => ({ finding: f, action: actionFor(f.entity) }));
  $("preview").innerHTML = found.length ? markFindings(text, applied) : "";
  const counts = {};
  for (const f of found) counts[f.entity] = (counts[f.entity] ?? 0) + 1;
  const list = Object.entries(counts).map(([k, n]) => `${k}${n > 1 ? ` ×${n}` : ""}`).join(", ");
  const verb = settings.mode === "shadow" ? "would be masked (shadow mode)" : "will be masked";
  $("preview-note").textContent = found.length ? `${found.length} ${verb}: ${list} · ${ms.toFixed(1)} ms` : `Nothing to mask · ${ms.toFixed(1)} ms`;
}
$("msg").addEventListener("input", () => {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(renderPreview, 60);
});
$("msg").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("composer").requestSubmit();
});

// --- why it was caught -------------------------------------------------------------------------
function showWhy(turn) {
  if (!turn.applied.length) {
    $("why-card").hidden = true;
    return;
  }
  const rows = turn.applied.map((a) => {
    const f = a.finding;
    const e = SPEC.byId.get(f.entity);
    const ev = [];
    if (f.validated && e?.validatorName) ev.push(`<span class="ok">✓</span> ${esc(e.validatorName)} check passes`);
    if (f.contextHit) ev.push("label nearby");
    if (f.ocrRepaired) ev.push("OCR-repaired, then checked");
    if (f.detector === "spelled") ev.push("spelled-out digits");
    if (!ev.length) ev.push("pattern match");
    return `<tr><td>${esc(labelOf(f.entity))}<br><code class="muted">${esc(f.entity)}</code></td><td><code>${esc(peek(f.text))}</code></td>
      <td>${f.score.toFixed(2)}</td><td>${ev.join("<br>")}</td><td>${esc(a.token ?? a.action)}</td></tr>`;
  });
  $("why").innerHTML = `<thead><tr><th>Type</th><th>Value</th><th>Score</th><th>Evidence</th><th>Sent as</th></tr></thead><tbody>${rows.join("")}</tbody>`;
  $("why-card").hidden = false;
}
const peek = (v) => (v.length <= 6 ? "•".repeat(v.length) : v.slice(0, 2) + "•".repeat(Math.max(3, v.length - 4)) + v.slice(-2));

$("report").addEventListener("click", async () => {
  const last = [...turns].reverse().find((t) => t.role === "user");
  const lines = [
    "Masked text (placeholders hide what Saaf caught; replace anything it missed with fake values before posting):",
    "",
    "```",
    last?.masked ?? "",
    "```",
    "",
    "Findings: " + (last?.applied ?? []).map((a) => `${a.finding.entity} ${a.finding.score.toFixed(2)} ${a.finding.detector}`).join("; "),
    `Engine: saaf-js ${VERSION}, spec ${SPEC.version}`,
  ];
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    alert("A report (masked text, types and scores only) was copied. Paste it into the issue that opens next, and use fake values only.");
  } catch { /* clipboard blocked: still open the form */ }
  window.open(ISSUES, "_blank", "noopener");
});

// --- sending ---------------------------------------------------------------------------------------
$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (busy) return;
  const text = $("msg").value.trim();
  if (!text) return;
  const p = PROVIDERS[settings.provider];
  if (p.key === true && !keys[settings.provider]) {
    $("api-key").focus();
    $("provider-hint").innerHTML = `<strong>Add your ${esc(p.name)} key first,</strong> or pick the simulated model. ` + p.hint;
    return;
  }
  const t0 = performance.now();
  const r = saaf.mask(text);
  const ms = performance.now() - t0;
  const userTurn = {
    role: "user", original: text, masked: r.text, applied: r.applied, blocked: r.blocked, shadow: r.shadow, ms,
    gateway: !!p.gateway,
  };
  turns.push(userTurn);
  bubble(userTurn);
  showWhy(userTurn);
  $("msg").value = "";
  renderPreview();
  evidence.push({
    at: new Date().toISOString(), direction: "outbound", destination: p.gateway ? "local saaf gateway" : p.name,
    mode: r.shadow ? "shadow" : "enforce", blocked: r.blocked, entity_counts: r.entityCounts, chars: text.length,
    sent_text: r.blocked ? null : p.gateway ? "(masked by the gateway)" : r.text,
  });
  renderStats();
  if (r.blocked) return;

  const bot = { role: "assistant", provider: p.name, raw: "", shown: "", done: false, gateway: !!p.gateway };
  turns.push(bot);
  bubble(bot);
  busy = true;
  $("send").disabled = true;
  const started = performance.now();
  const restorer = saaf.streamRestorer();
  try {
    const history = buildHistory(p);
    for await (const chunk of stream(p, history, bot)) {
      if (!chunk) continue;
      bot.raw += chunk;
      bot.shown += p.gateway ? chunk : restorer.feed(chunk);
      paint(bot);
      $("thread").scrollTop = $("thread").scrollHeight;
    }
    if (!p.gateway) bot.shown += restorer.flush();
    bot.restored = restorer.restored;
    bot.unknown = restorer.unknown;
  } catch (err) {
    bot.error = explain(err, p);
  } finally {
    bot.done = true;
    bot.ms = performance.now() - started;
    busy = false;
    $("send").disabled = false;
    paint(bot);
    evidence.push({
      at: new Date().toISOString(), direction: "inbound", source: p.name, placeholders_restored: bot.restored ?? 0,
      unknown_placeholders: bot.unknown?.length ?? 0, error: bot.error ? true : undefined,
    });
    renderStats();
  }
});

function buildHistory(p) {
  const msgs = [];
  for (const t of turns) {
    if (t.role === "user" && !t.blocked) msgs.push({ role: "user", content: p.gateway ? t.original : t.masked });
    if (t.role === "assistant" && t.done && !t.error) msgs.push({ role: "assistant", content: p.gateway ? t.shown : t.raw });
  }
  return msgs;
}

function explain(err, p) {
  if (err?.name === "TypeError" || /fetch|network/i.test(String(err?.message))) {
    if (settings.provider === "ollama") return "Could not reach Ollama. Is it running, and was it started with OLLAMA_ORIGINS=https://safearly.com? Your browser may also need permission to reach local devices.";
    if (settings.provider === "gateway") return "Could not reach the Saaf gateway. Is it running on that address, started with SAAF_CORS_ORIGINS=https://safearly.com?";
    return `Could not reach ${p.name}. Check your connection, or try another provider.`;
  }
  return String(err?.message ?? err);
}

// --- provider streaming ---------------------------------------------------------------------------
async function* sse(resp) {
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).replace(/\r$/, "");
      buf = buf.slice(i + 1);
      if (line.startsWith("data:")) {
        const d = line.slice(5).trim();
        if (d && d !== "[DONE]") yield d;
      }
    }
  }
}

async function failure(resp, name) {
  let detail = "";
  try {
    const body = await resp.text();
    try {
      const j = JSON.parse(body);
      detail = j.error?.message ?? j.error?.type ?? j.message ?? body;
      if (j.error?.type === "saaf_blocked") detail = `Blocked by the gateway's policy: ${(j.error.entities ?? []).join(", ")}`;
    } catch {
      detail = body;
    }
  } catch { /* ignore */ }
  const hint = resp.status === 401 || resp.status === 403 ? " Check the API key." : resp.status === 404 ? " Check the model name." : "";
  return new Error(`${name} returned ${resp.status}. ${String(detail).slice(0, 300)}${hint}`);
}

async function* stream(p, history, bot) {
  if (settings.provider === "sim") return yield* simulate(history);
  const model = ($("model").value || p.models[0]).trim();
  const key = keys[settings.provider];
  if (p.kind === "openai") {
    const base = p.base ?? (settings.urls[settings.provider] ?? p.url) + p.suffix;
    const headers = { "content-type": "application/json" };
    if (key) headers.authorization = `Bearer ${key}`;
    const messages = p.gateway ? history : [{ role: "system", content: SYSTEM_PROMPT }, ...history];
    const resp = await fetch(`${base}/chat/completions`, {
      method: "POST", headers, body: JSON.stringify({ model, messages, stream: true }),
    });
    if (!resp.ok) throw await failure(resp, p.name);
    bot.gatewayEntities = resp.headers.get("x-saaf-entities") || (p.gateway ? "none" : undefined);
    for await (const d of sse(resp)) yield JSON.parse(d).choices?.[0]?.delta?.content ?? "";
  } else if (p.kind === "anthropic") {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true",
      },
      body: JSON.stringify({ model, max_tokens: 1024, system: SYSTEM_PROMPT, messages: history, stream: true }),
    });
    if (!resp.ok) throw await failure(resp, p.name);
    for await (const d of sse(resp)) {
      const j = JSON.parse(d);
      if (j.type === "error") throw new Error(j.error?.message ?? "Anthropic stream error");
      if (j.type === "content_block_delta") yield j.delta?.text ?? "";
    }
  } else if (p.kind === "gemini") {
    const resp = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:streamGenerateContent?alt=sse`,
      {
        method: "POST",
        headers: { "content-type": "application/json", "x-goog-api-key": key },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
          contents: history.map((m) => ({ role: m.role === "assistant" ? "model" : "user", parts: [{ text: m.content }] })),
        }),
      },
    );
    if (!resp.ok) throw await failure(resp, p.name);
    for await (const d of sse(resp)) yield (JSON.parse(d).candidates?.[0]?.content?.parts ?? []).map((x) => x.text ?? "").join("");
  }
}

// A stand-in model for trying the round trip without a key. It writes the
// placeholders back the messy ways real models do, and streams in small
// random chunks so placeholders get split across chunks.
const MANGLE = [
  (t) => t,
  (t) => t.toLowerCase(),
  (t) => "**" + t.replace("[", "\\[").replace("]", "\\]") + "**",
  (t) => t.slice(1, -1),
  (t) => t + "'s",
  (t) => t.slice(1, -1).replace(/_/g, " "),
];
async function* simulate(history) {
  const last = history.at(-1)?.content ?? "";
  const toks = [...new Set(last.match(/\[[A-Z][A-Z0-9_]*_\d+\]/g) ?? [])];
  let reply;
  if (!toks.length) {
    reply = "Nothing in your message needed masking, so I received it exactly as you typed it.";
  } else {
    const lines = toks.map((t, i) => `- ${labelOf(t.slice(1, t.lastIndexOf("_")))}: ${MANGLE[i % MANGLE.length](t)}`);
    reply =
      "(Simulated reply.) I only ever see placeholders, never your real values. Here is what I received:\n" +
      lines.join("\n") +
      `\n\nI've noted ${MANGLE[1](toks[0])} on the file. Everything above was written with placeholders; ` +
      "Saaf put the real values back in your browser as this streamed in.";
  }
  for (let i = 0; i < reply.length; ) {
    const n = 1 + Math.floor(Math.random() * 6);
    yield reply.slice(i, i + n);
    i += n;
    await sleep(12 + Math.random() * 28);
  }
}

// --- evidence log ----------------------------------------------------------------------------------
function download(name, text, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("evidence").addEventListener("click", () => {
  const log = {
    format: "saaf-playground-evidence/1",
    generated_at: new Date().toISOString(),
    engine: `saaf-js ${VERSION}`,
    spec_version: SPEC.version,
    policy: policy(),
    note: "Records what left this browser tab. Real values are never included.",
    events: evidence,
  };
  download(`saaf-evidence-${Date.now()}.json`, JSON.stringify(log, null, 2));
});

// --- files -----------------------------------------------------------------------------------------
let worker = null;
let fileOut = null;
const MAX_BYTES = 25 * 1024 * 1024;
function getWorker() {
  worker ??= new Worker("/assets/playground-worker.js", { type: "module" });
  return worker;
}
function runWorker(msg, onProgress) {
  return new Promise((resolve, reject) => {
    const w = getWorker();
    w.onmessage = (e) => {
      if (e.data.type === "progress") onProgress?.(e.data.done);
      else if (e.data.type === "error") reject(new Error(e.data.message));
      else resolve(e.data);
    };
    w.onerror = (e) => reject(new Error(e.message || "worker failed"));
    w.postMessage(msg);
  });
}

async function maskFile(name, text) {
  $("progress").hidden = false;
  $("progress-bar").style.width = "0%";
  $("file-result").hidden = true;
  $("drop-note").textContent = `Masking ${name}…`;
  try {
    const r = await runWorker({ type: "mask", name, text, policy: policy() }, (d) => ($("progress-bar").style.width = `${(d * 100).toFixed(0)}%`));
    fileOut = { name, ...r };
    const kb = new Blob([text]).size / 1024;
    const total = Object.values(r.counts).reduce((a, b) => a + b, 0);
    $("file-stats").innerHTML = [
      ["File", name],
      ["Size", kb < 1024 ? `${kb.toFixed(1)} KB` : `${(kb / 1024).toFixed(2)} MB`],
      ["Lines", r.lines.toLocaleString()],
      [settings.mode === "shadow" ? "Would mask" : "Values masked", total.toLocaleString()],
      ["Distinct values", r.vault.length.toLocaleString()],
      ["Time", `${r.ms.toFixed(0)} ms (${((kb / Math.max(r.ms, 0.1)) * 1000 / 1024).toFixed(1)} MB/s)`],
      ["Mode", r.table ? "Columns: header used as context" : "Plain text"],
    ]
      .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
      .join("");
    $("file-chips").innerHTML = Object.keys(r.counts).length
      ? Object.entries(r.counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<span class="chip">${esc(k)} × ${n.toLocaleString()}</span>`).join("")
      : '<span class="chip">Nothing to mask</span>';
    const lines = r.masked.split("\n");
    $("file-preview").innerHTML = highlight(lines.slice(0, 200).join("\n"), /\[[A-Z][A-Z0-9_]*_\d+\]/g, "tk");
    $("preview-lines").textContent = lines.length > 200 ? `(first 200 of ${lines.length.toLocaleString()} lines)` : "";
    $("dl-vault").disabled = !r.vault.length;
    $("file-result").hidden = false;
    $("drop-note").innerHTML = 'Done. <button type="button" class="link-btn" id="file-sample">Try the sample CSV</button>';
  } catch (err) {
    $("drop-note").textContent = `Could not mask the file: ${err.message}`;
  } finally {
    $("progress").hidden = true;
  }
}
async function readFile(f) {
  if (f.size > MAX_BYTES) {
    $("drop-note").textContent = `That file is ${(f.size / 1048576).toFixed(1)} MB. The playground takes up to 25 MB; use the Python library or gateway for bigger jobs.`;
    return;
  }
  await maskFile(f.name, await f.text());
}
$("file").addEventListener("change", (e) => e.target.files[0] && readFile(e.target.files[0]));
const drop = $("drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (f) readFile(f);
});
drop.addEventListener("click", (e) => {
  if (e.target.id === "file-sample") {
    e.preventDefault();
    maskFile("sample-customers.csv", sampleCsv(2000));
  }
});

$("dl-masked").addEventListener("click", () => fileOut && download(fileOut.name.replace(/(\.[^.]+)?$/, ".masked$1"), fileOut.masked, "text/plain"));
$("dl-vault").addEventListener("click", () => {
  if (!fileOut) return;
  const vault = { format: "saaf-vault/1", created_at: new Date().toISOString(), source: fileOut.name, entries: fileOut.vault };
  download(fileOut.name.replace(/(\.[^.]+)?$/, ".vault.json"), JSON.stringify(vault, null, 2));
});

const rState = { file: null, vault: null };
const rCheck = () => ($("r-go").disabled = !(rState.file && rState.vault));
$("r-file").addEventListener("change", (e) => { rState.file = e.target.files[0] ?? null; rCheck(); });
$("r-vault").addEventListener("change", (e) => { rState.vault = e.target.files[0] ?? null; rCheck(); });
$("r-go").addEventListener("click", async () => {
  try {
    const vault = JSON.parse(await rState.vault.text());
    if (vault.format !== "saaf-vault/1" || !Array.isArray(vault.entries)) throw new Error("that is not a Saaf vault file");
    const r = await runWorker({ type: "restore", text: await rState.file.text(), entries: vault.entries });
    $("r-note").textContent = `Restored ${r.restored.toLocaleString()} placeholder(s)` + (r.unknown.length ? `; ${r.unknown.length} not in this vault were left as is.` : ".");
    const name = rState.file.name.replace(".masked", "").replace(/(\.[^.]+)?$/, ".restored$1");
    download(name, r.text, "text/plain");
  } catch (err) {
    $("r-note").textContent = `Could not restore: ${err.message}`;
  }
});

// Synthetic customer rows: checksum-valid Aadhaar numbers, PANs and GSTINs
// built from random digits, plus look-alike order IDs that must stay.
function sampleCsv(n) {
  const rnd = (k) => Math.floor(Math.random() * k);
  const digits = (k) => Array.from({ length: k }, () => rnd(10)).join("");
  const letters = (k) => Array.from({ length: k }, () => "ABCDEFGHJKLMNPQRSTUVWXYZ"[rnd(24)]).join("");
  const first = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vikram", "Isha", "Arjun", "Kavya", "Siddharth", "Nisha"];
  const last = ["Sharma", "Iyer", "Reddy", "Patel", "Nair", "Gupta", "Das", "Kulkarni", "Singh", "Menon", "Bose", "Joshi"];
  const banks = ["SBIN", "HDFC", "ICIC", "UTIB", "KKBK", "PUNB"];
  const handles = ["okaxis", "ybl", "oksbi", "paytm", "okicici"];
  const rows = ["customer,aadhaar,pan,mobile,upi,ifsc,order_id,amount,note"];
  for (let i = 0; i < n; i++) {
    const a11 = String(2 + rnd(8)) + digits(10);
    const aadhaar = a11 + verhoeffCheckDigit(a11);
    const pan = letters(3) + "P" + letters(1) + digits(4) + letters(1);
    const f = first[rnd(first.length)];
    const l = last[rnd(last.length)];
    const mobile = String(6 + rnd(4)) + digits(9);
    const upi = `${f.toLowerCase()}.${l.toLowerCase()}${rnd(99)}@${handles[rnd(handles.length)]}`;
    const ifsc = banks[rnd(banks.length)] + "0" + digits(6);
    const order = String(1 + rnd(9)) + digits(11);
    const amount = (rnd(500000) / 100).toFixed(2);
    const note = i % 7 === 0 ? `"callback on ${mobile.slice(0, 5)} ${mobile.slice(5)}"` : "";
    rows.push([`${f} ${l}`, `${aadhaar.slice(0, 4)} ${aadhaar.slice(4, 8)} ${aadhaar.slice(8)}`, pan, mobile, upi, ifsc, order, amount, note].join(","));
  }
  return rows.join("\n") + "\n";
}

// --- boot -------------------------------------------------------------------------------------------
buildRules();
renderPolicy();
renderProvider();
newSession();
