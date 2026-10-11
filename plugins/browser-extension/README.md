# Saaf browser extension (Chrome / Edge, MV3)

It warns before you send Aadhaar, PAN, GSTIN, UPI and other Indian PII to ChatGPT, Claude or Gemini, and masks it in one click. **Detection runs locally.** The extension makes no network requests and stores only aggregate counts (types and counts) for its popup.

## Build and load

```bash
npm run build --workspace packages/saaf-js
node plugins/browser-extension/build.mjs      # copies the engine into lib/
```

In Chrome, open `chrome://extensions`, turn on Developer mode, choose **Load unpacked** and select `plugins/browser-extension`.

## Behaviour

- On Enter or the send button, the draft is scanned. If PII is found, a dialog offers **Mask & send**, **Send anyway** or **Cancel**.
- Popup modes: warn (default), mask automatically, off.
- Restoring values inside the site's reply is intentionally **not** done: third-party pages change too often (see the development plan).

## Upkeep

Site selectors live in `SITES` in `src/content.js` and will break as the sites change. Phase 3 moves them to a signed remote config, with a weekly live smoke test. Budget about half a day per week.

## Store submission checklist (Phase 3)

- [ ] 128/48/16 px icons; screenshots; privacy policy ("no data collected or transmitted")
- [ ] Single-purpose description; host permissions justified per site
- [ ] Firefox port (`browser_specific_settings`)
