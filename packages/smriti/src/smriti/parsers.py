"""Parser router: every file becomes the same canonical list of blocks.

The router sniffs the real type from the bytes (not the extension), picks the
parser, and scores each block's confidence. Low-confidence pages stay
searchable but are labelled as such in answers and land in the review queue.

Built-in parsers are pure-Python and permissively licensed (pypdf, python-docx,
openpyxl, BeautifulSoup). Heavier engines plug in through ``EXTERNAL_PARSERS``:
Docling for layout-aware PDFs, PaddleOCR-VL or Granite-Docling for scans,
Whisper or IndicConformer for audio. PyMuPDF is deliberately avoided (AGPL).
"""

from __future__ import annotations

import csv
import email
import email.policy
import io
import re
import zipfile
from collections.abc import Callable

from .models import Block, ParsedDocument

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
CLAUSE_HEAD = re.compile(r"^(?:clause\s+)?(\d{1,3}(?:\.\d{1,3}){0,3})[.)]?\s+\S", re.IGNORECASE)

# name -> callable(data, filename) -> ParsedDocument ; registered by optional integrations
EXTERNAL_PARSERS: dict[str, Callable[[bytes, str], ParsedDocument]] = {}

COMMON_EN = set(
    "the of and to in a is for be by on with as shall this that or from are at it an not which will any all have has "
    "been such under per date no letter contract clause railway board tender work works officer section other may "
    "of its should above below para vide copy subject sub ref dated".split()
)


