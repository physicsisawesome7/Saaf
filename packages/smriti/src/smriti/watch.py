"""Watch: site adapters, change detection, alerts and digests.

Government sites are mostly a reliability problem, not a scraping problem. A
source is a YAML adapter (``sources/*.yaml``); the crawler is polite by
default (robots.txt, an identifiable user agent, one request every two
seconds per host, conditional GET) and never bypasses CAPTCHAs or bot
protection. Change detection:

1. conditional GET (ETag, Last-Modified); 304 means stop
2. strip volatile parts (scripts, counters, session tokens) and hash the listing
3. unchanged hash means stop; otherwise extract and fingerprint each item
4. diff against the last snapshot: new, changed, removed
5. download, hash, sniff, scan and ingest new or changed files (immutable, versioned)
6. write a "what changed" note citing the new files, with circular-impact analysis
7. route alerts by role and scope, and audit every fetch and decision

A listing that suddenly yields zero items raises a repair alert with a
proposed selector for a human to approve, instead of silently going quiet.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.robotparser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from .access import evaluate
from .config import SourceConfig
from .engine import Tenant
from .models import Principal
from .store import alerts, jobs, source_state

USER_AGENT = "SmritiBot/0.1 (+https://safearly.com/smriti/bot; institutional-memory crawler)"
VOLATILE_PARAMS = re.compile(
    r"^(jsessionid|phpsessid|sid|sessionid|session|token|_ts|ts|timestamp|cache|rnd|utm_.*)$", re.I
)
VOLATILE_TEXT = [
    re.compile(r"(visitors?|hits?|page views?)\s*(count|counter)?\s*[:#]?\s*[\d,]+", re.I),
    re.compile(r"(last\s+(updated|refreshed|visited)|generated\s+(at|on)|server\s+time)\s*[:\-]?\s*[^<\n]{4,40}", re.I),
    re.compile(r"__VIEWSTATE[^\"]*\"[^\"]*\"|__EVENTVALIDATION[^\"]*\"[^\"]*\"", re.I),
    re.compile(r"\b[a-f0-9]{24,}\b", re.I),
]
DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "zip", "csv", "html", "htm", "md", "txt", "eml"}


def normalise_url(url: str) -> str:
    s = urlsplit(url.strip())
    q = sorted((k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if not VOLATILE_PARAMS.match(k))
    path = re.sub(r";jsessionid=[^/?#]*", "", s.path, flags=re.I) or "/"
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, urlencode(q), ""))


def _sha(b: bytes | str) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


class HostPolicy:
    """Per-host politeness: rate limit, robots.txt and a circuit breaker."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last.get(host, 0) + min_interval - now
            self._last[host] = max(now, self._last.get(host, 0) + min_interval)
        if delay > 0:
            time.sleep(delay)

    def allowed(self, client: httpx.Client, url: str) -> bool:
        s = urlsplit(url)
        base = f"{s.scheme}://{s.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = client.get(base + "/robots.txt", timeout=10)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[base] = rp
            except httpx.HTTPError:
                self._robots[base] = None  # unreachable robots.txt: allowed, as per RFC 9309
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def open(self, host: str) -> bool:
        recent = [t for t in self._fails.get(host, []) if time.time() - t < 900]
        self._fails[host] = recent
        return len(recent) < 5

    def fail(self, host: str) -> None:
        self._fails.setdefault(host, []).append(time.time())


_hosts = HostPolicy()


def _rate(spec: str | None) -> float:
    if not spec:
        return 2.0
    m = re.match(r"\s*(\d+)\s*requests?\s*per\s*([\d.]+)?\s*(s|sec|second|m|min|minute)", spec, re.I)
    if not m:
        return 2.0
    n, per, unit = int(m.group(1)), float(m.group(2) or 1), m.group(3).lower()
    return per * (60 if unit.startswith("m") else 1) / max(n, 1)


