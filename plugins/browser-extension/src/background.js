// Background: opens session storage to the content script (that is where the
// vault lives) and keeps the sites a user turned on from the popup registered.

const api = globalThis.browser ?? globalThis.chrome;
const SCRIPT_ID = "saaf-user-sites";

api.storage.session?.setAccessLevel?.({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" }).catch(() => {});

async function sync() {
  const { sites = [] } = await api.storage.sync.get({ sites: [] });
  const granted = [];
  for (const origin of sites) {
    if (await api.permissions.contains({ origins: [`${origin}/*`] })) granted.push(`${origin}/*`);
  }
  const existing = await api.scripting.getRegisteredContentScripts({ ids: [SCRIPT_ID] });
  if (existing.length) await api.scripting.unregisterContentScripts({ ids: [SCRIPT_ID] });
  if (!granted.length) return;
  await api.scripting.registerContentScripts([
    { id: SCRIPT_ID, matches: granted, js: ["content.js"], css: ["overlay.css"], runAt: "document_idle", persistAcrossSessions: true },
  ]);
}

api.runtime.onInstalled.addListener(() => sync().catch(console.error));
api.runtime.onStartup?.addListener(() => sync().catch(console.error));
api.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && changes.sites) sync().catch(console.error);
});
api.permissions.onRemoved?.addListener(() => sync().catch(console.error));

// A site was allowed from the popup. Handled here because Firefox closes the
// popup while its permission prompt is open.
api.permissions.onAdded?.addListener(async ({ origins = [] }) => {
  const added = origins.map((o) => o.replace(/\/\*$/, ""));
  const { sites = [] } = await api.storage.sync.get({ sites: [] });
  await api.storage.sync.set({ sites: [...new Set([...sites, ...added])] });
  for (const tab of await api.tabs.query({ url: origins })) {
    await api.scripting.insertCSS({ target: { tabId: tab.id }, files: ["overlay.css"] }).catch(() => {});
    await api.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] }).catch(() => {});
  }
});
