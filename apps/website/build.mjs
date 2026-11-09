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
const LINKEDIN_CO = "https://www.linkedin.com/company/safeary.ai/";
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
  ["products", "/products", "Products"],
  ["agents", "/agents", "Agents"],
  ["workflows", "/workflows", "Workflows"],
  ["applications", "/applications", "Applications"],
  ["docs", "/docs", "Docs"],
  ["blog", "/blog", "Blog"],
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
          <li><a href="${LINKEDIN_CO}">Safearly on LinkedIn</a></li>
          <li><a href="${SMRITI}">Smriti on GitHub</a></li>
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
  const slug = meta.path.split("/").pop();
  const postOg = meta.post && existsSync(resolve(here, `assets/og/${slug}.png`)) ? `/assets/og/${slug}.png` : null;
  const og = SITE + (meta.ogImage ?? postOg ?? "/assets/brand/og-image.png");
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
  <link rel="preload" href="/assets/fonts/inter-latin-wght-normal.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="alternate" type="application/rss+xml" title="Safearly blog" href="/blog/feed.xml">
  <meta property="og:type" content="${meta.ogType ?? "website"}">
  <meta property="og:site_name" content="Safearly">
  <meta property="og:title" content="${esc(meta.ogTitle ?? meta.title)}">
  <meta property="og:description" content="${esc(meta.description)}">
  <meta property="og:url" content="${url}">
  <meta property="og:image" content="${og}">${ogAlt}${meta.post ? `
  <meta property="article:published_time" content="${meta.post.date}">
  <meta property="article:author" content="Lalit Shukla">
  <meta property="article:section" content="${esc(meta.post.type)}">
  <script type="application/ld+json">${JSON.stringify({
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: meta.post.title,
    description: meta.description,
    datePublished: meta.post.date,
    author: { "@type": "Person", name: "Lalit Shukla", url: `${SITE}/about` },
    publisher: { "@type": "Organization", name: "Safearly", url: SITE, email: EMAIL, sameAs: [LINKEDIN_CO, SMRITI], logo: { "@type": "ImageObject", url: `${SITE}/assets/brand/safearly-mark-512.png` } },
    image: og,
    mainEntityOfPage: url,
  }).replaceAll("<", "\\u003c")}</script>` : ""}
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

const posts = pages
  .filter((p) => p.meta.post)
  .sort((a, b) => b.meta.post.date.localeCompare(a.meta.post.date) || (b.meta.post.featured ? 1 : 0) - (a.meta.post.featured ? 1 : 0));
