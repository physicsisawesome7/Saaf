#!/usr/bin/env python3
"""Generate every Safearly / Saaf brand asset from one set of shapes.

    python scripts/make_brand_assets.py

Mark concept: "the sun behind the bar"
  * a saffron sun (early) partly hidden behind a green rounded bar (safe),
  * the bar is the redaction mask Saaf puts over a value; the sun is still
    recognisable, the way a masked prompt is still useful,
  * the sun sits mostly above the bar (rising) with a sliver below, so it
    reads as *behind* the mask, not resting on it,
  * two shapes, two flat colours, no container, so it reads at 16 px.
The Saaf product mark reuses the same pill inside brackets: [▬], a token.

Writes SVG logos, favicons, app icons, the social card and the
browser-extension icons. PNGs are drawn with Pillow at 4x and downsampled.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "apps" / "website"
BRAND = SITE / "assets" / "brand"
EXT_ICONS = ROOT / "plugins" / "browser-extension" / "icons"

# Palette v2: white, black and violet (keep in sync with docs/brand.md and apps/website/assets/styles.css).
# GREEN and SAFFRON keep their names for the mark's two parts: the bar (now black) and the sun (now violet).
GREEN = "#0A0A0A"
SAFFRON = "#7C3AED"
VIOLET = "#6D28D9"
VIOLET_TINT = "#F5F3FF"
INK = "#0A0A0A"
GREY = "#52525B"
WHITE = "#FFFFFF"

FONT_STACK = "'Google Sans', 'Segoe UI', Inter, system-ui, -apple-system, Roboto, Arial, sans-serif"

# Geometry in a 100-unit box.
SUN_C, SUN_R = (50, 47), 29  # full disc; the bar hides a band of it
BAR = (11, 52, 89, 65)  # pill wider than the sun (height 13, radius 6.5)
GAP = 4  # clear space between the bar and the visible parts of the sun
BRACKET_W = 9


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------


def mark_body(x: float = 0, y: float = 0, s: float = 100, uid: str = "m") -> str:
    k = s / 100
    cx, cy = SUN_C
    x0, y0, x1, y1 = BAR
    return (
        f'<g transform="translate({x} {y}) scale({k})">'
        f'<defs><clipPath id="{uid}"><rect x="0" y="0" width="100" height="{y0 - GAP}"/>'
        f'<rect x="0" y="{y1 + GAP}" width="100" height="{100 - y1 - GAP}"/></clipPath></defs>'
        f'<circle cx="{cx}" cy="{cy}" r="{SUN_R}" fill="{SAFFRON}" clip-path="url(#{uid})"/>'
        f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="{(y1 - y0) / 2}" fill="{GREEN}"/>'
        "</g>"
    )


def saaf_body(x: float = 0, y: float = 0, s: float = 100) -> str:
    k = s / 100
    return (
        f'<g transform="translate({x} {y}) scale({k})" fill="none" stroke="{GREEN}" stroke-width="{BRACKET_W}" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M30 22 H18 V78 H30"/><path d="M70 22 H82 V78 H70"/>'
        f'<rect x="34" y="43" width="32" height="14" rx="7" fill="{SAFFRON}" stroke="none"/>'
        "</g>"
    )


def svg(w: float, h: float, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-label="{title}"><title>{title}</title>{body}</svg>\n'
    )


def wordmark(x: float, y: float, size: float, text: str, color: str, weight: int = 600) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{FONT_STACK}" font-size="{size}" font-weight="{weight}" '
        f'letter-spacing="-0.02em" fill="{color}">{text}</text>'
    )


def write_svgs() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    (BRAND / "safearly-mark.svg").write_text(svg(100, 100, mark_body(), "Safearly"), encoding="utf-8")
    (BRAND / "saaf-mark.svg").write_text(svg(100, 100, saaf_body(), "Saaf"), encoding="utf-8")
    for name, color in (("safearly-logo.svg", INK), ("safearly-logo-light.svg", WHITE)):
        body = mark_body(0, 0, 56) + wordmark(62, 38, 32, "safearly", color)
        (BRAND / name).write_text(svg(200, 56, body, "Safearly"), encoding="utf-8")
    lockup = saaf_body(0, 0, 56) + wordmark(62, 36, 30, "Saaf", INK) + wordmark(129, 36, 15, "by Safearly", GREY, 500)
    (BRAND / "saaf-lockup.svg").write_text(svg(220, 56, lockup, "Saaf by Safearly"), encoding="utf-8")
    (SITE / "favicon.svg").write_text(svg(100, 100, mark_body(), "Safearly"), encoding="utf-8")


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------

SS = 4


def _rgb(hex_: str, a: int = 255) -> tuple[int, int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


def draw_mark(img: Image.Image, x: float, y: float, s: float) -> None:
    k = s / 100
    cx, cy = SUN_C
    x0, y0, x1, y1 = BAR
    sun = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sun)
    sd.ellipse(
        [x + (cx - SUN_R) * k, y + (cy - SUN_R) * k, x + (cx + SUN_R) * k, y + (cy + SUN_R) * k], fill=_rgb(SAFFRON)
    )
    sd.rectangle([x, y + (y0 - GAP) * k, x + s, y + (y1 + GAP) * k], fill=(0, 0, 0, 0))  # band behind the bar
    img.alpha_composite(sun)
    ImageDraw.Draw(img).rounded_rectangle(
        [x + x0 * k, y + y0 * k, x + x1 * k, y + y1 * k], radius=(y1 - y0) / 2 * k, fill=_rgb(GREEN)
    )


def draw_saaf(img: Image.Image, x: float, y: float, s: float) -> None:
    k = s / 100
    d = ImageDraw.Draw(img)
    w = BRACKET_W * k
    for pts in (((30, 22), (18, 22), (18, 78), (30, 78)), ((70, 22), (82, 22), (82, 78), (70, 78))):
        p = [(x + px * k, y + py * k) for px, py in pts]
        d.line(p, fill=_rgb(GREEN), width=round(w), joint="curve")
        for cx, cy in p:
            d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=_rgb(GREEN))
    d.rounded_rectangle([x + 34 * k, y + 43 * k, x + 66 * k, y + 57 * k], radius=7 * k, fill=_rgb(SAFFRON))


def icon(size: int, drawer, *, pad: float = 0.0, tile: bool = False) -> Image.Image:
    """Transparent mark, or (tile=True) a white rounded tile, Google-style."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    if tile:
        ImageDraw.Draw(img).rounded_rectangle([0, 0, big - 1, big - 1], radius=big * 0.22, fill=_rgb(WHITE))
    inset = big * pad
    drawer(img, inset, inset, big - 2 * inset)
    return img.resize((size, size), Image.LANCZOS)


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    dejavu = "/usr/share/fonts/truetype/dejavu/"
    candidates = {
        "bold": ["C:/Windows/Fonts/segoeuib.ttf", dejavu + "DejaVuSans-Bold.ttf"],
        "semibold": ["C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/segoeuib.ttf", dejavu + "DejaVuSans-Bold.ttf"],
        "regular": ["C:/Windows/Fonts/segoeui.ttf", dejavu + "DejaVuSans.ttf"],
        "mono": ["C:/Windows/Fonts/consola.ttf", dejavu + "DejaVuSansMono.ttf"],
    }[weight]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default(size)