class Crawler:
    def __init__(self, t: Tenant, src: SourceConfig, client: httpx.Client | None = None):
        self.t = t
        self.src = src
        fetch = src.fetch or {}
        self.min_interval = _rate(fetch.get("rate_limit"))
        self.respect_robots = fetch.get("respect_robots", True)
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=fetch.get("timeout_s", 30),
            follow_redirects=True,
            verify=fetch.get("verify_tls", True),
        )

    def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        host = urlsplit(url).netloc
        if not _hosts.open(host):
            raise RuntimeError(f"circuit open for {host}: too many recent failures")
        if self.respect_robots and not _hosts.allowed(self.client, url):
            raise PermissionError(f"robots.txt disallows {url}")
        last: Exception | None = None
        for attempt in range(3):
            _hosts.wait(host, self.min_interval)
            try:
                r = self.client.get(url, headers=headers or {})
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                return r
            except httpx.HTTPError as e:
                last = e
                _hosts.fail(host)
                time.sleep(min(8, 0.5 * 2**attempt))
        raise RuntimeError(f"fetch failed for {url}: {last}")

    # ---------------------------------------------------------------- listing

    def listing(self, state: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]], dict[str, str]]:
        """Returns (normalised listing hash or None if 304, items, validators)."""
        mode = self.src.mode
        if mode == "file":
            return self._file_listing()
        pages: list[str] = []
        validators: dict[str, str] = {}
        items: list[dict[str, Any]] = []
        for start in self.src.start_urls:
            url: str | None = start
            n = 0
            max_pages = int((self.src.discover.get("pagination") or {}).get("max_pages", 1))
            while url and n < max_pages:
                hdrs = {}
                if n == 0 and (self.src.fetch or {}).get("conditional_get", True):
                    if state.get("etag"):
                        hdrs["If-None-Match"] = state["etag"]
                    if state.get("last_modified"):
                        hdrs["If-Modified-Since"] = state["last_modified"]
                r = self.get(url, hdrs)
                if r.status_code == 304:
                    return None, [], validators
                r.raise_for_status()
                if n == 0:
                    validators = {
                        k: v
                        for k, v in (("etag", r.headers.get("etag")), ("last_modified", r.headers.get("last-modified")))
                        if v
                    }
                html = self._render(url, r.text) if mode == "playwright" else r.text
                if mode == "rss" or "<rss" in html[:500] or "<feed" in html[:500]:
                    items += self._rss(html, url)
                else:
                    items += self._extract(html, url)
                pages.append(self._normalise(html))
                url = self._next(html, url)
                n += 1
        return _sha("\n".join(pages)), items, validators

    def _render(self, url: str, fallback: str) -> str:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "mode 'playwright' needs `pip install smriti[browser]` and `playwright install chromium`"
            ) from e
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle")
            for step in self.src.discover.get("recipe") or []:
                if "click" in step:
                    page.click(step["click"])
                if "wait_for" in step:
                    page.wait_for_selector(step["wait_for"])
            html = page.content()
            b.close()
        return html or fallback

    def _normalise(self, html: str) -> str:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "noscript", "iframe"]):
            t.decompose()
        for sel in (self.src.volatile or {}).get("selectors", []):
            for el in soup.select(sel):
                el.decompose()
        text = soup.get_text(" ", strip=True)
        for pat in VOLATILE_TEXT + [re.compile(p, re.I) for p in (self.src.volatile or {}).get("patterns", [])]:
            text = pat.sub(" ", text)
        return re.sub(r"\s+", " ", text)

    def _extract(self, html: str, base: str) -> list[dict[str, Any]]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        d = self.src.discover
        sel = d.get("list_selector")
        fields = d.get("fields") or {}
        out = []
        if not sel:  # no adapter: every document link on the page is an item
            for a in soup.select("a[href]"):
                href = urljoin(base, a["href"])
                if href.rsplit(".", 1)[-1].lower() in DOC_EXT:
                    out.append({"title": a.get_text(" ", strip=True) or href, "file": href, "issued_on": None})
            return out
        for row in soup.select(sel):
            item: dict[str, Any] = {}
            for name, spec in fields.items():
                css, _, attr = str(spec).partition("@")
                el = row.select_one(css) if css else row
                if el is None:
                    item[name] = None
                elif attr:
                    v = el.get(attr)
                    item[name] = urljoin(base, v) if v and attr in ("href", "src") else v
                else:
                    item[name] = el.get_text(" ", strip=True)
            if any(item.values()):
                out.append(item)
        return out

    def _rss(self, xml: str, base: str) -> list[dict[str, Any]]:
        import xml.etree.ElementTree as ET  # feed XML from an allow-listed source, no DTDs

        out = []
        try:
            root = ET.fromstring(xml)  # noqa: S314
        except ET.ParseError:
            return out
        for it in root.iter():
            tag = it.tag.rsplit("}", 1)[-1]
            if tag not in ("item", "entry"):
                continue
            g = {c.tag.rsplit("}", 1)[-1]: (c.text or c.get("href") or "") for c in it}
            out.append(
                {
                    "title": g.get("title"),
                    "file": urljoin(base, g.get("link", "")),
                    "issued_on": g.get("pubDate") or g.get("updated"),
                }
            )
        return out

    def _next(self, html: str, base: str) -> str | None:
        p = self.src.discover.get("pagination") or {}
        if p.get("type") != "next_link":
            return None
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        el = soup.select_one(p.get("selector", "a[rel=next]"))
        return urljoin(base, el["href"]) if el and el.get("href") else None

    def _file_listing(self) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
        root = self.t.pack.resolve(self.src.path or "") if self.src.path else None
        if not root or not root.is_dir():
            raise FileNotFoundError(f"source path not found: {self.src.path}")
        items = []
        for f in sorted(p for p in root.rglob("*") if p.is_file() and not p.name.endswith(".meta.yaml")):
            data = f.read_bytes()
            items.append(
                {
                    "title": f.stem.replace("-", " ").replace("_", " "),
                    "file": f.as_uri(),
                    "path": str(f),
                    "issued_on": None,
                    "sha": _sha(data),
                }
            )
        return _sha(json.dumps([(i["file"], i["sha"]) for i in items])), items, {}

    def download(self, item: dict[str, Any]) -> tuple[bytes, str]:
        if item.get("path"):
            p = Path(item["path"])
            return p.read_bytes(), p.name
        url = item["file"]
        r = self.get(url)
        r.raise_for_status()
        limit = int((self.src.documents or {}).get("max_size_mb", 100)) * 1024 * 1024
        if len(r.content) > limit:
            raise ValueError(f"{url}: larger than the source's max_size_mb")
        name = urlsplit(url).path.rsplit("/", 1)[-1] or "index.html"
        return r.content, name


