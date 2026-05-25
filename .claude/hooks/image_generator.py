#!/usr/bin/env python3
"""
image_generator.py — Generates vertical social media images in the
@trainwithkale style: soft purple bg, bold black text, split panel,
question top / answer bottom.

No API keys. No external services. Runs locally with PIL.

Usage:
    python3 image_generator.py \
        --question "BEST ABS EXERCISE?" \
        --answer "HANGING LEG RAISES" \
        --handle "@oykamal" \
        --output /tmp/post.png \
        --type fitness   # or: tech, info, steps

For step-by-step posts (carousel style):
    python3 image_generator.py \
        --title "PULL-UP PROGRESSION" \
        --steps "Dead Hangs,Scapular Pulls,Negative Pull-ups,Band Assisted,Full Pull-up" \
        --handle "@oykamal" \
        --output /tmp/post.png \
        --type steps
"""

import argparse
import math
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── Colour palettes ───────────────────────────────────────────────────────────

PALETTES = {
    "fitness": {
        "bg":          (195, 185, 215),   # soft lavender (matches reference)
        "panel_top":   (195, 185, 215),
        "panel_bot":   (180, 170, 202),
        "text_main":   (10,  10,  10),
        "text_answer": (10,  10,  10),
        "accent":      (220, 50,  50),    # red accent
        "divider":     (150, 140, 175),
        "handle":      (80,  70,  100),
    },
    "tech": {
        "bg":          (15,  15,  25),    # dark
        "panel_top":   (20,  20,  35),
        "panel_bot":   (25,  25,  45),
        "text_main":   (255, 255, 255),
        "text_answer": (100, 200, 255),   # blue accent for tech
        "accent":      (100, 200, 255),
        "divider":     (50,  50,  80),
        "handle":      (150, 150, 200),
    },
    "info": {
        "bg":          (245, 245, 250),
        "panel_top":   (245, 245, 250),
        "panel_bot":   (235, 235, 245),
        "text_main":   (20,  20,  40),
        "text_answer": (20,  20,  40),
        "accent":      (80,  60,  200),
        "divider":     (200, 195, 220),
        "handle":      (100, 90,  150),
    },
}


