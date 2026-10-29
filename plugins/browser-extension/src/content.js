// Saaf content script: mask on send, restore on screen.
//
// 1. On Enter or the send button, the draft is scanned on this device. If it
//    holds personal data, Saaf asks (or, in auto mode, just masks) and the
//    model receives tokens such as [PAN_1] instead of the values.
// 2. When the reply shows those tokens, they are swapped back for the real
//    values on this screen only (reveal.js).
// The vault lives in the extension's session storage, never in the page, and
// is gone when the browser closes. No network requests are made.

import { Saaf, defaultSpec } from "@safearly/saaf";

import { startReveal } from "./reveal.js";
import { findComposer, findSendButton, isSendButton, siteFor } from "./sites.js";

const api = globalThis.browser ?? globalThis.chrome;

if (!globalThis.__saafLoaded) {
  globalThis.__saafLoaded = true;
  main();
}

function main() {
  const site = siteFor(location.hostname);
  const saaf = new Saaf();
  const vaultKey = `vault:${location.hostname}`;
  const settings = { mode: "warn", reveal: true }; // mode: warn | auto-mask | off
  let bypass = false;

  api.storage.sync.get(settings).then((s) => Object.assign(settings, s)).catch(() => {});
  sessionStore()
    ?.get(vaultKey)
    .then((got) => {
      if (got[vaultKey]) saaf.importVault(got[vaultKey]);
      reveal.rescan();
    })
    .catch(() => {});

  api.storage.onChanged.addListener((changes, area) => {
    if (area === "sync") for (const k of Object.keys(settings)) if (changes[k]) settings[k] = changes[k].newValue;
    if (area === "session" && changes[vaultKey] && !changes[vaultKey].newValue) saaf.clearVault();
  });

  const reveal = startReveal({ saaf, enabled: () => settings.reveal });

  // ---- send guard -------------------------------------------------------

  function guard(event, composer) {
    if (bypass || settings.mode === "off" || !composer) return;
    const text = readText(composer);
    if (!text.trim()) return;
    const found = saaf.scan(text);
    if (!found.length) return; // clean: let the site send as usual
    event.preventDefault();
    event.stopImmediatePropagation();
    bump(found);
    if (settings.mode === "auto-mask") return maskAndSend(composer, text);
    dialog(found).then((choice) => {
      if (choice === "always") api.storage.sync.set({ mode: "auto-mask" });
      if (choice === "mask" || choice === "always") maskAndSend(composer, text);
      else if (choice === "send") send(composer);
      else composer.focus();
    });
  }

  function maskAndSend(composer, text) {
    const r = saaf.mask(text);
    sessionStore()?.set({ [vaultKey]: saaf.exportVault() }).catch(() => {});
    writeText(composer, r.text);
    // Editors apply the change asynchronously. Only send once the composer
    // really holds the masked text; otherwise leave it there for the user.
    setTimeout(() => {
      if (saaf.scan(readText(composer)).length) {
        toast("Masked. Check the message, then press send.");
        return;
      }
      toast(`Masked ${r.tokens.length} item${r.tokens.length === 1 ? "" : "s"} on this device.`);
      send(composer);
    }, 80);
  }

  function send(composer) {
    bypass = true;
    try {
      const btn = findSendButton(site, composer);
      if (btn) btn.click();
      else
        composer.dispatchEvent(
          new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }),
        );
    } finally {
      setTimeout(() => (bypass = false), 0);
    }
  }

  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "Enter" || e.shiftKey || e.isComposing || !e.isTrusted) return;
      const composer = findComposer(site, e.target);
      if (composer && composer.contains(e.target)) guard(e, composer);
    },
    true,
  );

  document.addEventListener(
    "click",
    (e) => {
      if (!e.isTrusted) return;
      const btn = e.target?.closest?.("button, [role='button']");
      const composer = btn && findComposer(site, null);
      if (composer && isSendButton(site, btn, composer)) guard(e, composer);
    },
    true,
  );
}

// ---- helpers --------------------------------------------------------------

