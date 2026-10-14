"""Fetch licence-cleared external data for IndicPII-Bench.

    python -m indicpii_bench fetch            # download + build lexicons and external slices
    python -m indicpii_bench fetch --offline  # rebuild from already-downloaded files

Rules (see docs/COMPETITIVE_EDGE_PLAN.md, section 4):
* Only sources whose licence was checked are listed here. Each download is
  recorded in ``data/manifest.json`` with its URL, licence and SHA-256.
* Raw downloads live in ``bench/data/raw/`` (git-ignored, never redistributed).
* Committed outputs are small derived lexicons from permissive sources only
  (CC0 / MIT). Share-alike data (HiNER, CC BY-SA 4.0) is turned into a local
  evaluation slice that is git-ignored and never mixed into training data.
* No real personal data is collected: the sources are public-domain NER
  corpora of news/Wikipedia text and public bank-branch codes.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import urllib.request
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BENCH = Path(__file__).resolve().parents[1]
RAW = BENCH / "data" / "raw"
LEXICONS = Path(__file__).resolve().parent / "lexicons"
EXTERNAL = BENCH / "corpus" / "external"
MANIFEST = BENCH / "data" / "manifest.json"

HF = "https://huggingface.co/datasets"
NAAMAPADAM_LANGS = ("hi", "mr", "ta", "te")

SOURCES: list[dict[str, Any]] = [
    {
        "id": "razorpay-ifsc-banks",
        "url": "https://raw.githubusercontent.com/razorpay/ifsc/master/src/banknames.json",
        "licence": "MIT",
        "attribution": "Razorpay IFSC (github.com/razorpay/ifsc)",
        "file": "razorpay/banknames.json",
    },
    {
        "id": "razorpay-ifsc-branches",
        "url": "https://raw.githubusercontent.com/razorpay/ifsc/master/src/IFSC.json",
        "licence": "MIT",
        "attribution": "Razorpay IFSC (github.com/razorpay/ifsc)",
        "file": "razorpay/IFSC.json",
    },
    *[
        {
            "id": f"naamapadam-{lang}",
            "url": f"{HF}/ai4bharat/naamapadam/resolve/main/data/{lang}_IndicNER_v1.0.zip",
            "licence": "CC0-1.0",
            "attribution": "Naamapadam, AI4Bharat (arXiv:2212.10168)",
            "file": f"naamapadam/{lang}_IndicNER_v1.0.zip",
        }
        for lang in NAAMAPADAM_LANGS
    ],
    {
        "id": "hiner-test",
        "url": f"{HF}/cfilt/HiNER-original/resolve/main/data/test.json",
        "licence": "CC-BY-SA-4.0",
        "attribution": "HiNER, CFILT IIT Bombay (arXiv:2204.13743)",
        "file": "hiner/test.json",
        "eval_only": True,
    },
    {
        "id": "hiner-labels",
        "url": f"{HF}/cfilt/HiNER-original/resolve/main/data/labels_list.txt",
        "licence": "CC-BY-SA-4.0",
        "attribution": "HiNER, CFILT IIT Bombay",
        "file": "hiner/labels_list.txt",
        "eval_only": True,
    },
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(offline: bool = False) -> dict[str, Any]:
    manifest: dict[str, Any] = {"fetched": datetime.now(UTC).isoformat(timespec="seconds"), "sources": []}
    for src in SOURCES:
        dest = RAW / src["file"]
        if not dest.exists():
            if offline:
                raise SystemExit(f"missing {dest}; run without --offline")
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"downloading {src['id']} …")
            req = urllib.request.Request(src["url"], headers={"User-Agent": "indicpii-bench/0.1"})
            with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as out:
                while chunk := r.read(1 << 20):
                    out.write(chunk)
        manifest["sources"].append(
            {
                **{k: v for k, v in src.items() if k != "file"},
                "path": src["file"],
                "bytes": dest.stat().st_size,
                "sha256": _sha256(dest),
            }
        )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------
# Naamapadam -> name / place lexicons (CC0) + Indic-script PERSON eval slice
# --------------------------------------------------------------------------


def _bio_spans(words: list[str], tags: list[str]) -> list[tuple[int, int, str]]:
    """(start_word, end_word_exclusive, type) for B-/I- tagged runs."""
    spans, start, kind = [], None, None
    for i, tag in enumerate([*tags, "O"]):
        t = tag.split("-", 1)
        if start is not None and (tag == "O" or t[0] == "B" or (len(t) > 1 and t[1] != kind)):
            spans.append((start, i, kind))
            start, kind = None, None
        if tag != "O" and t[0] == "B":
            start, kind = i, t[1]
        elif tag != "O" and start is None:  # stray I- tag starts a span
            start, kind = i, t[1] if len(t) > 1 else tag
    return spans


def _naamapadam_rows(lang: str, split: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Stream rows from the zip so the large train splits never sit in memory whole."""
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(RAW / "naamapadam" / f"{lang}_IndicNER_v1.0.zip") as z, z.open(f"{lang}_{split}.json") as fh:
        for raw in io.TextIOWrapper(fh, encoding="utf-8"):
            if raw.strip():
                rows.append(json.loads(raw))
                if limit is not None and len(rows) >= limit:
                    break
    return rows