def load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    paths = [
        "/tmp/Montserrat-Black.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.FreeTypeFont,
              max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words  = text.split()
    lines  = []
    line   = ""
    for word in words:
        test = (line + " " + word).strip()
        w    = draw.textlength(test, font=font)
        if w <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def draw_text_block(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                    color: tuple, cx: int, cy: int, max_width: int,
                    align: str = "center", shadow: bool = True) -> int:
    """Draw wrapped text centred at cx,cy. Returns bottom y."""
    lines   = wrap_text(text, font, max_width, draw)
    lh      = font.size + 8
    total_h = len(lines) * lh
    y       = cy - total_h // 2

    for line in lines:
        w = draw.textlength(line, font=font)
        if align == "center":
            x = cx - w // 2
        elif align == "left":
            x = cx
        else:
            x = cx - w

        if shadow:
            draw.text((x + 3, y + 3), line, font=font,
                      fill=(0, 0, 0, 120))
        draw.text((x, y), line, font=font, fill=color)
        y += lh

    return y


def make_qa_post(question: str, answer: str, handle: str,
                 palette: dict, size: tuple = (1080, 1350)) -> Image.Image:
    """
    Split-panel post: question on top, answer on bottom.
    Matches the @trainwithkale reference images exactly in layout.
    """
    W, H   = size
    img    = Image.new("RGB", (W, H), palette["bg"])
    draw   = ImageDraw.Draw(img)
    mid    = H // 2

    # Top panel background
    draw.rectangle([0, 0, W, mid], fill=palette["panel_top"])
    # Bottom panel (slightly darker)
    draw.rectangle([0, mid, W, H], fill=palette["panel_bot"])
    # Divider line
    draw.rectangle([0, mid - 3, W, mid + 3], fill=palette["divider"])

    # ── Question text (top panel) ─────────────────────────────
    q_font = load_font(110)
    draw_text_block(draw, question, q_font, palette["text_main"],
                    cx=W // 2, cy=mid // 2, max_width=W - 120, shadow=True)

    # ── Answer text (bottom panel) ────────────────────────────
    a_font = load_font(130)
    draw_text_block(draw, answer, a_font, palette["text_answer"],
                    cx=W // 2, cy=mid + (H - mid) // 2, max_width=W - 80, shadow=True)

    # ── Accent bar on left edge ───────────────────────────────
    draw.rectangle([0, 0, 12, H], fill=palette["accent"])

    # ── Handle watermark ─────────────────────────────────────
    h_font = load_font(42, bold=False)
    draw.text((W - 20, H - 60), handle, font=h_font,
              fill=palette["handle"], anchor="rs")

    return img


def make_steps_post(title: str, steps: list[str], handle: str,
                    palette: dict, size: tuple = (1080, 1350)) -> Image.Image:
    """
    Vertical steps/progression post with numbered list.
    """
    W, H  = size
    img   = Image.new("RGB", (W, H), palette["bg"])
    draw  = ImageDraw.Draw(img)

    # Subtle gradient effect (draw bands)
    for i in range(H):
        t = i / H
        r = int(palette["bg"][0] * (1 - t * 0.08))
        g = int(palette["bg"][1] * (1 - t * 0.08))
        b = int(palette["bg"][2] * (1 - t * 0.05))
        draw.line([(0, i), (W, i)], fill=(r, g, b))

    # Accent bar
    draw.rectangle([0, 0, 14, H], fill=palette["accent"])

    # Title
    t_font = load_font(100)
    title_y = draw_text_block(draw, title, t_font, palette["text_main"],
                               cx=W // 2, cy=130, max_width=W - 140, shadow=True)

    # Divider under title
    draw.rectangle([60, title_y + 20, W - 60, title_y + 26],
                   fill=palette["accent"])

    # Steps
    s_font  = load_font(62)
    n_font  = load_font(72)
    step_h  = (H - title_y - 120) // max(len(steps), 1)
    y       = title_y + 60

    for i, step in enumerate(steps, 1):
        cx = W // 2
        # Number circle
        circle_r = 44
        circle_x = 90
        draw.ellipse([circle_x - circle_r, y - circle_r,
                      circle_x + circle_r, y + circle_r],
                     fill=palette["accent"])
        num_w = draw.textlength(str(i), font=n_font)
        draw.text((circle_x - num_w // 2, y - n_font.size // 2),
                  str(i), font=n_font, fill=(255, 255, 255))

        # Step text
        lines = wrap_text(step, s_font, W - 200, draw)
        line_y = y - (len(lines) * (s_font.size + 6)) // 2
        for line in lines:
            draw.text((160, line_y), line, font=s_font,
                      fill=palette["text_main"])
            line_y += s_font.size + 6

        # Connector line to next step
        if i < len(steps):
            draw.rectangle([86, y + circle_r, 94, y + step_h - circle_r],
                           fill=palette["divider"])
        y += step_h

    # Handle
    h_font = load_font(40)
    draw.text((W - 20, H - 55), handle, font=h_font,
              fill=palette["handle"], anchor="rs")

    return img


def make_info_post(title: str, points: list[str], handle: str,
                   palette: dict, subtitle: str = "",
                   size: tuple = (1080, 1350)) -> Image.Image:
    """
    Info/tips post with bold title and bullet points.
    Good for tech content.
    """
    W, H  = size
    img   = Image.new("RGB", (W, H), palette["bg"])
    draw  = ImageDraw.Draw(img)

    # Background gradient
    for i in range(H):
        t = i / H
        r = int(palette["bg"][0] + (palette["panel_bot"][0] - palette["bg"][0]) * t)
        g = int(palette["bg"][1] + (palette["panel_bot"][1] - palette["bg"][1]) * t)
        b = int(palette["bg"][2] + (palette["panel_bot"][2] - palette["bg"][2]) * t)
        draw.line([(0, i), (W, i)], fill=(max(0,min(255,r)), max(0,min(255,g)), max(0,min(255,b))))

    # Top accent band
    draw.rectangle([0, 0, W, 18], fill=palette["accent"])
    draw.rectangle([0, 0, 14, H], fill=palette["accent"])

    # Title
    t_font   = load_font(108)
    title_y  = draw_text_block(draw, title, t_font, palette["text_main"],
                                cx=W // 2, cy=150, max_width=W - 140, shadow=False)

    if subtitle:
        sub_font = load_font(52)
        draw.text((W // 2, title_y + 20), subtitle, font=sub_font,
                  fill=palette["accent"], anchor="mt")
        title_y += 80

    # Divider
    draw.rectangle([60, title_y + 30, W - 60, title_y + 36],
                   fill=palette["accent"])

    # Points
    p_font   = load_font(58)
    num_font = load_font(58)
    avail_h  = H - title_y - 140
    item_h   = avail_h // max(len(points), 1)
    y        = title_y + 70

    for i, point in enumerate(points, 1):
        # Number
        num_txt = f"{i}."
        draw.text((70, y), num_txt, font=num_font, fill=palette["accent"])

        # Point text
        lines  = wrap_text(point, p_font, W - 200, draw)
        for j, line in enumerate(lines):
            draw.text((160, y + j * (p_font.size + 8)), line,
                      font=p_font, fill=palette["text_main"])
        y += item_h

    # Handle
    h_font = load_font(40)
    draw.text((W - 20, H - 55), handle, font=h_font,
              fill=palette["handle"], anchor="rs")

    return img


def generate(post_type: str, output: str, handle: str = "@oykamal",
             question: str = "", answer: str = "", title: str = "",
             steps: list = None, points: list = None,
             subtitle: str = "", palette_name: str = "fitness") -> str:
    """Main entry point — generate image and save to output path."""
    palette = PALETTES.get(palette_name, PALETTES["fitness"])
    size    = (1080, 1350)  # 4:5 vertical — perfect for Instagram + TikTok

    if post_type == "qa":
        img = make_qa_post(question, answer, handle, palette, size)
    elif post_type == "steps":
        img = make_steps_post(title, steps or [], handle, palette, size)
    elif post_type == "info":
        img = make_info_post(title, points or [], handle, palette,
                             subtitle=subtitle, size=size)
    else:
        raise ValueError(f"Unknown post type: {post_type}")

    img.save(output, "PNG", quality=95)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="qa",
                        choices=["qa", "steps", "info"])
    parser.add_argument("--question", default="")
    parser.add_argument("--answer",   default="")
    parser.add_argument("--title",    default="")
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--steps",    default="")   # comma-separated
    parser.add_argument("--points",   default="")   # comma-separated
    parser.add_argument("--handle",   default="@oykamal")
    parser.add_argument("--palette",  default="fitness",
                        choices=["fitness", "tech", "info"])
    parser.add_argument("--output",   default="/tmp/social-post.png")
    args = parser.parse_args()

    steps_list  = [s.strip() for s in args.steps.split(",")  if s.strip()]
    points_list = [p.strip() for p in args.points.split(",") if p.strip()]

    out = generate(
        post_type    = args.type,
        output       = args.output,
        handle       = args.handle,
        question     = args.question,
        answer       = args.answer,
        title        = args.title,
        subtitle     = args.subtitle,
        steps        = steps_list,
        points       = points_list,
        palette_name = args.palette,
    )
    print(f"Saved: {out}")