// storage.session is readable here only after background.js opens it to content scripts.
function sessionStore() {
  try {
    return api.storage.session ?? null;
  } catch {
    return null;
  }
}

const readText = (el) => (el instanceof HTMLTextAreaElement ? el.value : el.innerText);

function writeText(el, text) {
  el.focus();
  if (el instanceof HTMLTextAreaElement) {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  // Rich editors (ProseMirror, Quill, Lexical) only observe real editing commands.
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  document.execCommand("insertText", false, text);
}

const SHORT = { PAN: "PAN", GSTIN: "GSTIN", IFSC: "IFSC code", PERSON: "Name", PHONE_IN: "Mobile number", TAN: "TAN" };
let labels;
const pretty = (entity) => {
  labels ??= Object.fromEntries(defaultSpec().entities.map((e) => [e.id, e.label]));
  return SHORT[entity] ?? labels[entity] ?? entity;
};

// Enough of the value to recognise it, not enough to read it over a shoulder.
function preview(value) {
  const v = value.trim();
  if (v.length <= 6) return "•".repeat(v.length);
  return v.slice(0, 2) + "•".repeat(Math.min(v.length - 4, 10)) + v.slice(-2);
}

function dialog(found) {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "saaf-overlay";
    wrap.setAttribute("role", "alertdialog");
    wrap.setAttribute("aria-modal", "true");
    wrap.setAttribute("aria-labelledby", "saaf-title");
    wrap.innerHTML = `
      <div class="saaf-card">
        <div class="saaf-head"><span class="saaf-mark" aria-hidden="true"><i></i><i></i></span><span id="saaf-title">Personal data in your message</span></div>
        <ul class="saaf-list"></ul>
        <p class="saaf-note">Checked on this device. Nothing has been sent. If you mask, the AI sees tokens like <code>[PAN_1]</code> and you see the real values in its reply.</p>
        <div class="saaf-actions">
          <button type="button" data-a="mask" class="saaf-primary">Mask &amp; send</button>
          <button type="button" data-a="send">Send anyway</button>
          <button type="button" data-a="cancel">Cancel</button>
        </div>
        <label class="saaf-always"><input type="checkbox"> Always mask without asking</label>
      </div>`;
    const list = wrap.querySelector(".saaf-list");
    for (const f of found.slice(0, 8)) {
      const li = document.createElement("li");
      const kind = document.createElement("b");
      kind.textContent = pretty(f.entity);
      const val = document.createElement("span");
      val.textContent = preview(f.text);
      li.append(kind, val);
      list.append(li);
    }
    if (found.length > 8) {
      const li = document.createElement("li");
      li.textContent = `and ${found.length - 8} more`;
      list.append(li);
    }
    const always = wrap.querySelector(".saaf-always input");
    const done = (a) => {
      wrap.remove();
      document.removeEventListener("keydown", onKey, true);
      resolve(a === "mask" && always.checked ? "always" : a);
    };
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        done("cancel");
      } else if (e.key === "Tab") {
        // Keep focus inside the dialog.
        const items = [...wrap.querySelectorAll("button, input")];
        const i = items.indexOf(document.activeElement);
        const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : (i + 1) % items.length;
        e.preventDefault();
        items[next].focus();
      }
      e.stopPropagation();
    };
    wrap.addEventListener("click", (e) => {
      const a = e.target?.closest?.("button")?.dataset?.a;
      if (a) done(a);
      else if (e.target === wrap) done("cancel");
    });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(wrap);
    wrap.querySelector(".saaf-primary").focus();
  });
}

function toast(message) {
  document.querySelector(".saaf-toast")?.remove();
  const t = document.createElement("div");
  t.className = "saaf-toast";
  t.setAttribute("role", "status");
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

function bump(found) {
  // Local, aggregate counters only (types and counts) for the popup.
  api.storage.local
    .get({ stats: {} })
    .then(({ stats }) => {
      for (const f of found) stats[f.entity] = (stats[f.entity] ?? 0) + 1;
      return api.storage.local.set({ stats });
    })
    .catch(() => {});
}