# ---------------------------------------------------------------- runner


def _fingerprint(item: dict[str, Any]) -> tuple[str, str]:
    key = normalise_url(item["file"]) if item.get("file") else _sha(item.get("title") or "")
    fp = _sha(json.dumps([item.get("title"), item.get("issued_on"), key, item.get("sha")], ensure_ascii=False))
    return key, fp


def run_source(t: Tenant, name: str, actor: str = "watcher", client: httpx.Client | None = None) -> dict[str, Any]:
    src = next((s for s in t.pack.sources if s.source == name), None)
    if not src:
        raise KeyError(name)
    st = (t.store.rows(source_state, tenant=t.id, source=name) or [None])[0]
    if st is None:
        t.store.insert(
            source_state, tenant=t.id, source=name, snapshot="{}", runs=0, failures=0, consecutive_failures=0
        )
        st = t.store.rows(source_state, tenant=t.id, source=name)[0]
    snapshot: dict[str, str] = json.loads(st.get("snapshot") or "{}")
    report: dict[str, Any] = {
        "source": name,
        "new": [],
        "changed": [],
        "removed": [],
        "errors": [],
        "unchanged": False,
        "impact": [],
    }
    crawler = Crawler(t, src, client)
    now = time.time()
    try:
        listing_hash, items, validators = crawler.listing(st)
        t.audit.record(
            actor,
            "fetch_listing",
            source=name,
            urls=src.start_urls or [src.path],
            not_modified=listing_hash is None,
            items=len(items),
        )
        if listing_hash is None or (listing_hash == st.get("listing_hash") and snapshot):
            report["unchanged"] = True
            t.store.update_row(
                source_state,
                {"tenant": t.id, "source": name},
                last_run=now,
                last_success=now,
                runs=(st["runs"] or 0) + 1,
                consecutive_failures=0,
                last_error=None,
                adapter_version=src.adapter_version,
                **validators,
            )
            return report
        if not items and snapshot:
            _repair_alert(t, src, crawler)
            raise RuntimeError(
                "listing returned zero items where it used to return some: selectors probably broke after a layout change"
            )

        current: dict[str, tuple[str, dict[str, Any]]] = {}
        for it in items:
            key, fp = _fingerprint(it)
            current[key] = (fp, it)
        allowed_types = set((src.documents or {}).get("types", DOC_EXT))
        for key, (fp, it) in current.items():
            kind = "new" if key not in snapshot else ("changed" if snapshot[key] != fp else None)
            if not kind:
                continue
            if not it.get("file"):
                continue
            ext = it["file"].rsplit(".", 1)[-1].lower().split("?")[0]
            if ext not in allowed_types and not it.get("path"):
                continue
            try:
                data, fname = crawler.download(it)
                hints: dict[str, Any] = {"access": src.access or {}}
                if it.get("title"):
                    hints["title"] = it["title"]
                if (src.classify or {}).get("doc_type"):
                    hints["doc_type"] = src.classify["doc_type"]
                if it.get("issued_on"):
                    from .metadata import to_iso

                    if d := to_iso(str(it["issued_on"])):
                        hints["date"] = d
                res = t.ingest(
                    data,
                    fname,
                    actor=actor,
                    source=name,
                    source_url=it["file"] if not it.get("path") else None,
                    hints=hints,
                    legal_status=src.legal_status,
                )
                if res["status"] == "duplicate":
                    continue
                entry = {
                    "title": res.get("title"),
                    "doc_id": res["doc_id"],
                    "version": res["version"],
                    "url": it["file"],
                    "impact": res.get("impact", []),
                }
                report[kind].append(entry)
                report["impact"] += res.get("impact", [])
            except Exception as e:  # one bad file never blocks the rest of the source
                report["errors"].append({"url": it.get("file"), "error": str(e)[:300]})
                t.store.insert(
                    jobs,
                    tenant=t.id,
                    kind="download",
                    payload=json.dumps({"source": name, "item": it}),
                    status="dead",
                    attempts=1,
                    last_error=str(e)[:500],
                    created_at=now,
                    updated_at=now,
                )
        for key in set(snapshot) - set(current):
            report["removed"].append({"key": key})
        new_snapshot = {k: v[0] for k, v in current.items()}
        t.store.update_row(
            source_state,
            {"tenant": t.id, "source": name},
            snapshot=json.dumps(new_snapshot),
            listing_hash=listing_hash,
            last_run=now,
            last_success=now,
            runs=(st["runs"] or 0) + 1,
            consecutive_failures=0,
            last_error=None,
            adapter_version=src.adapter_version,
            **validators,
        )
        _alerts(t, src, report)
        return report
    except Exception as e:
        t.store.update_row(
            source_state,
            {"tenant": t.id, "source": name},
            last_run=now,
            last_error=str(e)[:500],
            runs=(st["runs"] or 0) + 1,
            failures=(st["failures"] or 0) + 1,
            consecutive_failures=(st["consecutive_failures"] or 0) + 1,
        )
        t.audit.record(actor, "fetch_failed", source=name, error=str(e)[:300])
        report["errors"].append({"error": str(e)[:300]})
        return report


