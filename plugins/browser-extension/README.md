# Saaf for AI chats (browser extension, MV3)

Masks personal data before you send it to ChatGPT, Claude, Gemini or any AI chat, and shows the real values in the reply on your screen. **Everything runs locally.** The extension makes no network requests.

Install page and privacy policy: <https://safearly.com/saaf/extension>.

## How it works

1. **Mask on send.** On Enter or the send button, the draft is scanned on the device with `@safearly/saaf`. Clean messages are sent untouched, with no delay. If personal data is found, a dialog lists it, partly hidden, and offers **Mask & send**, **Send anyway** or **Cancel**. In *mask automatically* mode it just masks. The AI receives tokens such as `[PAN_1]`; one value keeps one token for the whole browser session.
2. **Restore on screen.** When a token appears on the page, its text node is rewritten in place with the real value and highlighted with the CSS Custom Highlight API. It works mid-stream and with the loose forms models produce (`pan_1`, `\[PAN_1\]`). It is display only: the site's copy button and history keep the tokens.
3. **The vault** (token → value) lives in `storage.session`, opened to the content script by `background.js`. Websites can't read it, it survives a page reload and it is wiped when the browser closes or when you choose **Forget saved values**.

| File | Role |
| --- | --- |
| `src/content.js` | send guard, dialog, toast, vault persistence |
| `src/reveal.js` | restores tokens in the page (MutationObserver + Highlight API) |
| `src/sites.js` | composer and send-button selectors per site, plus generic heuristics |
| `src/background.js` | opens session storage; registers sites the user turned on |
| `src/popup.*` | mode, reveal switch, per-site switch, counts |

## Sites

- **Built in (no extra permission):** ChatGPT, Claude and Gemini with exact selectors. Perplexity, Copilot, DeepSeek, Le Chat and Grok use the generic heuristics. The list is in `manifest.json` and `BUILT_IN` in `src/sites.js`; keep the two in sync.
- **Any other site:** **Turn on** in the popup requests that one origin (`optional_host_permissions`), then `background.js` registers the content script for it and injects it into open tabs.

## Build, load and test

```bash
npm ci
npm run extension          # builds saaf-js, then build/chrome, build/firefox and dist/*.zip
```

- **Chrome/Edge:** open `chrome://extensions`, turn on Developer mode, choose **Load unpacked** and select `build/chrome`.
- **Firefox:** open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on** and select `build/firefox/manifest.json`. On Firefox, allow the site permissions from the add-on's menu after install; Firefox treats MV3 host permissions as opt-in.

To test without installing: serve the folder (`python -m http.server 8091 --directory plugins/browser-extension`) and open `/test/harness.html`. That page is a fake chat site with a stub `chrome` API. It streams each sent message back as a "reply", and `window.sent` records what the "server" received.

Manual QA before each release, on each built-in site:

- [ ] A clean message is sent normally (Enter and button).
- [ ] A message with a test PAN (`ABCPE1234F`) or Aadhaar (`2345 6789 0124`) opens the dialog. **Mask & send** sends only tokens; **Send anyway** sends the original; Escape cancels and keeps the draft.
- [ ] The reply shows the real value, highlighted, and still does after a page reload.
- [ ] Auto-mask mode shows the toast and sends tokens; **Off** does nothing.
- [ ] **Turn on** works for an unlisted site and survives a browser restart; **Turn off** removes it.

## Known limits

- Only typed or pasted text is checked; uploaded files and images are not.
- Names in free text are only caught after a cue ("Mr", "name:"); see `docs/limitations.md`.
- Selectors drift as sites change. Budget about half a day a week, and treat a broken site as a P1, because a silent failure looks like protection.

## Store submission

See [STORE.md](STORE.md) for the listing text, permission justifications and the checklist.
