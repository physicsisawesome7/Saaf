"""Regenerate the demo's binary files (xlsx, docx). Everything is synthetic.

    python packs/tenants/railways-demo/make_binaries.py

Aadhaar-format numbers are random but pass the Verhoeff check, so the
masking path is exercised exactly as it would be on real data.
"""

from __future__ import annotations

import random
from pathlib import Path

import docx
import openpyxl

HERE = Path(__file__).parent
D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_digit(num: str) -> int:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = D[c][P[(i + 1) % 8][int(ch)]]
    return INV[c]


def aadhaar(rng: random.Random) -> str:
    base = str(rng.randint(2, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(10))
    n = base + str(verhoeff_digit(base))
    return f"{n[:4]} {n[4:8]} {n[8:]}"


def land_schedule() -> None:
    rng = random.Random(17)
    names = [
        "Ram Prasad",
        "Sita Devi",
        "Mohan Lal",
        "Gurpreet Kaur",
        "Abdul Rahim",
        "Kamla Bai",
        "Suresh Kumar",
        "Lakshmi Narayan",
        "Harbans Singh",
        "Rekha Rani",
    ]
    fathers = [
        "Shiv Charan",
        "Babu Ram",
        "Kishan Lal",
        "Joginder Singh",
        "Abdul Karim",
        "Bhola Nath",
        "Ram Kumar",
        "Narayan Das",
        "Kartar Singh",
        "Prem Chand",
    ]
    villages = ["Rampur", "Rampur", "Rampur", "Kheri", "Kheri", "Sondhi", "Sondhi", "Sondhi", "Rampur", "Kheri"]
    areas = [0.412, 0.268, 0.355, 0.190, 0.522, 0.305, 0.147, 0.236, 0.481, 0.274]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Schedule P-17"
    ws.append(
        [
            "Plot No",
            "Village",
            "Khasra No",
            "Name of owner",
            "Father's name",
            "Aadhaar",
            "Area (hectare)",
            "Land category",
        ]
    )
    for i in range(10):
        ws.append(
            [
                f"P17-{i + 1:03d}",
                villages[i],
                f"{rng.randint(100, 999)}/{rng.randint(1, 9)}",
                names[i],
                fathers[i],
                aadhaar(rng),
                areas[i],
                rng.choice(["agricultural", "abadi", "barren"]),
            ]
        )
    ws.append(["", "", "", "", "", "", "=SUM(G2:G11)", "total"])
    hidden = wb.create_sheet("Working notes")
    hidden.append(["internal valuation working, not for indexing"])
    hidden.sheet_state = "hidden"
    wb.save(HERE / "corpus" / "land-schedule-p17.xlsx")


def minutes() -> None:
    d = docx.Document()
    d.core_properties.title = "Minutes of tender committee meeting, NR-DLI-ENG-2025-14 (synthetic)"
    d.add_heading("Minutes of tender committee meeting", level=1)
    d.add_paragraph(
        "Tender No. NR-DLI-ENG-2025-14. Meeting held on 28.05.2025. Synthetic document for the Smriti demo."
    )
    d.add_heading("Recommendation", level=2)
    d.add_paragraph(
        "The committee recommends acceptance of the lowest valid offer of M/s Example Infra Pvt Ltd for Rs 42.50 crore, with completion in 18 months. The offer is valid up to 31.07.2025."
    )
    d.add_paragraph(
        "The value is within the powers of the Chief Engineer (Construction). Associate Finance vetting is required as the value exceeds Rs 25 crore under the powers of acceptance letter in force."
    )
    t = d.add_table(rows=1, cols=3)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text, t.rows[0].cells[2].text = (
        "Bidder",
        "Quoted value (Rs crore)",
        "Rank",
    )
    for row in [
        ("M/s Example Infra Pvt Ltd", "42.50", "L1"),
        ("M/s Sample Constructions", "44.10", "L2"),
        ("M/s Demo Builders", "46.95", "L3"),
    ]:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = v
    d.save(HERE / "inbox" / "tc-minutes-nr-dli-eng-2025-14.docx")


if __name__ == "__main__":
    land_schedule()
    minutes()
    print("wrote corpus/land-schedule-p17.xlsx and inbox/tc-minutes-nr-dli-eng-2025-14.docx")
