// Prepares apps/website for deployment: copies the compiled Saaf engine
// (@safearly/saaf, packages/saaf-js/dist) into assets/saaf/ for the live demo
// and the playground. The site is otherwise plain static files: no bundler.
//
//   npm run build --workspace packages/saaf-js && node apps/website/build.mjs
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "../../packages/saaf-js/dist");
const out = resolve(here, "assets/saaf");

if (!existsSync(resolve(dist, "index.js"))) {
  console.error("packages/saaf-js/dist is missing: run `npm run build --workspace packages/saaf-js` first");
  process.exit(1);
}
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(dist, out, { recursive: true, filter: (src) => !src.endsWith(".map") && !src.endsWith(".d.ts") });
console.log(`copied saaf-js into ${out}`);
