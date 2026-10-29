// Show real values in the model's reply, on this screen only.
//
// The model only ever saw tokens such as [PAN_1]. When one appears on the
// page, its text node is rewritten in place with the value from the local
// vault, and highlighted with the CSS Custom Highlight API (no extra DOM, so
// the site's own rendering is not disturbed). Nothing is sent anywhere, and
// the site's copy buttons and history still hold the tokens.

const SKIP = "script, style, noscript, textarea, input, [contenteditable], .saaf-overlay, .saaf-toast";
const MAYBE_TOKEN = /[A-Za-z]_?\s?#?\d/;

export function startReveal({ saaf, enabled }) {
  const highlight = typeof Highlight === "function" && globalThis.CSS?.highlights ? new Highlight() : null;
  if (highlight) CSS.highlights.set("saaf-restored", highlight);
  const pending = new Set();
  let scheduled = false;

  const originals = () => saaf.exportVault().entries.map((e) => e.original);

  function fix(node) {
    if (!node.isConnected || !node.data || !MAYBE_TOKEN.test(node.data)) return;
    if (node.parentElement?.closest(SKIP)) return;
    const r = saaf.restore(node.data);
    if (!r.restored) return;
    node.data = r.text;
    if (!highlight) return;
    for (const value of originals()) {
      for (let at = r.text.indexOf(value); at !== -1; at = r.text.indexOf(value, at + value.length)) {
        const range = new Range();
        range.setStart(node, at);
        range.setEnd(node, at + value.length);
        highlight.add(range);
      }
    }
  }

  function scan(root) {
    if (root.nodeType === Node.TEXT_NODE) return fix(root);
    if (root.nodeType !== Node.ELEMENT_NODE || root.closest?.(SKIP)) return;
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) fix(n);
  }

  function flush() {
    scheduled = false;
    if (!enabled() || !saaf.tokens().length) return pending.clear();
    for (const n of pending) scan(n);
    pending.clear();
    if (highlight) for (const r of highlight) if (r.collapsed || !r.startContainer.isConnected) highlight.delete(r);
  }

  const queue = (n) => {
    pending.add(n);
    if (!scheduled) {
      scheduled = true;
      setTimeout(flush, 16); // not rAF: that pauses in background tabs while replies stream
    }
  };

  new MutationObserver((records) => {
    for (const rec of records) {
      if (rec.type === "characterData") queue(rec.target);
      else for (const n of rec.addedNodes) queue(n);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true });

  return { rescan: () => queue(document.body) };
}
