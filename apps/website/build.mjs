// Builds safearly.com into apps/website (the Firebase public dir):
//  1. copies the compiled Saaf engine (packages/saaf-js/dist) into assets/saaf/
//     for the live demo and the playground;
//  2. renders every page in src/pages/ inside one shared layout (head, icons,
//     header, footer), so all pages share the same chrome;
//  3. writes sitemap.xml and the blog feed (blog/feed.xml) from page metadata.
//
// A page starts with a metadata comment:  <!--page {"path": "/saaf", ...} -->
// followed by the HTML that goes inside <main>.
//
//   npm run build --workspace packages/saaf-js && node apps/website/build.mjs
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SITE = "https://safearly.com";
const GITHUB = "https://github.com/physicsisawesome7";
const REPO = `${GITHUB}/Saaf`;
const SMRITI = `${GITHUB}/smriti`;
const LINKEDIN = "https://www.linkedin.com/in/lalit-shukla-884275188/";
const EMAIL = "lalit@safearly.com";
const YEAR = new Date().getFullYear();

// 1. engine -------------------------------------------------------------------
const dist = resolve(here, "../../packages/saaf-js/dist");
const engineOut = resolve(here, "assets/saaf");
if (!existsSync(resolve(dist, "index.js"))) {
  console.error("packages/saaf-js/dist is missing: run `npm run build --workspace packages/saaf-js` first");
  process.exit(1);
}
rmSync(engineOut, { recursive: true, force: true });
mkdirSync(engineOut, { recursive: true });
cpSync(dist, engineOut, { recursive: true, filter: (src) => !src.endsWith(".map") && !src.endsWith(".d.ts") });

// Browser extension downloads (built by plugins/browser-extension/build.mjs).
const extDist = resolve(here, "../../plugins/browser-extension/dist");
const downloads = resolve(here, "downloads");
rmSync(downloads, { recursive: true, force: true });
if (existsSync(extDist)) cpSync(extDist, downloads, { recursive: true });
else console.warn("plugins/browser-extension/dist is missing: /downloads will be empty (run `npm run extension`)");

// 2. pages ---------------------------------------------------------------------
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const icons = readFileSync(resolve(here, "src/icons.svg"), "utf8").trim();

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith(".html") ? [p] : [];
  });
}

const NAV = [
  ["agents", "/agents", "Agents"],
  ["workflows", "/workflows", "Workflows"],
  ["applications", "/applications", "Applications"],
  ["docs", "/docs", "Docs"],
  ["blog", "/blog", "Blog"],
  ["products", "/products", "Products"],
];

// Documentation sidebar: [section, [[path, title], ...]]. Order sets prev/next.
const DOCS = [
  ["Get started", [["/docs", "Introduction"], ["/docs/quickstart", "Quickstart"], ["/docs/install", "Install and deploy"]]],
  ["Core concepts", [["/docs/concepts", "How Smriti works"], ["/docs/knowledge", "Knowledge and sources"], ["/docs/security", "Security and access"]]],
  ["Build", [["/docs/agents", "Agents and tools"], ["/docs/workflows", "Workflows"], ["/docs/integrations", "Integrations"]]],
  ["Reference", [["/docs/api", "API, MCP and CLI"], ["/docs/faq", "FAQ and limits"]]],
];
const DOC_ORDER = DOCS.flatMap(([, items]) => items);

function docsLayout(meta, body) {
  const side = DOCS.map(
    ([section, items]) => `      <div class="dside-group"><p>${section}</p><ul>${items
      .map(([href, title]) => `<li><a href="${href}"${href === meta.path ? ' class="on" aria-current="page"' : ""}>${title}</a></li>`)
      .join("")}</ul></div>`,
  ).join("\n");
  const i = DOC_ORDER.findIndex(([href]) => href === meta.path);
  const prev = i > 0 ? DOC_ORDER[i - 1] : null;
  const next = i >= 0 && i < DOC_ORDER.length - 1 ? DOC_ORDER[i + 1] : null;
  const pn = `<nav class="dpn" aria-label="Previous and next">${prev ? `<a href="${prev[0]}"><span>Previous</span>${prev[1]}</a>` : "<span></span>"}${next ? `<a class="next" href="${next[0]}"><span>Next</span>${next[1]}</a>` : ""}</nav>`;
  const edit = meta.source ? `<p class="dedit"><a href="${SMRITI}/blob/main/${meta.source}">Full reference on GitHub →</a></p>` : "";
  return `<div class="wrap docs-grid">
    <aside class="dside" aria-label="Documentation">
      <a class="dside-home" href="/docs">Smriti docs</a>
${side}
    </aside>
    <article class="dmain prose">
${body}
      ${edit}
      ${pn}
    </article>
  </div>`;
}