# Honorifics / titles that NER tags as part of PER spans; never a given name.
TITLES = set(
    [
        "जस्टिस",
        "न्यायमूर्ति",
        "न्यायमूर्ती",
        "जस्टीस",
        "श्री",
        "श्रीमती",
        "डॉ",
        "डॉक्टर",
        "प्रोफेसर",
        "कुमारी",
        "सुश्री",
        "ஜஸ்டிஸ்",
        "நீதிபதி",
        "திரு",
        "திருமதி",
        "டாக்டர்",
        "ஸ்ரீ",
        "జస్టిస్",
        "న్యాయమూర్తి",
        "శ్రీ",
        "శ్రీమతి",
        "డాక్టర్",
        "श्रीमान",
        "सौ",
        "प्रा",
    ]
)


def build_naamapadam(rng: random.Random, per_lang_eval: int = 300) -> dict[str, Any]:
    names: dict[str, dict[str, list[str]]] = {}
    places: dict[str, list[str]] = {}
    eval_docs: list[dict[str, Any]] = []
    for lang in NAAMAPADAM_LANGS:
        per, loc = Counter(), Counter()
        for row in _naamapadam_rows(lang, "train", limit=300_000):
            for s, e, kind in _bio_spans(row["words"], row["ner"]):
                text = " ".join(row["words"][s:e])
                if not 2 <= len(text) <= 40 or any(ch.isdigit() for ch in text):
                    continue
                if kind == "PER" and 1 <= e - s <= 3:
                    per[text] += 1
                elif kind == "LOC" and 1 <= e - s <= 3:
                    loc[text] += 1
        # Never use whole real names: the most frequent PER entities are public
        # figures and deities. Drop the top of the frequency list, then keep only
        # *token pools* (first tokens / last tokens of multi-token names) so the
        # generator recombines them into synthetic people.
        ranked = [t for t, c in per.most_common() if c >= 2]
        famous = set(ranked[:200])
        firsts, lasts = Counter(), Counter()
        for full in ranked[200:6000]:
            toks = full.split()
            if len(toks) < 2 or full in famous or any(ch.isascii() and ch.isalpha() for ch in full):
                continue
            firsts[toks[0]] += 1
            lasts[toks[-1]] += 1
        famous_tokens = {tok for name in famous for tok in name.split()} | TITLES
        names[lang] = {
            "first": [t for t, c in firsts.most_common(400) if len(t) > 1 and t not in famous_tokens],
            "last": [t for t, c in lasts.most_common(300) if len(t) > 1 and c >= 2],
        }
        places[lang] = [t for t, c in loc.most_common(800) if c >= 2]

        # gold test split (human-validated in the Naamapadam paper) -> PERSON eval
        test = [r for r in _naamapadam_rows(lang, "test") if any(t.endswith("PER") for t in r["ner"])]
        rng.shuffle(test)
        for i, row in enumerate(test[:per_lang_eval]):
            text, spans, pos = "", [], []
            for w in row["words"]:
                if text:
                    text += " "
                pos.append(len(text))
                text += w
            for s, e, kind in _bio_spans(row["words"], row["ner"]):
                if kind == "PER":
                    end = pos[e - 1] + len(row["words"][e - 1])
                    spans.append({"start": pos[s], "end": end, "entity": "PERSON"})
            eval_docs.append(
                {
                    "id": f"naamapadam-{lang}-{i:04d}",
                    "domain": "indic_ner",
                    "slice": f"indic_person_{lang}",
                    "text": text,
                    "spans": spans,
                    "hard_negative": False,
                    "noise": [f"script-{lang}"],
                    "source": "naamapadam (CC0)",
                }
            )
    return {"names": names, "places": places, "eval": eval_docs}


