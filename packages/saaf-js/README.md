# @safearly/saaf

TypeScript port of Saaf for Node 20+ and modern browsers. No dependencies. It passes the same conformance vectors as the Python package.

```bash
npm i @safearly/saaf
```

```ts
import { Saaf } from "@safearly/saaf";

const saaf = new Saaf();
const r = saaf.mask("Aadhaar 2345 6789 0124, UPI ravi@okaxis");
r.text;            // "Aadhaar [AADHAAR_1], UPI [UPI_ID_1]"
saaf.restore("ok [aadhaar_1]").text;

const s = saaf.streamRestorer();
for await (const chunk of stream) process.stdout.write(s.feed(chunk));
process.stdout.write(s.flush());
```

Policy options: `mode` (`enforce`/`shadow`), `threshold`, `defaultAction` (`mask`/`warn`/`allow`/`block`), per-entity `entities`, `enabledEntities`, `onUnknownToken`.

Persistent vaults, audit signing, destination rules, hmac/fake tokens and cross-turn detection are available in the Python package only.