function header(active) {
  const links = NAV.map(([key, href, label]) => {
    const cur = key === active ? ' class="active" aria-current="page"' : "";
    return `      <li><a href="${href}"${cur}>${label}</a></li>`;
  }).join("\n");
  return `<header class="top">
  <nav class="wrap nav" aria-label="Main">
    <a class="logo" href="/" aria-label="Safearly home">
      <img src="/assets/brand/safearly-mark.svg" alt="" width="30" height="30">safearly
    </a>
    <ul class="links" id="links">
${links}
    </ul>
    <a class="gh" href="${SMRITI}" aria-label="Smriti on GitHub" title="Smriti on GitHub"><svg aria-hidden="true"><use href="#i-github"/></svg></a>
    <a class="btn btn-primary" href="/docs/quickstart">Get started</a>
    <button class="menu" id="menu" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="links"><svg aria-hidden="true"><use href="#i-menu"/></svg></button>
  </nav>
</header>`;
}

const footer = `<footer class="foot2">
  <div class="wrap">
    <div class="foot2-grid five">
      <div>
        <a class="logo" href="/"><img src="/assets/brand/safearly-mark.svg" alt="" width="26" height="26">safearly</a>
        <p class="about">Smriti is open-source institutional memory: private AI agents and workflows that cite their sources and act as the person asking. Built by Safearly, makers of Saaf.</p>
      </div>
      <div>
        <h4>Smriti</h4>
        <ul>
          <li><a href="/">Overview</a></li>
          <li><a href="/agents">Agents</a></li>
          <li><a href="/workflows">Workflows</a></li>
          <li><a href="/applications">Applications</a></li>
          <li><a href="${SMRITI}">GitHub</a></li>
        </ul>
      </div>
      <div>
        <h4>Docs</h4>
        <ul>
          <li><a href="/docs/quickstart">Quickstart</a></li>
          <li><a href="/docs/install">Install and deploy</a></li>
          <li><a href="/docs/agents">Agents and tools</a></li>
          <li><a href="/docs/api">API reference</a></li>
          <li><a href="/docs/security">Security</a></li>
        </ul>
      </div>
      <div>
        <h4>More from Safearly</h4>
        <ul>
          <li><a href="/saaf">Saaf PII masking</a></li>
          <li><a href="/saaf/extension">Browser extension</a></li>
          <li><a href="/saaf/playground">Playground</a></li>
          <li><a href="/research">Research</a></li>
          <li><a href="/products">All products</a></li>
        </ul>
      </div>
      <div>
        <h4>Company</h4>
        <ul>
          <li><a href="/about">About</a></li>
          <li><a href="/blog">Blog</a></li>
          <li><a href="${LINKEDIN}">LinkedIn</a></li>
          <li><a href="mailto:${EMAIL}">${EMAIL}</a></li>
          <li><a href="/blog/feed.xml">RSS</a></li>
        </ul>
      </div>
    </div>
    <div class="foot2-legal">
      <span>© ${YEAR} Safearly · Smriti and Saaf are Apache-2.0 · Smriti (स्मृति) means “memory”</span>
      <span>No cookies. No trackers.</span>
    </div>
  </div>
</footer>`;

