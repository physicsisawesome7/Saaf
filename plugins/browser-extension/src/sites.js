// Where the composer and the send button are on each chat site.
//
// Named sites get exact selectors. Every other site, including the ones a user
// turns on from the popup, uses the generic heuristics below. Selectors drift
// as sites change: this file is the main upkeep cost (see README "Upkeep").

export const EDITABLE = "textarea, [contenteditable='true'], [contenteditable=''], [contenteditable='plaintext-only']";

const SITES = {
  "chatgpt.com": {
    name: "ChatGPT",
    composer: "#prompt-textarea, div[contenteditable='true'].ProseMirror",
    send: "button[data-testid='send-button'], button#composer-submit-button",
  },
  "claude.ai": {
    name: "Claude",
    composer: "div[contenteditable='true'].ProseMirror",
    send: "button[aria-label='Send message'], button[aria-label='Send Message']",
  },
  "gemini.google.com": {
    name: "Gemini",
    composer: "rich-textarea .ql-editor",
    send: "button.send-button, button[aria-label='Send message']",
  },
};
SITES["chat.openai.com"] = SITES["chatgpt.com"];

/** Hosts covered without any extra permission (keep in sync with manifest.json). */
export const BUILT_IN = {
  "chatgpt.com": "ChatGPT",
  "chat.openai.com": "ChatGPT",
  "claude.ai": "Claude",
  "gemini.google.com": "Gemini",
  "www.perplexity.ai": "Perplexity",
  "copilot.microsoft.com": "Copilot",
  "chat.deepseek.com": "DeepSeek",
  "chat.mistral.ai": "Le Chat",
  "grok.com": "Grok",
};

const SEND_WORDS = /\b(send|submit|ask)\b/i;

export function siteFor(host) {
  return SITES[host] ?? { name: BUILT_IN[host] ?? host, composer: EDITABLE, send: null };
}

/** The composer that owns `from`, or the page's main one. */
export function findComposer(site, from) {
  const own = from?.closest?.(site.composer);
  if (own) return outermostEditable(own);
  if (site.send) {
    const el = document.querySelector(site.composer);
    return el && outermostEditable(el);
  }
  // Generic: the focused editable, else the largest visible one.
  const active = document.activeElement?.closest?.(EDITABLE);
  if (active) return outermostEditable(active);
  let best = null;
  let bestArea = 0;
  for (const el of document.querySelectorAll(EDITABLE)) {
    const r = el.getBoundingClientRect();
    if (r.width * r.height > bestArea && r.width > 0) [best, bestArea] = [el, r.width * r.height];
  }
  return best && outermostEditable(best);
}

// Rich editors nest contenteditable nodes; the composer is the outermost one.
function outermostEditable(el) {
  let top = el;
  while (top.parentElement?.closest(EDITABLE)) top = top.parentElement.closest(EDITABLE);
  return top;
}

const label = (b) =>
  [b.getAttribute("aria-label"), b.getAttribute("title"), b.getAttribute("data-testid"), b.textContent]
    .filter(Boolean)
    .join(" ");

/** Is `btn` the button that sends `composer`'s text? */
export function isSendButton(site, btn, composer) {
  if (!btn || btn.disabled) return false;
  if (site.send) return btn.matches(site.send);
  if (!composer || !SEND_WORDS.test(label(btn))) return false;
  // Generic: a send-like button that sits near the composer.
  for (let box = composer.parentElement, i = 0; box && i < 6; box = box.parentElement, i++) {
    if (box.contains(btn)) return true;
  }
  return false;
}

export function findSendButton(site, composer) {
  if (site.send) return document.querySelector(site.send);
  const form = composer?.closest("form");
  const submit = form?.querySelector("button[type='submit']:not([disabled])");
  if (submit) return submit;
  for (let box = composer?.parentElement, i = 0; box && i < 6; box = box.parentElement, i++) {
    for (const b of box.querySelectorAll("button:not([disabled])")) if (isSendButton(site, b, composer)) return b;
  }
  return null;
}