const fmtDate = (d) => new Date(`${d}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const plain = (html) =>
  html
    .replace(/<(script|style|svg)[\s\S]*?<\/\1>/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
const minutes = (html) => Math.max(1, Math.round(plain(html).split(" ").length / 220));
const TYPES = [...new Set(posts.map((p) => p.meta.post.type))];

function postChips() {
  const btn = (t, n, on) =>
    `<button type="button" class="chip-link${on ? " on" : ""}" data-filter="${esc(t)}" aria-pressed="${on}">${esc(t === "*" ? "All" : t)} · ${n}</button>`;
  return `<div class="chips-row" role="group" aria-label="Filter posts">${btn("*", posts.length, true)}${TYPES.map((t) => btn(t, posts.filter((p) => p.meta.post.type === t).length, false)).join("")}</div>`;
}
function postList() {
  const [first, ...rest] = posts;
  const f = first.meta;
  return `      <a class="post-feature" href="${f.path}" data-type="${esc(f.post.type)}">
        <span class="meta">${fmtDate(f.post.date)} · ${esc(f.post.type)} · ${minutes(first.body)} min read</span>
        <h2>${esc(f.post.title)}</h2>
        <p>${esc(f.post.dek ?? f.description)}</p>
        <span class="more">Read →</span>
      </a>
      <div class="post-list">
${rest
  .map(
    (p) => `        <a class="post-row" href="${p.meta.path}" data-type="${esc(p.meta.post.type)}">
          <span class="meta">${fmtDate(p.meta.post.date)} · ${esc(p.meta.post.type)} · ${minutes(p.body)} min</span>
          <div><h3>${esc(p.meta.post.title)}</h3><p>${esc(p.meta.post.dek ?? p.meta.description)}</p></div>
        </a>`,
  )
  .join("\n")}
      </div>`;
}
function latestPosts(n = 3) {
  return `<div class="posts3">${posts
    .slice(0, n)
    .map(
      (p) =>
        `<a class="post-card reveal" href="${p.meta.path}"><span class="meta">${fmtDate(p.meta.post.date)} · ${esc(p.meta.post.type)} · ${minutes(p.body)} min</span><h3>${esc(p.meta.post.title)}</h3><p>${esc(p.meta.post.dek ?? p.meta.description)}</p><span class="more">Read →</span></a>`,
    )
    .join("")}</div>`;
}
function postTools(meta, body) {
  const url = encodeURIComponent(`${SITE}${meta.path}`);
  const title = encodeURIComponent(meta.post.title);
  const share = `<div class="post-tools"><span>Share</span>
          <a href="https://www.linkedin.com/sharing/share-offsite/?url=${url}" rel="noopener" target="_blank">LinkedIn</a>
          <a href="https://twitter.com/intent/tweet?url=${url}&amp;text=${title}" rel="noopener" target="_blank">X</a>
          <a href="https://news.ycombinator.com/submitlink?u=${url}&amp;t=${title}" rel="noopener" target="_blank">Hacker News</a>
          <a href="https://www.reddit.com/submit?url=${url}&amp;title=${title}" rel="noopener" target="_blank">Reddit</a>
          <a href="mailto:?subject=${title}&amp;body=${url}">Email</a>
          <a href="/blog/feed.xml">RSS</a></div>`;
  let out = body.replace(/(<div class="meta">[^<]*· [^<]*?)(<\/div>)/, `$1 · ${minutes(body)} min read$2`);
  out = out.includes('<div class="related">')
    ? out.replace('<div class="related">', `${share}\n        <div class="related">`)
    : out.replace("</article>", `${share}\n    </article>`);
  return out;
}

for (const { file, meta, body } of pages) {
  const out = resolve(here, relative(pagesDir, file));
  mkdirSync(dirname(out), { recursive: true });
  let html = body
    .replaceAll("{{YEAR}}", String(YEAR))
    .replace("<!--POST_CHIPS-->", () => postChips())
    .replace("<!--POST_LIST-->", () => postList())
    .replace("<!--LATEST_POSTS-->", () => latestPosts(3))
    .replace(/<!--FIG:([a-z0-9-]+)-->/g, (_, name) => readFileSync(resolve(here, `src/figures/${name}.svg`), "utf8").trim());
  if (meta.post) html = postTools(meta, html);
  writeFileSync(out, render(meta, html));
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

// 4. files for search engines and AI assistants --------------------------------
const line = (p) => `- [${p.meta.post?.title ?? p.meta.ogTitle ?? p.meta.title.split(" · ")[0]}](${SITE}${p.meta.path === "/" ? "/" : p.meta.path}): ${p.meta.description}`;
const find = (hrefs) => hrefs.map((h) => pages.find((p) => p.meta.path === h)).filter(Boolean);
const docsPages = find(DOC_ORDER.map(([href]) => href));
writeFileSync(
  resolve(here, "llms.txt"),
  `# Smriti by Safearly

> Smriti is open-source (Apache-2.0) institutional memory: private AI agents and workflows over an organisation's documents, sites, APIs and databases. Answers cite their sources and are checked sentence by sentence. Every agent, workflow, widget and chat bot acts as the person asking. Personal data is masked before any model. It runs on your own hardware, with one GPU or none. Safearly also makes Saaf, an open-source PII masking engine for LLM traffic.

Source code: ${SMRITI}
Saaf: ${REPO}
Contact: ${EMAIL}

## Product
${find(["/", "/agents", "/workflows", "/applications", "/products"]).map(line).join("\n")}

## Docs
${docsPages.map(line).join("\n")}

## Blog
${posts.map(line).join("\n")}

## Optional
${find(["/saaf", "/saaf/extension", "/saaf/playground", "/research", "/about"]).map(line).join("\n")}
- [Full text of the product pages, docs and blog](${SITE}/llms-full.txt)
- [RSS feed](${SITE}/blog/feed.xml)
`,
);
const fullDoc = (p) =>
  `# ${p.meta.post?.title ?? p.meta.ogTitle ?? p.meta.title}\nURL: ${SITE}${p.meta.path === "/" ? "/" : p.meta.path}${p.meta.post ? `\nPublished: ${p.meta.post.date}` : ""}\n\n${plain(p.body)}\n`;
writeFileSync(
  resolve(here, "llms-full.txt"),
  `# Smriti by Safearly: full text of the product pages, docs and blog\n# Generated ${today} from ${SITE}\n\n` +
    [...find(["/", "/agents", "/workflows", "/applications"]), ...docsPages, ...posts].map(fullDoc).join("\n---\n\n"),
);
writeFileSync(
  resolve(here, "robots.txt"),
  `# safearly.com: everything public may be crawled and indexed, including by AI assistants.
# A guide to the site for language models: ${SITE}/llms.txt
User-agent: *
Allow: /
Disallow: /downloads/

User-agent: GPTBot
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Claude-User
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Applebot-Extended
Allow: /

Sitemap: ${SITE}/sitemap.xml
`,
);
writeFileSync(
  resolve(here, "humans.txt"),
  `/* TEAM */
Founder and head of product: Lalit Shukla
Contact: ${EMAIL}
LinkedIn: ${LINKEDIN}
Company: Safearly (${LINKEDIN_CO})
Code: ${SMRITI}

/* SITE */
Last update: ${today}
Standards: HTML5, CSS, no cookies, no trackers
Fonts: Inter and JetBrains Mono (SIL Open Font License)
Source: ${SMRITI}
`,
);

console.log(`built ${pages.length} pages, ${posts.length} posts, engine copied to ${relative(here, engineOut)}`);
