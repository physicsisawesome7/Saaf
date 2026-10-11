"""Synthetic corpus generator for IndicPII-Bench.

Every identifier is checksum-valid and *invented*. Documents mix realistic
templates (KYC forms, bank statements, Hinglish chat, support tickets,
OCR-noisy scans, invoices) with hard negatives that look like PII but are not
(order IDs, AWB numbers, invoice numbers, transaction IDs).

Synthetic data alone is not enough -- the plan calls for hand-written samples,
community contributions and a private held-out split. This generator is the
reproducible public baseline (``corpus/v0``); the held-out split is never
committed.

    python -m indicpii_bench generate --seed 7 --n 400 -o corpus/v0/docs.jsonl
"""

from __future__ import annotations

import json
import random
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from saaf.validators import GST_STATE_CODES, gstin_check_char, luhn, verhoeff, verhoeff_check_digit

DEVANAGARI = str.maketrans("0123456789", "०१२३४५६७८९")
OCR_SWAPS = {"0": "O", "1": "I", "5": "S", "8": "B"}
UPI_HANDLES = ["okaxis", "okhdfcbank", "oksbi", "ybl", "paytm", "ibl", "axl", "upi"]
FIRST = [
    "Ravi",
    "Lakshmi",
    "Arjun",
    "Priya",
    "Imran",
    "Fatima",
    "Suresh",
    "Ananya",
    "Gurpreet",
    "Meera",
    "Rahul",
    "Kavya",
]
LAST = ["Kumar", "Iyer", "Sharma", "Khan", "Reddy", "Singh", "Nair", "Das", "Patel", "Menon", "Gupta", "Bose"]


@dataclass
class Doc:
    id: str
    domain: str
    text: str = ""
    spans: list[dict[str, object]] = field(default_factory=list)
    hard_negative: bool = False
    noise: list[str] = field(default_factory=list)

    def add(self, s: str) -> None:
        self.text += s

    def pii(self, entity: str, value: str) -> None:
        start = len(self.text)
        self.text += value
        self.spans.append({"start": start, "end": len(self.text), "entity": entity})

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "domain": self.domain,
            "text": self.text,
            "spans": self.spans,
            "hard_negative": self.hard_negative,
            "noise": self.noise,
        }


class Gen:
    def __init__(self, rng: random.Random):
        self.r = rng

    def digits(self, n: int) -> str:
        return "".join(self.r.choice(string.digits) for _ in range(n))

    def aadhaar(self) -> str:
        p = self.r.choice("23456789") + self.digits(10)
        return p + verhoeff_check_digit(p)

    def pan(self) -> str:
        L = string.ascii_uppercase
        return (
            "".join(self.r.choice(L) for _ in range(3))
            + self.r.choice("PCHF")
            + self.r.choice(L)
            + self.digits(4)
            + self.r.choice(L)
        )

    def gstin(self) -> str:
        base = self.r.choice(sorted(GST_STATE_CODES - {"97", "99"})) + self.pan() + self.r.choice("123456789") + "Z"
        return base + gstin_check_char(base)

    def mobile(self) -> str:
        return self.r.choice("6789") + self.digits(9)

    def card(self) -> str:
        while True:
            c = "4" + self.digits(15)
            if luhn(c):
                return c

    def ifsc(self) -> str:
        return self.r.choice(["SBIN", "HDFC", "ICIC", "UTIB", "KKBK", "PUNB"]) + "0" + self.digits(6)

    def name(self) -> str:
        return f"{self.r.choice(FIRST)} {self.r.choice(LAST)}"

    def not_aadhaar_12(self) -> str:
        """12-digit number that fails Verhoeff (a realistic order/AWB number)."""
        while True:
            n = self.r.choice("23456789") + self.digits(11)
            if not verhoeff(n):
                return n

    def any_12(self) -> str:
        """12 digits, checksum unconstrained: ~10% pass Verhoeff by chance."""
        return self.r.choice("23456789") + self.digits(11)

    # -- formatting variants ----------------------------------------------

    def group(self, s: str, sizes: tuple[int, ...], sep: str) -> str:
        out, i = [], 0
        for n in sizes:
            out.append(s[i : i + n])
            i += n
        return sep.join(out)

    def fmt_aadhaar(self, a: str) -> tuple[str, str]:
        style = self.r.choice(["space", "space", "hyphen", "plain"])
        return {"space": self.group(a, (4, 4, 4), " "), "hyphen": self.group(a, (4, 4, 4), "-"), "plain": a}[
            style
        ], style

    def fmt_mobile(self, m: str) -> str:
        return self.r.choice([m, f"+91 {m[:5]} {m[5:]}", f"+91-{m}", f"0{m}", f"{m[:5]} {m[5:]}"])

    def ocr(self, s: str, rate: float = 0.25) -> str:
        return "".join(OCR_SWAPS[c] if c in OCR_SWAPS and self.r.random() < rate else c for c in s)


def kyc(g: Gen, d: Doc) -> None:
    aad, _ = g.fmt_aadhaar(g.aadhaar())
    d.add("KYC Verification Form\nApplicant: Shri ")
    d.pii("PERSON", g.name())
    d.add("\nAadhaar No: ")
    d.pii("AADHAAR", aad)
    d.add("\nPAN: ")
    d.pii("PAN", g.pan())
    d.add("\nMobile: ")
    d.pii("PHONE_IN", g.fmt_mobile(g.mobile()))
    d.add("\nEmail: ")
    d.pii("EMAIL", f"{g.r.choice(FIRST).lower()}.{g.digits(3)}@example.in")
    d.add("\nApplication ref: ")
    d.add(g.not_aadhaar_12())
    d.add("\n")


