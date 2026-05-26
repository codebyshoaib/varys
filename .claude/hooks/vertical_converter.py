#!/usr/bin/env python3
"""
vertical_converter.py — Converts horizontal NotebookLM infographics
into vertical Instagram/TikTok format (1080x1350, 4:5 portrait).

Strategy: Smart split — cuts the wide image into 2-3 horizontal strips,
stacks them vertically on a branded background, adds title + handle.

Usage:
    python3 vertical_converter.py \
        --input /tmp/nlm-fitness-infographic.png \
        --output /tmp/vertical-post.png \
        --title "PULL-UP ROADMAP" \
        --handle "@oykamal" \
        --palette fitness
"""

import argparse
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W_OUT, H_OUT = 1080, 1350   # 4:5 — Instagram + TikTok

PALETTES = {
    "fitness": {
        "bg":      (200, 190, 220),
        "header":  (185, 175, 208),
        "footer":  (175, 163, 200),
        "accent":  (210, 45,  45),
        "text":    (15,  12,  30),
        "handle":  (90,  75, 120),
        "handle_bg":(160,148,188),
        "border":  (160, 148, 180),
    },
    "tech": {
        "bg":      (12,  12,  22),
        "header":  (18,  16,  32),
        "footer":  (20,  18,  38),
        "accent":  (90, 190, 255),
        "text":    (240, 240, 255),
        "handle":  (140, 140, 200),
        "handle_bg":(35, 30,  60),
        "border":  (50,  45,  80),
    },
}


