#!/usr/bin/env python3
"""How often does a random number pass the Aadhaar checksum?

    python bench/scripts/verhoeff_collisions.py            # 1,000,000 samples, seed 2026
    python bench/scripts/verhoeff_collisions.py -n 200000 --seed 7

Aadhaar numbers end in a Verhoeff check digit. A check digit catches typing
errors; it does not make a number unique. This script measures how many
uniformly random 12-digit strings pass the checks a regex-plus-checksum
detector applies (the same rules as Presidio's Aadhaar recognizer: 12 digits,
first digit 2-9, Verhoeff valid, not a palindrome), and how many Indian mobile
numbers written with a "91" prefix and no separator would pass as well.
Cited in https://safearly.com/blog/checksum-is-not-enough.
"""

from __future__ import annotations

import argparse
import random

_D = [
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
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_ok(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def detector_ok(number: str) -> bool:
    return len(number) == 12 and number[0] in "23456789" and number != number[::-1] and verhoeff_ok(number)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    verhoeff = detector = 0
    for _ in range(a.n):
        s = f"{rng.randrange(10**12):012d}"
        verhoeff += verhoeff_ok(s)
        detector += detector_ok(s)

    mobiles = 0
    for _ in range(a.n):
        m = str(rng.randint(6, 9)) + f"{rng.randrange(10**9):09d}"
        mobiles += verhoeff_ok("91" + m)

    print(f"samples                          {a.n:,} (seed {a.seed})")
    print(f"random 12 digits, Verhoeff valid {100 * verhoeff / a.n:.2f}%")
    print(f"... and first digit 2-9, not a palindrome (detector rules) {100 * detector / a.n:.2f}%")
    print(f"'91' + 10-digit mobile, Verhoeff valid {100 * mobiles / a.n:.2f}%")


if __name__ == "__main__":
    main()
