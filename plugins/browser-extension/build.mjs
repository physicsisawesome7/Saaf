// Copies the compiled @safearly/saaf (packages/saaf-js/dist) into lib/ and
// zips nothing: load the folder unpacked, or let CI package it.
//   npm --prefix packages/saaf-js run build && node plugins/browser-extension/build.mjs
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "../../packages/saaf-js/dist");
const lib = resolve(here, "lib");

if (!existsSync(resolve(dist, "index.js"))) {
  console.error("packages/saaf-js/dist is missing: run `npm --prefix packages/saaf-js run build` first");
  process.exit(1);
}
rmSync(lib, { recursive: true, force: true });
mkdirSync(lib, { recursive: true });
cpSync(dist, lib, { recursive: true, filter: (src) => !src.endsWith(".map") && !src.endsWith(".d.ts") });
console.log(`copied saaf-js into ${lib}`);