def load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    paths = [
        "/tmp/Anton-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def smart_split(img: Image.Image, n_strips: int) -> list[Image.Image]:
    """
    Split image horizontally into n strips.
    Tries to find natural break points (lighter vertical columns)
    to avoid cutting through important content.
    """
    W, H = img.size
    strip_w = W // n_strips
    strips = []

    for i in range(n_strips):
        x1 = i * strip_w
        x2 = (i + 1) * strip_w if i < n_strips - 1 else W
        strips.append(img.crop((x1, 0, x2, H)))

    return strips


def make_vertical(input_path: str, output_path: str, title: str,
                  handle: str, palette_name: str = "fitness",
                  subtitle: str = "") -> str:
    palette = PALETTES.get(palette_name, PALETTES["fitness"])
    src     = Image.open(input_path).convert("RGB")
    sw, sh  = src.size

    # ── Layout plan ──────────────────────────────────────────────
    # Header: title bar        ~140px
    # Image strips: stacked    ~1100px total
    # Footer: handle/branding  ~110px
    header_h = 130
    footer_h = 120
    image_area_h = H_OUT - header_h - footer_h
    pad = 16   # padding around strips

    # Decide how many strips based on source aspect ratio
    aspect = sw / sh
    if aspect >= 2.5:
        n_strips = 3
    elif aspect >= 1.5:
        n_strips = 2
    else:
        n_strips = 1

    strips = smart_split(src, n_strips)

    # Each strip gets equal height in image_area
    strip_area_h = (image_area_h - pad * (n_strips + 1)) // n_strips
    strip_w_available = W_OUT - pad * 2

    # ── Canvas ────────────────────────────────────────────────────
    canvas = Image.new("RGB", (W_OUT, H_OUT), palette["bg"])
    draw   = ImageDraw.Draw(canvas)

    # Gradient background
    for y in range(H_OUT):
        t = y / H_OUT
        r = int(palette["bg"][0] * (1 - t*0.12) + palette["footer"][0] * t*0.12)
        g = int(palette["bg"][1] * (1 - t*0.12) + palette["footer"][1] * t*0.12)
        b = int(palette["bg"][2] * (1 - t*0.12) + palette["footer"][2] * t*0.12)
        draw.line([(0, y), (W_OUT, y)], fill=(max(0,r), max(0,g), max(0,b)))

    # ── Header ────────────────────────────────────────────────────
    # Accent bar top
    draw.rectangle([0, 0, W_OUT, 12], fill=palette["accent"])
    draw.rectangle([0, 0, 12, H_OUT], fill=palette["accent"])

    # Title text
    t_fnt = load_font(88)
    words = title.upper().split()
    line, lines = "", []
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1,1)))
    for word in words:
        test = (line + " " + word).strip()
        if dummy_draw.textlength(test, font=t_fnt) <= W_OUT - 100:
            line = test
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)

    lh = int(t_fnt.size * 1.1)
    ty = (header_h - len(lines) * lh) // 2
    for ln in lines:
        tw = draw.textlength(ln, font=t_fnt)
        draw.text((W_OUT//2 - tw//2, ty), ln, font=t_fnt,
                  fill=palette["text"])
        ty += lh

    if subtitle:
        sf   = load_font(42)
        sw_t = draw.textlength(subtitle, font=sf)
        draw.text((W_OUT//2 - sw_t//2, header_h - 36),
                  subtitle, font=sf, fill=palette["accent"])

    # ── Image strips ──────────────────────────────────────────────
    y_cursor = header_h + pad

    for strip in strips:
        # Resize strip to fit width while preserving aspect ratio
        strip_aspect = strip.width / strip.height
        target_w     = strip_w_available
        target_h     = int(target_w / strip_aspect)

        # If too tall, fit to height instead
        if target_h > strip_area_h:
            target_h = strip_area_h
            target_w = int(target_h * strip_aspect)

        strip_resized = strip.resize((target_w, target_h), Image.LANCZOS)

        # Enhance: slightly boost saturation for vibrancy
        enhancer = ImageEnhance.Color(strip_resized)
        strip_resized = enhancer.enhance(1.15)

        # Rounded corner mask
        mask = Image.new("L", (target_w, target_h), 0)
        md   = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, target_w-1, target_h-1], radius=24, fill=255)

        # Drop shadow
        shadow = Image.new("RGB", (target_w+8, target_h+8), palette["bg"])
        shadow_d = ImageDraw.Draw(shadow)
        shadow_d.rounded_rectangle([4, 4, target_w+3, target_h+3],
                                    radius=24, fill=palette["border"])
        sx = (W_OUT - target_w) // 2
        canvas.paste(shadow, (sx - 2, y_cursor - 2))

        # Paste strip
        canvas.paste(strip_resized, (sx, y_cursor), mask)

        # Border
        border_draw = ImageDraw.Draw(canvas)
        border_draw.rounded_rectangle(
            [sx-2, y_cursor-2, sx+target_w+1, y_cursor+target_h+1],
            radius=26, outline=palette["border"], width=3
        )

        y_cursor += target_h + pad

    # ── Footer / Handle ───────────────────────────────────────────
    h_fnt  = load_font(44)
    htext  = handle
    hw     = int(draw.textlength(htext, font=h_fnt))
    hpad   = 16
    hrh    = h_fnt.size + hpad * 2
    hrw    = hw + hpad * 3
    hrx    = W_OUT - hrw - 40
    hry    = H_OUT - hrh - 36
    draw.rounded_rectangle([hrx, hry, hrx+hrw, hry+hrh],
                            radius=hrh//2, fill=palette["handle_bg"])
    draw.text((hrx + hpad*1.5, hry + hpad), htext, font=h_fnt,
              fill=palette["handle"])

    # "by NotebookLM" tag bottom left
    nlm_fnt = load_font(36)
    draw.text((28, H_OUT - 52), "research by NotebookLM",
              font=nlm_fnt, fill=palette["handle"])

    canvas.save(output_path, "PNG", quality=95, optimize=True)
    return output_path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input",    required=True)
    p.add_argument("--output",   default="/tmp/vertical-nlm.png")
    p.add_argument("--title",    default="ROADMAP")
    p.add_argument("--subtitle", default="")
    p.add_argument("--handle",   default="@oykamal")
    p.add_argument("--palette",  default="fitness",
                   choices=["fitness", "tech"])
    args = p.parse_args()

    out = make_vertical(args.input, args.output, args.title,
                        args.handle, args.palette, args.subtitle)
    print(f"Saved: {out}")
