#!/usr/bin/env python3
"""
Render captured terminal output (with ANSI colour codes) to a PNG image
that looks like a real terminal screenshot.

Used to embed paper figures showing actual command output. Avoids the
unreproducibility of literal screenshots from a desktop session.

Usage::

    ./scripts/render_terminal.py <input.txt> <output.png> [--title "$ ./local_scan.sh"]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Solarized-Dark-ish palette ─────────────────────────────────────────────
BG = (29, 31, 33)
FG = (235, 219, 178)
TITLE_BG = (60, 56, 54)
TITLE_FG = (235, 219, 178)
RED = (251, 73, 52)
GREEN = (152, 151, 26)
YELLOW = (215, 153, 33)
BLUE = (69, 133, 136)
CYAN = (104, 157, 106)
GREY = (124, 111, 100)

ANSI_TO_COLOR = {
    "0": FG,         # reset
    "31": RED,       # red
    "32": GREEN,     # green
    "33": YELLOW,    # yellow
    "34": BLUE,      # blue
    "36": CYAN,      # cyan
    "37": FG,        # white
    "1;31": RED,     # bold red
    "1;32": GREEN,   # bold green
    "1;33": YELLOW,
    "1;36": CYAN,
    "0;31": RED,
    "0;32": GREEN,
    "0;33": YELLOW,
    "0;36": CYAN,
}

ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")


def parse_ansi_line(line: str) -> list[tuple[str, tuple]]:
    """Split a line into (text, colour) chunks."""
    chunks = []
    pos = 0
    current_color = FG
    for m in ANSI_RE.finditer(line):
        text = line[pos:m.start()]
        if text:
            chunks.append((text, current_color))
        code = m.group(1)
        current_color = ANSI_TO_COLOR.get(code, current_color if code else FG)
        if code == "" or code == "0":
            current_color = FG
        pos = m.end()
    rest = line[pos:]
    if rest:
        chunks.append((rest, current_color))
    return chunks


def render(text: str, output_path: Path, title: str = "") -> None:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    font = ImageFont.truetype(font_path, 14)
    title_font = ImageFont.truetype(font_path, 13)

    # Strip ANSI to compute dimensions
    clean_lines = [ANSI_RE.sub("", ln).rstrip() for ln in text.splitlines()]
    if not clean_lines:
        clean_lines = [""]

    # Measure
    char_w = font.getbbox("M")[2]
    line_h = font.getbbox("Mg")[3] + 4
    cols = max(len(ln) for ln in clean_lines)
    cols = min(cols, 110)  # cap width

    pad_x = 16
    pad_y = 14
    title_h = 30 if title else 0
    img_w = pad_x * 2 + char_w * cols
    img_h = title_h + pad_y * 2 + line_h * len(clean_lines)

    img = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(img)

    # Title bar
    if title:
        draw.rectangle([(0, 0), (img_w, title_h)], fill=TITLE_BG)
        # Three traffic-light dots
        dot_y = title_h // 2
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            draw.ellipse([(12 + i * 18 - 6, dot_y - 6),
                          (12 + i * 18 + 6, dot_y + 6)], fill=c)
        # Title text right of dots
        draw.text((80, title_h // 2 - 7), title, fill=TITLE_FG, font=title_font)

    # Body
    y = title_h + pad_y
    for line in text.splitlines():
        x = pad_x
        chunks = parse_ansi_line(line) or [(line, FG)]
        for chunk_text, color in chunks:
            # Replace tabs with 4 spaces for stable rendering
            chunk_text = chunk_text.replace("\t", "    ")
            draw.text((x, y), chunk_text, fill=color, font=font)
            x += font.getbbox(chunk_text)[2]
        y += line_h

    img.save(output_path)
    print(f"  wrote {output_path}  ({img_w}x{img_h})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    text = args.input.read_text()
    render(text, args.output, title=args.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
