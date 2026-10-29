// Builds the extension for Chrome/Edge and Firefox.
//
//   npm run extension            (from the repo root: builds saaf-js first)
//
// Output:
//   build/chrome/, build/firefox/   load these unpacked
//   dist/saaf-<browser>-<version>.zip   upload these to the stores
//
// Each script is bundled with esbuild into one classic file, so no extension
// files are exposed to web pages (no web_accessible_resources).
import { build } from "esbuild";
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateRawSync } from "node:zlib";

const here = dirname(fileURLToPath(import.meta.url));
const base = JSON.parse(readFileSync(resolve(here, "manifest.json"), "utf8"));

const TARGETS = {
  chrome: {
    ...base,
    background: { service_worker: "background.js" },
    minimum_chrome_version: "122",
  },
  firefox: {
    ...base,
    background: { scripts: ["background.js"] },
    browser_specific_settings: {
      gecko: {
        id: "saaf@safearly.com",
        strict_min_version: "128.0",
        data_collection_permissions: { required: ["none"] },
      },
    },
  },
};

rmSync(resolve(here, "build"), { recursive: true, force: true });
mkdirSync(resolve(here, "dist"), { recursive: true });

for (const [name, manifest] of Object.entries(TARGETS)) {
  const out = resolve(here, "build", name);
  await build({
    entryPoints: ["content", "background", "popup"].map((f) => resolve(here, "src", `${f}.js`)),
    outdir: out,
    bundle: true,
    format: "iife",
    target: name === "chrome" ? "chrome122" : "firefox128",
    legalComments: "none",
    logLevel: "warning",
  });
  for (const f of ["popup.html", "popup.css", "overlay.css"]) cpSync(resolve(here, "src", f), join(out, f));
  cpSync(resolve(here, "icons"), join(out, "icons"), { recursive: true });
  writeFileSync(join(out, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  const zip = resolve(here, "dist", `saaf-${name}-${manifest.version}.zip`);
  writeFileSync(zip, zipDir(out));
  console.log(`${name}: ${relative(process.cwd(), out)}  ->  ${relative(process.cwd(), zip)}`);
}

// ---- a minimal deflate zip writer (enough for store uploads) ----------------

function zipDir(root) {
  const files = [];
  const walk = (d) => {
    for (const n of readdirSync(d).sort()) {
      const p = join(d, n);
      if (statSync(p).isDirectory()) walk(p);
      else files.push(p);
    }
  };
  walk(root);
  const local = [];
  const central = [];
  let offset = 0;
  for (const p of files) {
    const name = Buffer.from(relative(root, p).replaceAll("\\", "/"));
    const raw = readFileSync(p);
    const data = deflateRawSync(raw, { level: 9 });
    const crc = crc32(raw);
    const head = Buffer.alloc(30);
    head.writeUInt32LE(0x04034b50, 0);
    head.writeUInt16LE(20, 4);
    head.writeUInt16LE(8, 8);
    head.writeUInt16LE(0x21, 12); // 1980-01-01, so builds are reproducible
    head.writeUInt32LE(crc, 14);
    head.writeUInt32LE(data.length, 18);
    head.writeUInt32LE(raw.length, 22);
    head.writeUInt16LE(name.length, 26);
    local.push(head, name, data);
    const dir = Buffer.alloc(46);
    dir.writeUInt32LE(0x02014b50, 0);
    dir.writeUInt16LE(20, 4);
    dir.writeUInt16LE(20, 6);
    dir.writeUInt16LE(8, 10);
    dir.writeUInt16LE(0x21, 14);
    dir.writeUInt32LE(crc, 16);
    dir.writeUInt32LE(data.length, 20);
    dir.writeUInt32LE(raw.length, 24);
    dir.writeUInt16LE(name.length, 28);
    dir.writeUInt32LE(offset, 42);
    central.push(dir, name);
    offset += 30 + name.length + data.length;
  }
  const size = central.reduce((n, b) => n + b.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(size, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, ...central, end]);
}

function crc32(buf) {
  let c = ~0;
  for (const b of buf) {
    c ^= b;
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}
