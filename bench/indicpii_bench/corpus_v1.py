"""IndicPII-Bench corpus v1: synthetic documents in named slices.

    python -m indicpii_bench generate-v1 --per-slice 150 --seed 23 -o corpus/v1/docs.jsonl

Every identifier is synthetic (checksum-valid generators). People are
synthesised by recombining first-name and surname *token pools* (see
fetch.py), so no document names a real, identifiable person. Bank names and
IFSC codes are real public branch codes (Razorpay IFSC, MIT).

Slices (each doc carries ``slice``):
  structured_en      KYC / support / invoice text in English with Indian IDs
  hinglish           Roman-script Hinglish chat with names and IDs
  indic_script       Hindi, Marathi, Tamil, Telugu KYC text with native-script names
  bank_real          statements with real bank names and IFSC codes
  obfuscated         IDs disguised by spacing, dots, homoglyphs, zero-width, digit words, OCR
  look_alikes        order / AWB / UTR / invoice numbers only (hard negatives, no PII)
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

from indicpii_bench.generate import Doc, Gen

LEX = Path(__file__).resolve().parent / "lexicons"

# Common given names and surnames across Indian regions, in Roman script.
# Generic name tokens (not records of real people); recombined at random.
ROMAN_FIRST = [
    "Aarav",
    "Aditi",
    "Aditya",
    "Akash",
    "Ananya",
    "Anjali",
    "Arjun",
    "Asha",
    "Ayesha",
    "Bhavna",
    "Chetan",
    "Deepa",
    "Devika",
    "Dinesh",
    "Divya",
    "Farhan",
    "Gaurav",
    "Geeta",
    "Harish",
    "Imran",
    "Ishaan",
    "Jaya",
    "Karan",
    "Kavita",
    "Kiran",
    "Lakshmi",
    "Mahesh",
    "Meena",
    "Mohan",
    "Nandini",
    "Naveen",
    "Neha",
    "Nikhil",
    "Nisha",
    "Pooja",
    "Pradeep",
    "Priya",
    "Rahul",
    "Rajesh",
    "Ramesh",
    "Rekha",
    "Ritu",
    "Rohit",
    "Sachin",
    "Sameer",
    "Sana",
    "Sandeep",
    "Sangeeta",
    "Sanjay",
    "Shalini",
    "Shreya",
    "Siddharth",
    "Sneha",
    "Sunita",
    "Suresh",
    "Swati",
    "Tanvi",
    "Uday",
    "Usha",
    "Varun",
    "Vikram",
    "Vinay",
    "Yash",
    "Zoya",
    "Abdul",
    "Fatima",
    "Gurpreet",
    "Harpreet",
    "Joseph",
    "Mary",
    "Thomas",
    "Anil",
    "Sunil",
    "Venkatesh",
    "Lavanya",
    "Karthik",
    "Meenakshi",
    "Senthil",
    "Arun",
    "Bhaskar",
    "Gopal",
]
ROMAN_LAST = [
    "Sharma",
    "Verma",
    "Gupta",
    "Singh",
    "Kumar",
    "Patel",
    "Shah",
    "Mehta",
    "Joshi",
    "Desai",
    "Kulkarni",
    "Patil",
    "Deshmukh",
    "Reddy",
    "Rao",
    "Naidu",
    "Iyer",
    "Iyengar",
    "Nair",
    "Menon",
    "Pillai",
    "Das",
    "Bose",
    "Banerjee",
    "Chatterjee",
    "Mukherjee",
    "Ghosh",
    "Sen",
    "Khan",
    "Ahmed",
    "Qureshi",
    "Ansari",
    "Siddiqui",
    "Fernandes",
    "D'Souza",
    "Thomas",
    "Mathew",
    "Gill",
    "Sandhu",
    "Dhillon",
    "Yadav",
    "Mishra",
    "Tiwari",
    "Pandey",
    "Chauhan",
    "Rathore",
    "Agarwal",
    "Bansal",
    "Jain",
    "Saxena",
    "Srivastava",
    "Shetty",
    "Hegde",
    "Gowda",
    "Krishnan",
    "Subramanian",
    "Natarajan",
    "Chandra",
    "Bhatt",
    "Trivedi",
    "Kapoor",
    "Malhotra",
]

DEVANAGARI = str.maketrans("0123456789", "०१२३४५६७८९")
DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
CYRILLIC = str.maketrans(
    {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х"}
)

SCRIPT_TEMPLATES = {
    "hi": ("नाम: ", "\nआधार संख्या: ", "\nमोबाइल नंबर: ", "\nपैन: ", "\nपता: "),
    "mr": ("नाव: ", "\nआधार क्रमांक: ", "\nमोबाईल नंबर: ", "\nपॅन: ", "\nपत्ता: "),
    "ta": ("பெயர்: ", "\nஆதார் எண்: ", "\nகைபேசி எண்: ", "\nபான்: ", "\nமுகவரி: "),
    "te": ("పేరు: ", "\nఆధార్ సంఖ్య: ", "\nమొబైల్ నంబర్: ", "\nపాన్: ", "\nచిరునామా: "),
}


class GenV1(Gen):
    def __init__(self, rng: random.Random):
        super().__init__(rng)
        names = json.loads((LEX / "indic_names.json").read_text(encoding="utf-8"))["names"]
        self.indic = names
        self.places = json.loads((LEX / "indic_places.json").read_text(encoding="utf-8"))["places"]
        self.banks = json.loads((LEX / "banks.json").read_text(encoding="utf-8"))["banks"]

    def roman_name(self) -> str:
        return f"{self.r.choice(ROMAN_FIRST)} {self.r.choice(ROMAN_LAST)}"

    def script_name(self, lang: str) -> str:
        pool = self.indic[lang]
        return f"{self.r.choice(pool['first'])} {self.r.choice(pool['last'])}"


def structured_en(g: GenV1, d: Doc) -> None:
    aad, _ = g.fmt_aadhaar(g.aadhaar())
    d.add("Hi team, please verify the applicant ")
    d.pii("PERSON", g.roman_name())
    d.add(". Aadhaar ")
    d.pii("AADHAAR", aad)
    d.add(", PAN ")
    d.pii("PAN", g.pan())
    d.add(", GSTIN ")
    d.pii("GSTIN", g.gstin())
    d.add(". Reach them on ")
    d.pii("PHONE_IN", g.fmt_mobile(g.mobile()))
    d.add(" or ")
    d.pii("EMAIL", f"{g.r.choice(ROMAN_FIRST).lower()}.{g.r.choice(ROMAN_LAST).lower()}{g.digits(2)}@example.in")
    d.add(f". Ticket ref {g.not_aadhaar_12()}.")


def hinglish(g: GenV1, d: Doc) -> None:
    d.add(g.r.choice(["bhai ", "hello ji, ", "sir ", ""]))
    d.add(g.r.choice(["mera naam ", "main ", "myself "]))
    d.pii("PERSON", g.roman_name())
    d.add(g.r.choice([" hai. ", " bol raha hu. ", " here. "]))
    d.add(g.r.choice(["mera aadhar ", "adhaar no ", "aadhaar card number "]))
    d.pii("AADHAAR", g.group(g.aadhaar(), (4, 4, 4), " "))
    d.add(" hai aur ")
    d.add(g.r.choice(["pan ", "PAN card "]))
    pan = g.pan()
    d.pii("PAN", pan.lower() if g.r.random() < 0.5 else pan)
    d.add(". ")
    d.add(g.r.choice(["paise yaha bhejo ", "gpay kar do ", "phonepe pe bhej do "]))
    d.pii("UPI_ID", f"{g.mobile()}@{g.r.choice(['ybl', 'paytm', 'okaxis', 'oksbi'])}")
    d.add(g.r.choice([", call karo ", ", whatsapp pe ping karo "]))
    d.pii("PHONE_IN", g.fmt_mobile(g.mobile()))


def indic_script(g: GenV1, d: Doc) -> None:
    lang = g.r.choice(list(SCRIPT_TEMPLATES))
    t = SCRIPT_TEMPLATES[lang]
    d.noise.append(f"script-{lang}")
    d.add(t[0])
    d.pii("PERSON", g.script_name(lang))
    d.add(t[1])
    aad = g.group(g.aadhaar(), (4, 4, 4), " ")
    if lang in ("hi", "mr") and g.r.random() < 0.5:
        aad = aad.translate(DEVANAGARI)
        d.noise.append("devanagari-digits")
    d.pii("AADHAAR", aad)
    d.add(t[2])
    d.pii("PHONE_IN", g.mobile())
    d.add(t[3])
    d.pii("PAN", g.pan())
    d.add(t[4])
    d.add(f"{g.r.randint(1, 300)}, {g.r.choice(g.places[lang])}")


def bank_real(g: GenV1, d: Doc) -> None:
    bank = g.r.choice(g.banks)
    d.add(f"{bank['name']}\nStatement of account\nAccount holder: ")
    d.pii("PERSON", g.roman_name())
    d.add("\nA/c No: ")
    d.pii("BANK_ACCOUNT", g.digits(g.r.choice([11, 12, 14])))
    d.add("   IFSC: ")
    d.pii("IFSC", g.r.choice(bank["ifsc"]))
    d.add("\n")
    for _ in range(g.r.randint(2, 3)):
        d.add(f"{g.r.randint(10, 28)}/0{g.r.randint(1, 9)}/2026  NEFT/{g.digits(12)}/")
        d.pii(
            "UPI_ID",
            f"{g.r.choice(ROMAN_FIRST).lower()}{g.digits(2)}@{g.r.choice(['okhdfcbank', 'okicici', 'ybl', 'axl'])}",
        )
        d.add(f"  {g.r.randint(100, 99999)}.00\n")


def _spaced(s: str) -> str:
    return " ".join(ch for ch in s if ch != " ")


def obfuscated(g: GenV1, d: Doc) -> None:
    kind = g.r.choice(
        ["spaced", "dotted", "zero-width", "homoglyph-pan", "pan-hyphen", "digit-words", "ocr", "fullwidth"]
    )
    d.noise.append(f"obf-{kind}")
    a = g.aadhaar()
    d.add("Customer note: aadhaar ")
    if kind == "spaced":
        d.pii("AADHAAR", _spaced(a))
    elif kind == "dotted":
        d.pii("AADHAAR", g.group(a, (4, 4, 4), "."))
    elif kind == "zero-width":
        d.pii("AADHAAR", "​".join(g.group(a, (4, 4, 4), " ").split(" ")))
    elif kind == "digit-words":
        d.pii("AADHAAR", " ".join(DIGIT_WORDS[int(c)] for c in a))
    elif kind == "ocr":
        d.pii("AADHAAR", g.ocr(g.group(a, (4, 4, 4), " "), rate=0.35))
    elif kind == "fullwidth":
        d.pii("AADHAAR", g.group(a, (4, 4, 4), " ").translate(str.maketrans("0123456789", "０１２３４５６７８９")))
    else:
        d.pii("AADHAAR", g.group(a, (4, 4, 4), " "))
    d.add(". PAN ")
    p = g.pan()
    if kind == "homoglyph-pan":
        d.pii("PAN", p.translate(CYRILLIC))
    elif kind == "pan-hyphen":
        d.pii("PAN", f"{p[:5]}-{p[5:9]}-{p[9]}".lower())
    else:
        d.pii("PAN", p)
    d.add(".")


def look_alikes(g: GenV1, d: Doc) -> None:
    d.hard_negative = True
    lines = [
        f"Order ID {g.any_12()} shipped via AWB {g.any_12()}.",
        f"UTR {g.digits(12)} credited; txn id {g.mobile()} reversed.",
        f"Invoice INV-{g.digits(4)}-{g.digits(6)}, PNR {g.digits(10)}, IMEI {g.digits(15)}.",
        f"Booking reference {g.not_aadhaar_12()}, batch {g.digits(10)}, serial {g.digits(16)}.",
        f"Ticket #{g.digits(7)} escalated; tracking {g.digits(12)}.",
    ]
    d.add(" ".join(g.r.sample(lines, k=3)))


SLICES: dict[str, Callable[[GenV1, Doc], None]] = {
    "structured_en": structured_en,
    "hinglish": hinglish,
    "indic_script": indic_script,
    "bank_real": bank_real,
    "obfuscated": obfuscated,
    "look_alikes": look_alikes,
}


def generate_v1(per_slice: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    g = GenV1(rng)
    docs = []
    for name, fn in SLICES.items():
        for i in range(per_slice):
            d = Doc(id=f"v1-{name}-{i:04d}", domain=name)
            fn(g, d)
            row = d.to_json()
            row["slice"] = name
            docs.append(row)
    return docs