def centered(d: ImageDraw.ImageDraw, cx: float, y: float, text: str, f, fill) -> None:
    d.text((cx - d.textlength(text, font=f) / 2, y), text, font=f, fill=fill)


def og_image() -> Image.Image:
    W, H, s = 1200, 630, SS
    img = Image.new("RGBA", (W * s, H * s), _rgb(WHITE))
    d = ImageDraw.Draw(img)
    f_word = font("semibold", 54 * s)
    word_w = d.textlength("safearly", font=f_word)
    mark = 84 * s
    total = mark + 18 * s + word_w
    x0 = (W * s - total) / 2
    draw_mark(img, x0, 92 * s, mark)
    d.text((x0 + mark + 18 * s, 104 * s), "safearly", font=f_word, fill=_rgb(INK))
    centered(d, W * s / 2, 238 * s, "AI safety & trust, built in India.", font("bold", 64 * s), _rgb(INK))
    sub = font("regular", 30 * s)
    centered(d, W * s / 2, 345 * s, "Open-source guardrails, benchmarks and research for teams", sub, _rgb(GREY))
    centered(d, W * s / 2, 387 * s, "putting LLMs and AI agents to work on real Indian data.", sub, _rgb(GREY))
    chips = [("2345 6789 0124", "[AADHAAR_1]"), ("ABCPE1234F", "[PAN_1]")]
    f = font("mono", 28 * s)
    widths = [
        (d.textlength(raw, font=f) + 40 * s, d.textlength("→", font=f) + 28 * s, d.textlength(tok, font=f) + 40 * s)
        for raw, tok in chips
    ]
    row = sum(a + b + c for a, b, c in widths) + 56 * s
    x, y = (W * s - row) / 2, 476 * s
    for (raw, tok), (wa, wb, wc) in zip(chips, widths, strict=True):
        d.rounded_rectangle([x, y, x + wa, y + 56 * s], radius=28 * s, fill=_rgb(VIOLET_TINT))
        d.text((x + 20 * s, y + 11 * s), raw, font=f, fill=_rgb(INK))
        x += wa
        d.text((x + 14 * s, y + 11 * s), "→", font=f, fill=_rgb(GREY))
        x += wb
        d.rounded_rectangle([x, y, x + wc, y + 56 * s], radius=28 * s, fill=_rgb(VIOLET))
        d.text((x + 20 * s, y + 11 * s), tok, font=f, fill=_rgb(WHITE))
        x += wc + 56 * s
    return img.resize((W, H), Image.LANCZOS).convert("RGB")


def write_pngs() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    EXT_ICONS.mkdir(parents=True, exist_ok=True)
    icon(32, draw_mark).save(SITE / "favicon-32.png")
    icon(180, draw_mark, pad=0.14, tile=True).save(SITE / "apple-touch-icon.png")
    icon(192, draw_mark, pad=0.14, tile=True).save(BRAND / "icon-192.png")
    icon(512, draw_mark, pad=0.14, tile=True).save(BRAND / "icon-512.png")
    icon(512, draw_mark, pad=0.22, tile=True).save(BRAND / "icon-maskable-512.png")
    icon(512, draw_mark).save(BRAND / "safearly-mark-512.png")
    icon(512, draw_saaf).save(BRAND / "saaf-mark-512.png")
    icon(256, draw_mark).save(SITE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    for n in (16, 32, 48, 128):
        icon(n, draw_saaf).save(EXT_ICONS / f"saaf-{n}.png")
    og_image().save(BRAND / "og-image.png", optimize=True)


if __name__ == "__main__":
    write_svgs()
    write_pngs()
    print("brand assets written to", BRAND.relative_to(ROOT))
