import { BUILT_IN } from "./sites.js";

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

$("ver").textContent = `v${api.runtime.getManifest().version}`;

// ---- settings -------------------------------------------------------------

const radios = [...document.querySelectorAll("input[name=mode]")];
api.storage.sync.get({ mode: "warn", reveal: true }).then(({ mode, reveal }) => {
  for (const r of radios) r.checked = r.value === mode;
  $("reveal").checked = reveal;
});
for (const r of radios) r.addEventListener("change", () => api.storage.sync.set({ mode: r.value }));
$("reveal").addEventListener("change", (e) => api.storage.sync.set({ reveal: e.target.checked }));

// ---- counts ---------------------------------------------------------------

function showStats(stats) {
  const rows = Object.entries(stats).sort((a, b) => b[1] - a[1]);
  const box = $("stats");
  box.replaceChildren();
  if (!rows.length) {
    box.textContent = "Nothing yet.";
    box.className = "muted";
    return;
  }
  box.className = "chips";
  for (const [k, n] of rows) {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = `${k.replace(/_/g, " ")} · ${n}`;
    box.append(c);
  }
}
api.storage.local.get({ stats: {} }).then(({ stats }) => showStats(stats));
$("reset").addEventListener("click", () => api.storage.local.set({ stats: {} }).then(() => showStats({})));

$("forget").addEventListener("click", async () => {
  const all = await api.storage.session.get(null);
  await api.storage.session.remove(Object.keys(all).filter((k) => k.startsWith("vault:")));
  $("forget").textContent = "Forgotten";
});

// ---- this site ------------------------------------------------------------

async function showSite() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  let url;
  try {
    url = new URL(tab?.url ?? "");
  } catch {
    url = null;
  }
  const name = $("site-name");
  const state = $("site-state");
  const btn = $("site-btn");
  btn.hidden = true;
  state.className = "site-state";

  if (!url || !/^https?:$/.test(url.protocol)) {
    name.textContent = "This page";
    state.textContent = "Saaf can't run on browser pages.";
    return;
  }
  name.textContent = url.hostname;
  if (BUILT_IN[url.hostname]) {
    state.textContent = `Protected · ${BUILT_IN[url.hostname]}`;
    state.classList.add("on");
    return;
  }
  const origin = `${url.protocol}//${url.hostname}`; // match patterns carry no port
  const { sites = [] } = await api.storage.sync.get({ sites: [] });
  const on = sites.includes(origin) && (await api.permissions.contains({ origins: [`${origin}/*`] }));
  btn.hidden = false;
  if (on) {
    state.textContent = "Protected · turned on by you";
    state.classList.add("on");
    btn.textContent = "Turn off";
    btn.className = "secondary";
    btn.onclick = async () => {
      await api.storage.sync.set({ sites: sites.filter((s) => s !== origin) });
      await api.permissions.remove({ origins: [`${origin}/*`] }).catch(() => {});
      showSite();
    };
  } else {
    state.textContent = "Not protected. Turn on for any AI chat site.";
    btn.textContent = "Turn on";
    btn.className = "";
    btn.onclick = async () => {
      // Must run straight from the click: the browser asks the user to allow
      // this one site. background.js then saves it and starts Saaf on the tab.
      if (await api.permissions.request({ origins: [`${origin}/*`] })) setTimeout(showSite, 300);
    };
  }
}
showSite();