def _repair_alert(t: Tenant, src: SourceConfig, crawler: Crawler) -> None:
    proposal = "table tr  (rows that contain a document link)"
    if t.gw.available("extract") and src.start_urls:
        try:
            html = crawler.get(src.start_urls[0]).text[:6000]
            proposal = t.gw.complete(
                "extract",
                [
                    {
                        "role": "system",
                        "content": "Propose one CSS selector that matches each row of the document listing. Reply with the selector only.",
                    },
                    {"role": "user", "content": html},
                ],
                max_tokens=40,
            ).strip()
        except Exception:  # noqa: S110 - a failed proposal still leaves the alert for a human
            pass
    t.store.insert(
        alerts,
        tenant=t.id,
        source=src.source,
        kind="repair",
        title=f"Adapter '{src.source}' v{src.adapter_version} needs repair",
        body=f"The listing returned no items. Proposed list_selector for review: {proposal}. Approving it bumps adapter_version.",
        doc_ids="[]",
        roles=json.dumps(["knowledge-manager", "org-admin"]),
        impact="[]",
        created_at=time.time(),
    )


def _alerts(t: Tenant, src: SourceConfig, report: dict[str, Any]) -> None:
    roles = (src.alert or {}).get("to", [])
    when = set((src.alert or {}).get("when", ["new", "changed"]))
    for kind in ("new", "changed"):
        if kind not in when:
            continue
        for e in report[kind]:
            body = what_changed_note(t, e["doc_id"], kind)
            t.store.insert(
                alerts,
                tenant=t.id,
                source=src.source,
                kind=kind,
                title=e["title"],
                body=body,
                doc_ids=json.dumps([e["doc_id"]]),
                roles=json.dumps(roles),
                impact=json.dumps(e.get("impact", []), default=str),
                created_at=time.time(),
            )
    if "removed" in when:
        for e in report["removed"]:
            t.store.insert(
                alerts,
                tenant=t.id,
                source=src.source,
                kind="removed",
                title="Document removed from source",
                body=f"No longer listed: {e['key']}. The archived copy is kept.",
                doc_ids="[]",
                roles=json.dumps(roles),
                impact="[]",
                created_at=time.time(),
            )