def bank_statement(g: Gen, d: Doc) -> None:
    d.add("Account Statement\nA/c No: ")
    d.pii("BANK_ACCOUNT", g.digits(g.r.choice([11, 12, 14])))
    d.add("  IFSC: ")
    d.pii("IFSC", g.ifsc())
    d.add("\nDate        Narration                         Amount\n")
    for _ in range(g.r.randint(2, 4)):
        d.add(f"0{g.r.randint(1, 9)}/0{g.r.randint(1, 9)}/2026  UPI/")
        d.add(g.digits(12))
        d.add("/")
        d.pii("UPI_ID", f"{g.r.choice(FIRST).lower()}{g.digits(2)}@{g.r.choice(UPI_HANDLES)}")
        d.add(f"   {g.r.randint(100, 99999)}.00\n")
    d.noise.append("utr-12-digit")


def hinglish_chat(g: Gen, d: Doc) -> None:
    a = g.aadhaar()
    dev = g.r.random() < 0.3
    aad = g.group(a, (4, 4, 4), " ")
    if dev:
        aad = aad.translate(DEVANAGARI)
        d.noise.append("devanagari-digits")
    d.add(g.r.choice(["bhai ", "didi ", "sir ", ""]))
    d.add(g.r.choice(["mera adhaar ", "mera aadhar no ", "aadhaar card number "]))
    d.pii("AADHAAR", aad)
    d.add(" hai, ")
    d.add(g.r.choice(["pan bhi bhej raha hu ", "aur PAN ", "pan card "]))
    pan = g.pan()
    d.pii("PAN", pan.lower() if g.r.random() < 0.4 else pan)
    d.add(". ")
    d.add(g.r.choice(["paise yaha bhejo ", "gpay kar do ", "phonepe pe bhej do "]))
    d.pii("UPI_ID", f"{g.mobile()}@{g.r.choice(['ybl', 'paytm', 'okaxis'])}")
    d.add(g.r.choice([" 🙏", " jaldi", " thanks"]))


def support_ticket(g: Gen, d: Doc) -> None:
    d.add(f"Ticket #{g.digits(7)}: Customer says card ")
    d.pii("CREDIT_CARD", g.group(g.card(), (4, 4, 4, 4), " "))
    d.add(" was charged twice for order ")
    d.add(g.any_12())
    d.add(". Callback on ")
    d.pii("PHONE_IN", g.fmt_mobile(g.mobile()))
    d.add(". GSTIN for invoice: ")
    d.pii("GSTIN", g.gstin())
    d.add(".")


def ocr_scan(g: Gen, d: Doc) -> None:
    a = g.aadhaar()
    noisy = g.ocr(g.group(a, (4, 4, 4), " "))
    d.add("GOVERNMENT OF INDIA\n")
    d.pii("PERSON", g.name().upper())  # all-caps names: a known hard case for rule-based tools
    d.add("\nDOB: ")
    d.pii("DATE_OF_BIRTH", f"{g.r.randint(10, 28)}/{g.r.randint(10, 12)}/19{g.r.randint(60, 99)}")
    d.add("\nAadhaar: ")
    d.pii("AADHAAR", noisy)
    d.add("\n")
    if noisy != g.group(a, (4, 4, 4), " "):
        d.noise.append("ocr-confusables")


def invoice(g: Gen, d: Doc) -> None:
    d.add(f"TAX INVOICE  INV-2026-{g.digits(6)}\nSupplier GSTIN: ")
    d.pii("GSTIN", g.gstin())
    d.add(
        f"\nOrder ID: {g.any_12()}  AWB: {g.any_12()}\nHSN 8471  Qty {g.r.randint(1, 20)}  Total Rs {g.r.randint(1000, 99999)}.00\n"
    )


def hard_negative(g: Gen, d: Doc) -> None:
    d.hard_negative = True
    lines = [
        f"Order ID {g.any_12()} has shipped via AWB {g.any_12()}.",
        f"Txn id {g.mobile()} failed; ref no {g.digits(12)}.",
        f"Invoice INV-{g.digits(4)}-{g.digits(6)} dated 12/03/2026, batch {g.digits(10)}.",
        f"Tracking {g.digits(12)}, PNR {g.digits(10)}, serial {g.digits(16)}.",
        f"Booking reference {g.not_aadhaar_12()} confirmed for {g.r.randint(1, 6)} guests.",
    ]
    d.add(" ".join(g.r.sample(lines, k=3)))


TEMPLATES: dict[str, Callable[[Gen, Doc], None]] = {
    "kyc": kyc,
    "bank_statement": bank_statement,
    "hinglish_chat": hinglish_chat,
    "support_ticket": support_ticket,
    "ocr_scan": ocr_scan,
    "invoice": invoice,
    "hard_negative": hard_negative,
}


def generate(n: int, seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    g = Gen(rng)
    names = list(TEMPLATES)
    out = []
    for i in range(n):
        domain = names[i % len(names)]
        d = Doc(id=f"v0-{seed}-{i:05d}", domain=domain)
        TEMPLATES[domain](g, d)
        out.append(d.to_json())
    return out


def write(path: str | Path, docs: list[dict[str, object]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
