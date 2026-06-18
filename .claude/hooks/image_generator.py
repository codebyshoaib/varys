#!/usr/bin/env python3
"""
image_generator.py — Vertical social media image generator.

Produces Instagram/TikTok-ready 1080x1350 images (4:5 portrait).
Inspired by @trainwithkale style: bold Impact/Anton font, split panels,
soft lavender bg for fitness, dark bg for tech.

Post types:
  qa      — Split panel: question top, answer bottom (most viral format)
  steps   — Numbered progression list with circles
  info    — Title + numbered tips (great for tech carousels)
  tip     — Single bold tip with context

Usage:
  python3 image_generator.py --type qa \
      --question "BEST PULL EXERCISE?" --answer "DEAD HANG" \
      --handle "@shoaib" --palette fitness --output /tmp/post.png
"""

import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sys as _sys, time as _time
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
try:
    import varys_log as _k
except Exception:
    _k = None

# ─── Fonts ────────────────────────────────────────────────────────────────────

FONT_PATHS = {
    "heavy":  ["/tmp/Anton-Regular.ttf",
               "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    "bold":   ["/tmp/Oswald-Bold.ttf",
               "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    "regular":["/usr/share/fonts/truetype/freefont/FreeSans.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
}

def font(style: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS.get(style, FONT_PATHS["bold"]):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

# ─── Palettes ─────────────────────────────────────────────────────────────────

PALETTES = {
    "fitness": {
        "bg_top":    (200, 190, 220),   # soft lavender top
        "bg_bot":    (175, 163, 200),   # deeper lavender bottom
        "divider":   (140, 128, 170),
        "text_q":    (15,  12,  30),    # near black for question
        "text_a":    (15,  12,  30),    # near black for answer
        "accent":    (210, 45,  45),    # red accent bar + numbers
        "tag":       (90,  75, 120),    # handle colour
        "tag_bg":    (160, 148, 188),   # handle pill bg
        "tip_bg":    (185, 175, 210),   # card bg
    },
    "tech": {
        "bg_top":    (12,  12,  22),
        "bg_bot":    (20,  18,  38),
        "divider":   (50,  45,  80),
        "text_q":    (240, 240, 255),
        "text_a":    (90, 190, 255),    # blue for answer
        "accent":    (90, 190, 255),
        "tag":       (140, 140, 200),
        "tag_bg":    (35,  30,  60),
        "tip_bg":    (25,  22,  45),
    },
    "purple": {
        "bg_top":    (88,  50, 160),
        "bg_bot":    (55,  25, 110),
        "divider":   (120, 80, 200),
        "text_q":    (255, 255, 255),
        "text_a":    (255, 220, 80),    # gold for answer
        "accent":    (255, 200, 50),
        "tag":       (200, 180, 255),
        "tag_bg":    (70,  40, 130),
        "tip_bg":    (75,  42, 145),
    },
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

W, H = 1080, 1350  # 4:5 portrait — Instagram + TikTok perfect

def new_canvas(palette: dict) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img  = Image.new("RGBA", (W, H), palette["bg_top"])
    draw = ImageDraw.Draw(img)
    # Vertical gradient: draw top→bottom bands
    for y in range(H):
        t   = y / H
        r   = int(palette["bg_top"][0] * (1-t) + palette["bg_bot"][0] * t)
        g   = int(palette["bg_top"][1] * (1-t) + palette["bg_bot"][1] * t)
        b   = int(palette["bg_top"][2] * (1-t) + palette["bg_bot"][2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img, draw

def wrap(text: str, fnt: ImageFont.FreeTypeFont,
         max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = (line + " " + word).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            line = test
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    return lines or [""]

def draw_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont,
              color: tuple, cx: int, cy: int, max_w: int,
              align: str = "center", stroke: int = 0,
              stroke_color: tuple = (0, 0, 0)) -> int:
    """Draw text block centred at (cx, cy). Returns bottom Y."""
    lines  = wrap(text, fnt, max_w, draw)
    lh     = int(fnt.size * 1.15)
    total  = len(lines) * lh
    y      = cy - total // 2

    for line in lines:
        w = draw.textlength(line, font=fnt)
        x = {"center": cx - w//2, "left": cx, "right": cx - w}.get(align, cx - w//2)
        if stroke:
            draw.text((x, y), line, font=fnt,
                      fill=stroke_color, stroke_width=stroke, stroke_fill=stroke_color)
        draw.text((x, y), line, font=fnt, fill=color)
        y += lh
    return y

def draw_handle(draw: ImageDraw.ImageDraw, handle: str, palette: dict):
    """Bottom-right handle pill."""
    fnt = font("bold", 38)
    tw  = int(draw.textlength(handle, font=fnt))
    pad = 18
    rh  = fnt.size + pad * 2
    rw  = tw + pad * 3
    rx  = W - rw - 40
    ry  = H - rh - 40
    # Pill
    draw.rounded_rectangle([rx, ry, rx+rw, ry+rh], radius=rh//2,
                            fill=(*palette["tag_bg"][:3], 200))
    draw.text((rx + pad*1.5, ry + pad), handle, font=fnt, fill=palette["tag"])

def draw_accent_bar(draw: ImageDraw.ImageDraw, palette: dict, side: str = "left"):
    """Accent colour bar on edge."""
    if side == "left":
        draw.rectangle([0, 0, 16, H], fill=palette["accent"])
    elif side == "top":
        draw.rectangle([0, 0, W, 18], fill=palette["accent"])
    elif side == "both":
        draw.rectangle([0, 0, 16, H], fill=palette["accent"])
        draw.rectangle([0, 0, W, 18], fill=palette["accent"])

# ─── Post types ───────────────────────────────────────────────────────────────

def make_qa(question: str, answer: str, handle: str, palette: dict) -> Image.Image:
    """
    Split-panel: bold question top half, bold answer bottom half.
    Exact @trainwithkale layout.
    """
    img, draw = new_canvas(palette)
    mid = H // 2

    # Darker bottom panel
    for y in range(mid, H):
        t  = (y - mid) / (H - mid)
        r  = int(palette["bg_top"][0] * (1 - t*0.15))
        g  = int(palette["bg_top"][1] * (1 - t*0.15))
        b  = int(palette["bg_top"][2] * (1 - t*0.08))
        draw.line([(0, y), (W, y)], fill=(max(0,r), max(0,g), max(0,b)))

    # Divider
    draw.rectangle([0, mid-4, W, mid+4], fill=palette["divider"])

    # Question — giant Anton, top panel
    q_fnt = font("heavy", 148)
    draw_text(draw, question, q_fnt, palette["text_q"],
              cx=W//2, cy=mid//2, max_w=W-100, stroke=4,
              stroke_color=(0,0,0) if palette["text_q"][0] > 100 else (255,255,255))

    # Answer — even bigger, bottom panel
    a_fnt = font("heavy", 170)
    draw_text(draw, answer, a_fnt, palette["text_a"],
              cx=W//2, cy=mid + (H-mid)//2, max_w=W-60, stroke=5,
              stroke_color=(0,0,0) if palette["text_a"][0] > 100 else (20,20,20))

    draw_accent_bar(draw, palette, "left")
    draw_handle(draw, handle, palette)
    return img.convert("RGB")


def make_steps(title: str, steps: list[str], handle: str,
               palette: dict, subtitle: str = "") -> Image.Image:
    """Numbered progression steps with accent circles."""
    img, draw = new_canvas(palette)
    draw_accent_bar(draw, palette, "left")

    # Title
    t_fnt  = font("heavy", 110)
    title_bottom = draw_text(draw, title, t_fnt, palette["text_q"],
                              cx=W//2, cy=140, max_w=W-130, stroke=3,
                              stroke_color=(0,0,0) if palette["text_q"][0]>100 else (255,255,255))

    if subtitle:
        s_fnt = font("bold", 52)
        draw.text((W//2, title_bottom+14), subtitle, font=s_fnt,
                  fill=palette["accent"], anchor="mt")
        title_bottom += 70

    # Thick accent line under title
    lx = 70
    draw.rectangle([lx, title_bottom+22, W-lx, title_bottom+30],
                   fill=palette["accent"])

    # Steps
    n   = len(steps)
    avail = H - title_bottom - 130
    step_h = avail // max(n, 1)
    y     = title_bottom + 58
    s_fnt = font("bold", 60)
    n_fnt = font("heavy", 64)

    for i, step in enumerate(steps, 1):
        mid_y = y + step_h // 2
        # Circle
        cr = 48
        cx = 88
        # Shadow circle
        draw.ellipse([cx-cr+3, mid_y-cr+3, cx+cr+3, mid_y+cr+3],
                     fill=(*palette["divider"], 120))
        draw.ellipse([cx-cr, mid_y-cr, cx+cr, mid_y+cr],
                     fill=palette["accent"])
        nw = draw.textlength(str(i), font=n_fnt)
        draw.text((cx - nw//2, mid_y - n_fnt.size//2),
                  str(i), font=n_fnt, fill=(255,255,255))

        # Step text
        lines = wrap(step, s_fnt, W - 200, draw)
        lh    = int(s_fnt.size * 1.2)
        ty    = mid_y - (len(lines) * lh)//2
        for ln in lines:
            draw.text((155, ty), ln, font=s_fnt, fill=palette["text_q"])
            ty += lh

        # Connector
        if i < n and step_h > 2 * cr:
            draw.rectangle([cx-4, mid_y+cr, cx+4, mid_y+step_h-cr],
                           fill=palette["divider"])
        y += step_h

    draw_handle(draw, handle, palette)
    return img.convert("RGB")


def make_info(title: str, points: list[str], handle: str,
              palette: dict, subtitle: str = "") -> Image.Image:
    """Bold title + numbered tips. Great for tech content."""
    img, draw = new_canvas(palette)
    draw_accent_bar(draw, palette, "both")

    # Title
    t_fnt = font("heavy", 118)
    ty    = draw_text(draw, title, t_fnt, palette["text_q"],
                       cx=W//2, cy=155, max_w=W-130, stroke=3,
                       stroke_color=(0,0,0) if palette["text_q"][0]>100 else (30,30,30))

    if subtitle:
        sf = font("bold", 50)
        draw.text((W//2, ty+16), subtitle, font=sf,
                  fill=palette["accent"], anchor="mt")
        ty += 72

    # Divider
    draw.rectangle([60, ty+26, W-60, ty+34], fill=palette["accent"])

    # Points
    n      = len(points)
    avail  = H - ty - 120
    item_h = avail // max(n, 1)
    y      = ty + 60
    p_fnt  = font("bold", 54)
    i_fnt  = font("heavy", 56)

    for i, point in enumerate(points, 1):
        mid_y = y + item_h//2

        # Number badge
        bw, bh = 72, 72
        bx = 56
        draw.rounded_rectangle([bx, mid_y-bh//2, bx+bw, mid_y+bh//2],
                                radius=14, fill=palette["accent"])
        nw = draw.textlength(str(i), font=i_fnt)
        draw.text((bx + bw//2 - nw//2, mid_y - i_fnt.size//2),
                  str(i), font=i_fnt, fill=(255, 255, 255))

        # Point text
        lines = wrap(point, p_fnt, W - 190, draw)
        lh    = int(p_fnt.size * 1.18)
        ty2   = mid_y - (len(lines) * lh)//2
        for ln in lines:
            draw.text((148, ty2), ln, font=p_fnt, fill=palette["text_q"])
            ty2 += lh

        # Thin separator
        if i < n:
            sep_y = y + item_h - 8
            draw.rectangle([56, sep_y, W-56, sep_y+2],
                           fill=(*palette["divider"], 100))
        y += item_h

    draw_handle(draw, handle, palette)
    return img.convert("RGB")


def make_tip(tip: str, context: str, handle: str, palette: dict) -> Image.Image:
    """Single bold tip with context line. Very shareable."""
    img, draw = new_canvas(palette)
    draw_accent_bar(draw, palette, "left")

    # Large quote mark
    q_fnt = font("heavy", 300)
    draw.text((50, -30), "“", font=q_fnt,
              fill=(*palette["accent"][:3], 60))

    # Tip text — massive
    t_fnt = font("heavy", 120)
    ty    = draw_text(draw, tip, t_fnt, palette["text_q"],
                       cx=W//2, cy=H//2 - 60, max_w=W-120, stroke=3,
                       stroke_color=(0,0,0) if palette["text_q"][0]>100 else (30,30,30))

    # Context
    if context:
        c_fnt = font("bold", 52)
        draw.text((W//2, ty + 40), context, font=c_fnt,
                  fill=palette["accent"], anchor="mt")

    # Bottom accent line
    draw.rectangle([80, H-130, W-80, H-122], fill=palette["accent"])

    draw_handle(draw, handle, palette)
    return img.convert("RGB")


# ─── Entry point ──────────────────────────────────────────────────────────────

def generate(post_type: str, output: str, palette_name: str = "fitness",
             handle: str = "@shoaib", question: str = "", answer: str = "",
             title: str = "", subtitle: str = "", tip: str = "", context: str = "",
             steps: list = None, points: list = None) -> str:
    palette = PALETTES.get(palette_name, PALETTES["fitness"])
    if post_type == "qa":
        img = make_qa(question.upper(), answer.upper(), handle, palette)
    elif post_type == "steps":
        img = make_steps(title.upper(), steps or [], handle, palette, subtitle)
    elif post_type == "info":
        img = make_info(title.upper(), points or [], handle, palette, subtitle)
    elif post_type == "tip":
        img = make_tip(tip, context, handle, palette)
    else:
        raise ValueError(f"Unknown type: {post_type}")
    img.save(output, "PNG", quality=95, optimize=True)
    return output


if __name__ == "__main__":
    _t0 = _time.time()
    try:
        p = argparse.ArgumentParser()
        p.add_argument("--type",     default="qa",
                       choices=["qa","steps","info","tip"])
        p.add_argument("--question", default="")
        p.add_argument("--answer",   default="")
        p.add_argument("--title",    default="")
        p.add_argument("--subtitle", default="")
        p.add_argument("--tip",      default="")
        p.add_argument("--context",  default="")
        p.add_argument("--steps",    default="")
        p.add_argument("--points",   default="")
        p.add_argument("--handle",   default="@shoaib")
        p.add_argument("--palette",  default="fitness",
                       choices=["fitness","tech","purple"])
        p.add_argument("--output",   default="/tmp/social-post.png")
        args = p.parse_args()

        out = generate(
            post_type    = args.type,
            output       = args.output,
            palette_name = args.palette,
            handle       = args.handle,
            question     = args.question,
            answer       = args.answer,
            title        = args.title,
            subtitle     = args.subtitle,
            tip          = args.tip,
            context      = args.context,
            steps        = [s.strip() for s in args.steps.split(",") if s.strip()],
            points       = [s.strip() for s in args.points.split(",") if s.strip()],
        )
        print(f"Saved: {out}")
        if _k: _k.klog_cron("image-generator", status="ok", duration_ms=(_time.time()-_t0)*1000)
    except Exception as _e:
        if _k: _k.klog_error("image-generator-main", _e, component="image-generator", severity="ERROR")
        raise