def what_changed_note(t: Tenant, doc_id: str, kind: str) -> str:
    d = t.store.get_document(t.id, doc_id)
    if not d:
        return ""
    chunks = t.store.doc_chunks(t.id, doc_id)
    lead = next(
        (c["text_masked"] for c in chunks if len(c["text_masked"]) > 60), chunks[0]["text_masked"] if chunks else ""
    )
    rels = [
        r
        for r in t.store.relations_for(t.id, doc_id)
        if r["src_doc"] == doc_id and r["rel_type"] in ("modifies", "supersedes")
    ]
    parts = [
        f"{'New' if kind == 'new' else 'Revised'}: {d['title']}"
        + (f" ({d['ref_no']})" if d.get("ref_no") else "")
        + (f", dated {d['doc_date']}" if d.get("doc_date") else "")
        + "."
    ]
    for r in rels:
        tgt = t.store.get_document(t.id, r["dst_doc"]) if r["dst_doc"] else None
        what = f"clause {r['clause_id']} of " if r["clause_id"] else ""
        parts.append(
            f"It {r['rel_type'].rstrip('s')}s {what}{tgt['title'] if tgt else r['dst_ref']}"
            + (f" with effect from {r['effective_from']}." if r["effective_from"] else ".")
        )
    if kind == "changed":
        vs = t.store.get_versions(t.id, doc_id)
        if len(vs) >= 2:
            parts.append(
                f"Now at version {vs[-1]['version']}; the file at the same address was replaced. Both versions are kept."
            )
    if t.gw.available("chat"):
        try:
            return t.gw.complete(
                "chat",
                [
                    {
                        "role": "system",
                        "content": "Write a two-sentence 'what changed' note for officers. Use only the facts given. No speculation.",
                    },
                    {"role": "user", "content": "\n".join(parts) + "\n\nOpening text:\n" + lead[:1500]},
                ],
                max_tokens=160,
            ).strip()
        except Exception:  # noqa: S110 - fall back to the deterministic note
            pass
    parts.append("Opening text: " + (lead[:280] + ("…" if len(lead) > 280 else "")))
    return " ".join(parts)