function render(meta, body) {
  const url = SITE + (meta.path === "/" ? "/" : meta.path);
  const og = SITE + (meta.ogImage ?? "/assets/brand/og-image.png");
  const css = ["/assets/styles.css", "/assets/lab.css", "/assets/smriti.css", ...(meta.css ?? [])]
    .map((h) => `  <link rel="stylesheet" href="${h}">`)
    .join("\n");
  const js = (meta.scripts ?? []).map((s) => `  <script type="module" src="${s}"></script>`).join("\n");
  const ogAlt = meta.ogImageAlt ? `\n  <meta property="og:image:alt" content="${esc(meta.ogImageAlt)}">` : "";
  const robots = meta.noindex ? '\n  <meta name="robots" content="noindex">' : "";
  return `<!doctype html>
<html lang="en" class="no-js">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${esc(meta.title)}</title>
  <meta name="description" content="${esc(meta.description)}">${robots}
  <link rel="canonical" href="${url}">
  <meta name="theme-color" content="#ffffff">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <link rel="alternate" type="application/rss+xml" title="Safearly blog" href="/blog/feed.xml">
  <meta property="og:type" content="${meta.ogType ?? "website"}">
  <meta property="og:site_name" content="Safearly">
  <meta property="og:title" content="${esc(meta.ogTitle ?? meta.title)}">
  <meta property="og:description" content="${esc(meta.description)}">
  <meta property="og:url" content="${url}">
  <meta property="og:image" content="${og}">${ogAlt}
  <meta name="twitter:card" content="summary_large_image">
${css}
${meta.head ? "  " + meta.head + "\n" : ""}${js}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
${icons}

${header(meta.nav)}

<main id="main"${meta.mainClass ? ` class="${meta.mainClass}"` : ""}>
${meta.docs ? docsLayout(meta, body) : body}
</main>

${footer}
</body>
</html>
`;
}

const pagesDir = resolve(here, "src/pages");
const pages = walk(pagesDir).map((file) => {
  const raw = readFileSync(file, "utf8").replaceAll("\r\n", "\n");
  const m = raw.match(/^<!--page (\{.*?\}) -->\n/s);
  if (!m) throw new Error(`${relative(here, file)}: missing <!--page {...} --> header`);
  return { file, meta: JSON.parse(m[1]), body: raw.slice(m[0].length).trimEnd() };
});

for (const { file, meta, body } of pages) {
  const out = resolve(here, relative(pagesDir, file));
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, render(meta, body.replaceAll("{{YEAR}}", String(YEAR))));
}

// 3. sitemap + feed ------------------------------------------------------------
const today = new Date().toISOString().slice(0, 10);
const listed = pages.filter((p) => !p.meta.noindex).sort((a, b) => a.meta.path.localeCompare(b.meta.path));
writeFileSync(
  resolve(here, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${listed
  .map((p) => `  <url><loc>${SITE}${p.meta.path === "/" ? "/" : p.meta.path}</loc><lastmod>${p.meta.post?.date ?? today}</lastmod></url>`)
  .join("\n")}
</urlset>
`,
);

const posts = pages.filter((p) => p.meta.post).sort((a, b) => b.meta.post.date.localeCompare(a.meta.post.date));
const rfc822 = (d) => new Date(`${d}T09:00:00+05:30`).toUTCString();
writeFileSync(
  resolve(here, "blog/feed.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Safearly blog</title>
    <link>${SITE}/blog</link>
    <atom:link href="${SITE}/blog/feed.xml" rel="self" type="application/rss+xml"/>
    <description>Essays, research notes and explainers on fast, safe AI in production.</description>
    <language>en-in</language>
${posts
  .map(
    (p) => `    <item>
      <title>${esc(p.meta.post.title)}</title>
      <link>${SITE}${p.meta.path}</link>
      <guid>${SITE}${p.meta.path}</guid>
      <pubDate>${rfc822(p.meta.post.date)}</pubDate>
      <category>${esc(p.meta.post.type)}</category>
      <description>${esc(p.meta.description)}</description>
    </item>`,
  )
  .join("\n")}
  </channel>
</rss>
`,
);

console.log(`built ${pages.length} pages, ${posts.length} posts, engine copied to ${relative(here, engineOut)}`);
