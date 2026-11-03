"""Generates a 1200x630 social card for every blog post, at apps/website/assets/og/<slug>.png.

The site build picks a post's card up automatically for og:image.

    python scripts/make_og_posts.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from make_brand_assets import GREY, INK, SS, VIOLET, VIOLET_TINT, WHITE, Image, ImageDraw, _rgb, draw_mark, font

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "apps/website/src/pages/blog"
OUT = ROOT / "apps/website/assets/og"


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=f) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def card(title: str, kind: str, date: str) -> Image.Image:
    W, H, s = 1200, 630, SS
    img = Image.new("RGBA", (W * s, H * s), _rgb(WHITE))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 16 * s, H * s], fill=_rgb(VIOLET))
    pad = 84 * s
    draw_mark(img, pad, 64 * s, 56 * s)
    d.text((pad + 70 * s, 70 * s), "safearly", font=font("semibold", 38 * s), fill=_rgb(INK))
    tag = font("semibold", 24 * s)
    label = f"{kind.upper()}  ·  {date}"
    tw = d.textlength(label, font=tag)
    d.rounded_rectangle([pad, 168 * s, pad + tw + 40 * s, 214 * s], radius=23 * s, fill=_rgb(VIOLET_TINT))
    d.text((pad + 20 * s, 177 * s), label, font=tag, fill=_rgb(VIOLET))
    size = 64
    while True:
        f = font("bold", size * s)
        lines = wrap(d, title, f, W * s - 2 * pad)
        if len(lines) <= 3 or size <= 44:
            break
        size -= 4
    y = 250 * s
    for ln in lines[:3]:
        d.text((pad, y), ln, font=f, fill=_rgb(INK))
        y += int(size * 1.18) * s
    d.text((pad, 548 * s), "safearly.com/blog  ·  Smriti, open-source institutional memory", font=font("regular", 24 * s), fill=_rgb(GREY))
    return img.resize((W, H), Image.LANCZOS).convert("RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(POSTS.glob("*.html")):
        m = re.match(r"<!--page (\{.*?\}) -->", p.read_text(encoding="utf-8"), re.S)
        meta = json.loads(m.group(1))
        post = meta["post"]
        y, mo, da = post["date"].split("-")
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        card(post["title"], post["type"], f"{int(da)} {months[int(mo) - 1]} {y}").save(OUT / f"{p.stem}.png", optimize=True)
        n += 1
    print(f"wrote {n} cards to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