def build_hiner(rng: random.Random, n: int = 400) -> list[dict[str, Any]]:
    labels = (RAW / "hiner" / "labels_list.txt").read_text(encoding="utf-8").split()
    data = json.loads((RAW / "hiner" / "test.json").read_text(encoding="utf-8"))
    rows = [r for r in data if any(labels[t].endswith("PERSON") for t in r["ner_tags"])]
    rng.shuffle(rows)
    docs = []
    for i, row in enumerate(rows[:n]):
        tags = [labels[t] for t in row["ner_tags"]]
        text, pos = "", []
        for w in row["tokens"]:
            if text:
                text += " "
            pos.append(len(text))
            text += w
        spans = [
            {"start": pos[s], "end": pos[e - 1] + len(row["tokens"][e - 1]), "entity": "PERSON"}
            for s, e, kind in _bio_spans(row["tokens"], tags)
            if kind == "PERSON"
        ]
        docs.append(
            {
                "id": f"hiner-{i:04d}",
                "domain": "hindi_news",
                "slice": "hiner_person_hi",
                "text": text,
                "spans": spans,
                "hard_negative": False,
                "noise": ["script-hi"],
                "source": "HiNER (CC BY-SA 4.0, eval only)",
            }
        )
    return docs


# --------------------------------------------------------------------------
# Razorpay -> real bank names and IFSC codes (MIT)
# --------------------------------------------------------------------------


def build_banks(rng: random.Random, per_bank: int = 3) -> dict[str, Any]:
    names = json.loads((RAW / "razorpay" / "banknames.json").read_text(encoding="utf-8"))
    branches = json.loads((RAW / "razorpay" / "IFSC.json").read_text(encoding="utf-8"))
    out = []
    for code, branch_ids in branches.items():
        if code not in names or not branch_ids:
            continue
        picks = rng.sample(branch_ids, k=min(per_bank, len(branch_ids)))
        ifscs = [f"{code}0{b:06d}" if isinstance(b, int) else f"{code}0{str(b)[-6:].rjust(6, '0')}" for b in picks]
        out.append({"code": code, "name": names[code], "ifsc": ifscs})
    return {"banks": out}


def run(offline: bool = False, seed: int = 11) -> None:
    rng = random.Random(seed)
    download(offline)
    LEXICONS.mkdir(parents=True, exist_ok=True)
    EXTERNAL.mkdir(parents=True, exist_ok=True)

    nm = build_naamapadam(rng)
    (LEXICONS / "indic_names.json").write_text(
        json.dumps(
            {
                "source": "Naamapadam, AI4Bharat",
                "licence": "CC0-1.0",
                "note": "token pools only; top-200 most frequent (public) names excluded; recombine to synthesise people",
                "names": nm["names"],
            },
            ensure_ascii=False,
            indent=0,
        ),
        encoding="utf-8",
    )
    (LEXICONS / "indic_places.json").write_text(
        json.dumps(
            {"source": "Naamapadam, AI4Bharat", "licence": "CC0-1.0", "places": nm["places"]},
            ensure_ascii=False,
            indent=0,
        ),
        encoding="utf-8",
    )
    banks = build_banks(rng)
    (LEXICONS / "banks.json").write_text(
        json.dumps({"source": "Razorpay IFSC", "licence": "MIT", **banks}, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )

    def dump(name: str, docs: list[dict[str, Any]]) -> None:
        with (EXTERNAL / name).open("w", encoding="utf-8", newline="\n") as fh:
            for d in docs:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    dump("naamapadam_person.jsonl", nm["eval"])
    dump("hiner_person.jsonl", build_hiner(rng))
    counts = {k: (len(v["first"]), len(v["last"])) for k, v in nm["names"].items()}
    print(f"lexicons: names {counts}, banks {len(banks['banks'])}")
    print(f"external eval: naamapadam {len(nm['eval'])} docs, hiner written (eval only)")
