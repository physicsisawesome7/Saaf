"use strict";

const radios = [...document.querySelectorAll("input[name=mode]")];

chrome.storage.sync.get({ mode: "warn" }).then(({ mode }) => {
  for (const r of radios) r.checked = r.value === mode;
});
for (const r of radios) {
  r.addEventListener("change", () => chrome.storage.sync.set({ mode: r.value }));
}

chrome.storage.local.get({ stats: {} }).then(({ stats }) => {
  const rows = Object.entries(stats).sort((a, b) => b[1] - a[1]);
  if (rows.length) {
    document.getElementById("stats").textContent = rows.map(([k, n]) => `${k}: ${n}`).join(" · ");
  }
});