def detect_lang(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    dev = sum(1 for c in letters if DEVANAGARI.match(c))
    return "hi" if dev / len(letters) > 0.3 else "en"


def garble_score(text: str) -> float:
    """0 = clean, 1 = garbage. Catches legacy non-Unicode Hindi fonts (Kruti Dev
    style text extracted as Latin junk) and broken encodings."""
    if len(text) < 80:
        return 0.0
    bad = sum(1 for c in text if c == "�" or 0xE000 <= ord(c) <= 0xF8FF or (ord(c) < 32 and c not in "\n\t\r"))
    tokens = re.findall(r"[A-Za-z]{2,}", text)
    if DEVANAGARI.search(text) or len(tokens) < 15:
        return min(1.0, bad / max(len(text), 1) * 20)
    known = sum(1 for t in tokens if t.lower() in COMMON_EN)
    dict_ratio = known / len(tokens)
    return min(1.0, bad / len(text) * 20 + max(0.0, 0.12 - dict_ratio) * 6)


def sniff(data: bytes, filename: str) -> str:
    head = data[:2048].lstrip()
    name = filename.lower()
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"PK"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "application/octet-stream"
        if "word/document.xml" in names:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if any(n.startswith("xl/") for n in names):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    low = head[:512].lower()
    if low.startswith((b"<!doctype html", b"<html")) or b"<body" in low or name.endswith((".html", ".htm")):
        return "text/html"
    if name.endswith(".eml") or (b"\nsubject:" in b"\n" + low and b"\nfrom:" in b"\n" + low):
        return "message/rfc822"
    if name.endswith(".csv"):
        return "text/csv"
    if name.endswith((".md", ".markdown")):
        return "text/markdown"
    try:
        data[:4096].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def parse(data: bytes, filename: str) -> ParsedDocument:
    mime = sniff(data, filename)
    for name, fn in EXTERNAL_PARSERS.items():
        try:
            doc = fn(data, filename)
            if doc is not None:
                doc.parser = name
                return doc
        except Exception:  # noqa: S112 - an optional parser failing must fall back, never break ingest
            continue
    if mime == "application/pdf":
        doc = _pdf(data, filename)
    elif mime.endswith("wordprocessingml.document"):
        doc = _docx(data, filename)
    elif mime.endswith("spreadsheetml.sheet"):
        doc = _xlsx(data, filename)
    elif mime == "text/html":
        doc = _html(data.decode("utf-8", errors="replace"), filename)
    elif mime == "message/rfc822":
        doc = _eml(data, filename)
    elif mime == "text/csv":
        doc = _csv(data.decode("utf-8-sig", errors="replace"), filename)
    elif mime in ("text/markdown", "text/plain"):
        doc = _markdown(data.decode("utf-8-sig", errors="replace"), filename)
    else:
        raise ValueError(f"unsupported file type {mime} for {filename}")
    doc.mime = mime
    _score(doc)
    return doc


def _score(doc: ParsedDocument) -> None:
    for i, b in enumerate(doc.blocks):
        b.order = i
        b.lang = detect_lang(b.text)
        g = garble_score(b.text)
        if g > 0.5:
            b.confidence = min(b.confidence, 1 - g)
    if doc.low_confidence:
        doc.warnings.append("low-confidence blocks: routed to the review queue (OCR or font-map conversion)")


def _title(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return re.sub(r"[-_]+", " ", stem).strip().title()


# ---------------------------------------------------------------- text and markdown


def _md_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _markdown(text: str, filename: str, title: str | None = None) -> ParsedDocument:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    blocks: list[Block] = []
    path: list[str] = []
    para: list[str] = []
    page = 1

    def flush() -> None:
        if para:
            t = " ".join(s.strip() for s in para).strip()
            if t:
                blocks.append(Block("paragraph", t, page=page, heading_path=list(path)))
            para.clear()

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s == "\f" or s == "<!-- page -->":
            flush()
            page += 1
        elif m := re.match(r"^(#{1,6})\s+(.*)", s):
            flush()
            level = len(m.group(1))
            path = [*path[: level - 1], m.group(2).strip()]
            path = path[:level]
            blocks.append(Block("heading", m.group(2).strip(), page=page, heading_path=list(path)))
            if title is None and level == 1:
                title = m.group(2).strip()
        elif s.startswith("|"):
            flush()
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            rows = _md_table(tbl)
            if rows:
                blocks.append(Block("table", _render_table(rows), page=page, heading_path=list(path), rows=rows))
            continue
        elif re.match(r"^([-*•]|\d{1,2}[.)])\s+", s) and not CLAUSE_HEAD.match(s):
            flush()
            blocks.append(Block("list", re.sub(r"^([-*•]|\d{1,2}[.)])\s+", "", s), page=page, heading_path=list(path)))
        elif CLAUSE_HEAD.match(s):
            flush()
            para.append(s)
        elif not s:
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return ParsedDocument(
        title=title or _title(filename), blocks=blocks, mime="text/markdown", parser="markdown", pages=page
    )


def _render_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head, *body = rows
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(out)


# ---------------------------------------------------------------- PDF


def _pdf(data: bytes, filename: str) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted PDF: supply the key or an unencrypted copy")
    blocks: list[Block] = []
    title = (reader.metadata.title if reader.metadata and reader.metadata.title else None) or None
    path: list[str] = []
    warnings: list[str] = []
    for pno, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if len(text.strip()) < 20:
            blocks.append(Block("paragraph", f"[page {pno}: no text layer; queued for OCR]", page=pno, confidence=0.0))
            warnings.append(f"page {pno}: scanned or image-only, needs OCR")
            continue
        para: list[str] = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                if para:
                    blocks.append(Block("paragraph", " ".join(para), page=pno, heading_path=list(path)))
                    para = []
                continue
            is_heading = (
                len(s) < 80 and (s.isupper() or re.match(r"^(chapter|part|section|annexure)\b", s, re.I))
            ) and not s.endswith(".")
            if is_heading:
                if para:
                    blocks.append(Block("paragraph", " ".join(para), page=pno, heading_path=list(path)))
                    para = []
                path = [s.title() if s.isupper() else s]
                blocks.append(Block("heading", path[0], page=pno, heading_path=list(path)))
                title = title or path[0]
            elif CLAUSE_HEAD.match(s) and para:
                blocks.append(Block("paragraph", " ".join(para), page=pno, heading_path=list(path)))
                para = [s]
            else:
                para.append(s)
        if para:
            blocks.append(Block("paragraph", " ".join(para), page=pno, heading_path=list(path)))
    return ParsedDocument(
        title=title or _title(filename),
        blocks=blocks,
        mime="application/pdf",
        parser="pypdf",
        pages=len(reader.pages),
        warnings=warnings,
    )


# ---------------------------------------------------------------- Office


def _docx(data: bytes, filename: str) -> ParsedDocument:
    import docx  # python-docx

    d = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    path: list[str] = []
    title = d.core_properties.title or None
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = docx.text.paragraph.Paragraph(child, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            if style.startswith("heading") or style == "title":
                level = int(re.sub(r"\D", "", style) or 1)
                path = [*path[: level - 1], text]
                blocks.append(Block("heading", text, heading_path=list(path)))
                title = title or text
            elif "list" in style:
                blocks.append(Block("list", text, heading_path=list(path)))
            else:
                blocks.append(Block("paragraph", text, heading_path=list(path)))
        elif tag == "tbl":
            t = docx.table.Table(child, d)
            rows = [[c.text.strip() for c in r.cells] for r in t.rows]
            if rows:
                blocks.append(Block("table", _render_table(rows), heading_path=list(path), rows=rows))
    return ParsedDocument(title=title or _title(filename), blocks=blocks, mime="docx", parser="python-docx")


def _xlsx(data: bytes, filename: str) -> ParsedDocument:
    import openpyxl

    wb_val = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    wb_f = openpyxl.load_workbook(io.BytesIO(data), data_only=False, read_only=False)
    blocks: list[Block] = []
    warnings: list[str] = []
    for ws in wb_val.worksheets:
        if ws.sheet_state != "visible":
            warnings.append(f"hidden sheet '{ws.title}' not indexed")
            continue
        wf = wb_f[ws.title]
        rows: list[list[str]] = []
        formulas = 0
        for r_val, r_f in zip(ws.iter_rows(), wf.iter_rows(), strict=False):
            cells = []
            for cv, cf in zip(r_val, r_f, strict=False):
                v = cv.value
                if isinstance(cf.value, str) and cf.value.startswith("="):
                    formulas += 1
                    if v is None:
                        v = cf.value  # cached value missing: keep the formula visible
                cells.append("" if v is None else _cell(v))
            if any(c.strip() for c in cells):
                rows.append(cells)
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        if formulas:
            warnings.append(f"sheet '{ws.title}': {formulas} formula cells kept with their values")
        blocks.append(Block("heading", ws.title, heading_path=[ws.title]))
        blocks.append(Block("table", _render_table(rows), heading_path=[ws.title], rows=rows))
    return ParsedDocument(title=_title(filename), blocks=blocks, mime="xlsx", parser="openpyxl", warnings=warnings)


def _cell(v: object) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]  # type: ignore[attr-defined]
    return str(v)


def _csv(text: str, filename: str) -> ParsedDocument:
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    return ParsedDocument(
        title=_title(filename), blocks=[Block("table", _render_table(rows), rows=rows)], mime="text/csv", parser="csv"
    )


# ---------------------------------------------------------------- HTML and email


def _html(html: str, filename: str) -> ParsedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "footer", "form", "iframe"]):
        t.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None
    blocks: list[Block] = []
    path: list[str] = []
    root = soup.body or soup
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "table", "pre", "blockquote", "div"]):
        if el.name == "div" and el.find(["p", "table", "div", "li", "h1", "h2", "h3"]):
            continue  # only leaf divs carry text of their own
        if el.find_parent("table") and el.name != "table":
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            level = int(el.name[1])
            text = el.get_text(" ", strip=True)
            path = [*path[: level - 1], text][:level]
            blocks.append(Block("heading", text, heading_path=list(path)))
            title = title or text
        elif el.name == "table":
            rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in el.find_all("tr")]
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append(Block("table", _render_table(rows), heading_path=list(path), rows=rows))
        else:
            text = el.get_text(" ", strip=True)
            if text:
                hidden = "display:none" in (el.get("style") or "").replace(" ", "") or el.has_attr("hidden")
                b = Block("list" if el.name == "li" else "paragraph", text, heading_path=list(path))
                if hidden:
                    b.confidence = 0.5  # hidden text is a classic injection carrier; flag it
                blocks.append(b)
    return ParsedDocument(title=title or _title(filename), blocks=blocks, mime="text/html", parser="html")


def _eml(data: bytes, filename: str) -> ParsedDocument:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    subject = str(msg.get("subject", "")) or _title(filename)
    meta = f"From: {msg.get('from', '')} | To: {msg.get('to', '')} | Date: {msg.get('date', '')}"
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = "\n\n".join(b.text for b in _html(text, filename).blocks)
    # strip quoted replies: they are indexed with the message they belong to
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    cut = next((i for i, ln in enumerate(lines) if re.match(r"^On .+ wrote:$", ln.strip())), None)
    if cut is not None:
        lines = lines[:cut]
    doc = _markdown("\n".join(lines), filename, title=subject)
    doc.blocks.insert(0, Block("paragraph", meta, heading_path=[subject]))
    doc.parser = "email"
    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    if attachments:
        doc.warnings.append(f"attachments ingested separately: {', '.join(attachments)}")
    return doc
