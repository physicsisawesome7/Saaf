// Saaf content script: warn-and-mask-on-submit for AI chat sites.
//
// Intercepts Enter / send-button clicks in the chat composer, scans the draft
// locally with @safearly/saaf, and if PII is found shows a small dialog:
//   [Mask & send]  [Send anyway]  [Cancel]
// Nothing leaves the page: detection runs in this content script.
//
// Site selectors live in SITES and WILL drift as sites change; that is the
// main maintenance cost of this extension (see README "Upkeep").

(() => {
  "use strict";

  const SITES = {
    "chatgpt.com": {
      composer: "#prompt-textarea, div[contenteditable='true'].ProseMirror, textarea",
      send: "button[data-testid='send-button'], button#composer-submit-button",
    },
    "claude.ai": {
      composer: "div[contenteditable='true'].ProseMirror, div[contenteditable='true']",
      send: "button[aria-label='Send message'], button[aria-label='Send Message']",
    },
    "gemini.google.com": {
      composer: "rich-textarea .ql-editor, div[contenteditable='true']",
      send: "button.send-button, button[aria-label='Send message']",
    },
  };
  const site = SITES[location.hostname] ?? { composer: "textarea, [contenteditable='true']", send: "button[type='submit']" };

  let saafModule = null;
  let bypass = false;
  let settings = { mode: "warn" }; // warn | auto-mask | off

  const loadSaaf = async () => (saafModule ??= await import(chrome.runtime.getURL("lib/index.js")));

  chrome.storage?.sync.get({ mode: "warn" }).then((s) => (settings = s)).catch(() => {});
  chrome.storage?.onChanged.addListener((changes) => {
    if (changes.mode) settings.mode = changes.mode.newValue;
  });

  const findComposer = (from) =>
    (from && from.closest?.(site.composer)) || document.querySelector(site.composer);

  const readText = (el) => (el instanceof HTMLTextAreaElement ? el.value : el.innerText);

  function writeText(el, text) {
    el.focus();
    if (el instanceof HTMLTextAreaElement) {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(el, text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    // Rich editors (ProseMirror, Quill) only observe real editing commands.
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand("insertText", false, text);
  }

  function describe(counts) {
    return Object.entries(counts)
      .map(([entity, n]) => `${n} × ${entity.replace(/_/g, " ")}`)
      .join(", ");
  }

  function dialog(counts) {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "saaf-overlay";
      wrap.setAttribute("role", "alertdialog");
      wrap.setAttribute("aria-label", "Saaf personal data warning");
      wrap.innerHTML = `
        <div class="saaf-card">
          <div class="saaf-title">Personal data in your message</div>
          <div class="saaf-body"></div>
          <div class="saaf-note">Checked on this device. Nothing was sent.</div>
          <div class="saaf-actions">
            <button data-a="mask" class="saaf-primary">Mask &amp; send</button>
            <button data-a="send">Send anyway</button>
            <button data-a="cancel">Cancel</button>
          </div>
        </div>`;
      wrap.querySelector(".saaf-body").textContent = `Found ${describe(counts)}.`;
      const done = (a) => {
        wrap.remove();
        document.removeEventListener("keydown", onKey, true);
        resolve(a);
      };
      const onKey = (e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          done("cancel");
        }
      };
      wrap.addEventListener("click", (e) => {
        const a = e.target?.dataset?.a;
        if (a) done(a);
      });
      document.addEventListener("keydown", onKey, true);
      document.body.appendChild(wrap);
      wrap.querySelector(".saaf-primary").focus();
    });
  }

  function resend(composer) {
    bypass = true;
    try {
      const btn = document.querySelector(site.send);
      if (btn) btn.click();
      else composer.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
    } finally {
      setTimeout(() => (bypass = false), 0);
    }
  }

  async function guard(event, composer) {
    if (bypass || settings.mode === "off" || !composer) return;
    const text = readText(composer);
    if (!text || !text.trim()) return;
    // Stop the send synchronously; decide after the (async) scan.
    event.preventDefault();
    event.stopImmediatePropagation();
    const { Saaf } = await loadSaaf();
    const saaf = new Saaf();
    const result = saaf.mask(text);
    if (!result.applied.length) return resend(composer);
    bump(result.entityCounts);
    const choice = settings.mode === "auto-mask" ? "mask" : await dialog(result.entityCounts);
    if (choice === "cancel") return;
    if (choice === "mask") writeText(composer, result.text);
    resend(composer);
  }

  function bump(counts) {
    // Local, aggregate counters only (types and counts) for the popup.
    chrome.storage?.local.get({ stats: {} }).then(({ stats }) => {
      for (const [k, n] of Object.entries(counts)) stats[k] = (stats[k] ?? 0) + n;
      chrome.storage.local.set({ stats });
    });
  }

  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
      const composer = findComposer(e.target);
      if (composer && composer.contains(e.target)) guard(e, composer);
    },
    true,
  );

  document.addEventListener(
    "click",
    (e) => {
      const btn = e.target?.closest?.(site.send);
      if (btn) guard(e, findComposer(null));
    },
    true,
  );
})();