def visible_alerts(t: Tenant, p: Principal, limit: int = 50) -> list[dict[str, Any]]:
    """Alerts routed by role and filtered by scope: each reader sees only
    alerts about documents they may open, and only the impacted documents
    they may open."""
    out = []
    docs_cache: dict[str, dict[str, Any] | None] = {}
    for a in t.store.rows(alerts, order_by="id", limit=500, tenant=t.id):
        roles = json.loads(a["roles"] or "[]")
        if roles and not set(roles) & set(p.roles):
            continue
        ids = json.loads(a["doc_ids"] or "[]")
        ok = True
        for i in ids:
            if i not in docs_cache:
                docs_cache[i] = t.store.get_document(t.id, i)
            d = docs_cache[i]
            if not d or not evaluate(p, d["access"], d["doc_type"]).allowed:
                ok = False
        if not ok:
            continue
        impact = [x for x in json.loads(a["impact"] or "[]") if evaluate(p, x["access"], x["doc_type"]).allowed]
        for x in impact:
            x.pop("access", None)
        out.append(
            {
                **a,
                "doc_ids": ids,
                "roles": roles,
                "impact": impact,
                "created": datetime.fromtimestamp(a["created_at"]).isoformat(timespec="minutes"),
            }
        )
        if len(out) >= limit:
            break
    return out


def source_health(t: Tenant) -> list[dict[str, Any]]:
    states = {s["source"]: s for s in t.store.rows(source_state, tenant=t.id)}
    out = []
    for src in t.pack.sources:
        s = states.get(src.source, {})
        runs = s.get("runs") or 0
        out.append(
            {
                "source": src.source,
                "mode": src.mode,
                "schedule": src.schedule,
                "adapter_version": src.adapter_version,
                "legal_status": src.legal_status,
                "start": src.start_urls[0] if src.start_urls else src.path,
                "last_run": s.get("last_run"),
                "last_success": s.get("last_success"),
                "last_error": s.get("last_error"),
                "error_rate": round((s.get("failures") or 0) / runs, 2) if runs else None,
                "items_tracked": len(json.loads(s.get("snapshot") or "{}")),
                "healthy": bool(s.get("last_success")) and not s.get("consecutive_failures"),
            }
        )
    return out


# ---------------------------------------------------------------- scheduler


def cron_match(expr: str, dt: datetime) -> bool:
    """Minimal five-field cron: '*', '*/n', 'a-b', 'a,b,c'."""
    fields = expr.split()
    if len(fields) != 5:
        return False
    vals = [dt.minute, dt.hour, dt.day, dt.month, (dt.isoweekday() % 7)]
    for f, v in zip(fields, vals, strict=True):
        ok = False
        for part in f.split(","):
            step = 1
            if "/" in part:
                part, s = part.split("/")
                step = int(s)
            if part == "*":
                lo, hi = 0, 59
            elif "-" in part:
                lo, hi = map(int, part.split("-"))
            else:
                lo = hi = int(part)
            if lo <= v <= hi and (v - lo) % step == 0:
                ok = True
        if not ok:
            return False
    return True


class Scheduler(threading.Thread):
    """Fires sources on their cron schedule. Production runs the same
    ``run_source`` inside Temporal workflows for durable retries; this thread
    is the single-server appliance equivalent."""

    def __init__(self, tenants: dict[str, Tenant]):
        super().__init__(daemon=True, name="smriti-scheduler")
        self.tenants = tenants
        self._stop = threading.Event()
        self._fired: set[str] = set()

    def run(self) -> None:
        while not self._stop.wait(20):
            now = datetime.now().replace(second=0, microsecond=0)
            for t in self.tenants.values():
                for src in t.pack.sources:
                    key = f"{t.id}|{src.source}|{now.isoformat()}"
                    if src.schedule and key not in self._fired and cron_match(src.schedule, now):
                        self._fired.add(key)
                        try:
                            run_source(t, src.source)
                        except Exception:  # noqa: S112 - a failed site never blocks the others
                            continue
            if len(self._fired) > 10000:
                self._fired.clear()

    def stop(self) -> None:
        self._stop.set()
