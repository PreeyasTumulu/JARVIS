"""The words on the overlay, drawn with Pillow into a picture that becomes a texture.

They are pixels in a window that takes no clicks, so nothing in them can be followed or pressed,
whatever a reply or a web page managed to put in the text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONTS = Path(r"C:\Windows\Fonts")
FACES = ("bahnschrift.ttf", "segoeui.ttf", "arial.ttf")
BODY_LINES = 3
CONFIRM_LINES = 5
TONES = {"normal": (120, 225, 255, 255), "confirm": (255, 176, 74, 255)}


@dataclass(frozen=True)
class CardText:
    heading: str = ""
    body: str = ""
    status: str = ""
    tone: str = "normal"


def load_font(size: int, *, semibold: bool = False) -> Any:
    for face in FACES:
        try:
            font = ImageFont.truetype(str(FONTS / face), size)
        except OSError:
            continue
        if semibold and face == "bahnschrift.ttf":
            font.set_variation_by_name("SemiBold")
        return font
    return ImageFont.load_default(size)


def wrap(text: str, width: int, measure: Any, max_lines: int) -> list[str]:
    """Split into lines that fit, ending in dots when the text runs longer than `max_lines`."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if measure(trial) <= width or not line:
            line = trial
            continue
        lines.append(line)
        line = word
        if len(lines) == max_lines:
            lines[-1] = _with_dots(lines[-1], width, measure)
            return lines
    if line:
        lines.append(line)
    return lines


def _with_dots(line: str, width: int, measure: Any) -> str:
    while line and measure(line + "...") > width:
        line = line[:-1]
    return line.rstrip() + "..."


def _premultiplied(image: Image.Image) -> Image.Image:
    red, green, blue, alpha = image.split()
    return Image.merge(
        "RGBA",
        (
            ImageChops.multiply(red, alpha),
            ImageChops.multiply(green, alpha),
            ImageChops.multiply(blue, alpha),
            alpha,
        ),
    )


def render_card(text: CardText, *, width: int, big: bool, scale: float) -> Image.Image:
    """A premultiplied RGBA picture of the words, cropped to its height, centred across `width`.

    Big sits on the darkened screen with a soft shadow. Small is the panel over your apps.
    """
    body_size = round((42 if big else 23) * scale)
    label_size = round((22 if big else 15) * scale)
    pad = round((0 if big else 18) * scale)
    body_font = load_font(body_size, semibold=big)
    label_font = load_font(label_size, semibold=True)
    max_lines = CONFIRM_LINES if text.tone == "confirm" else BODY_LINES
    inner = width - 2 * pad - round(40 * scale)
    lines = wrap(text.body, inner, body_font.getlength, max_lines)

    line_height = round(body_size * 1.28)
    label_height = round(label_size * 1.6) if text.heading or text.status else 0
    height = 2 * pad + label_height + line_height * len(lines) + round(14 * scale)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    box_left = 0
    if not big:
        widest = max([body_font.getlength(line) for line in lines] or [0])
        header = label_font.getlength(_label(text))
        box_width = min(
            width, round(max(widest, header, 260 * scale)) + 2 * pad + round(16 * scale)
        )
        box_left = (width - box_width) // 2
        draw.rounded_rectangle(
            (box_left, 0, box_left + box_width - 1, height - 1),
            radius=round(10 * scale),
            fill=(9, 12, 18, 232),
            outline=(255, 255, 255, 34),
        )

    ink = TONES.get(text.tone, TONES["normal"])
    words = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    writer = ImageDraw.Draw(words)
    y = pad
    label = _label(text)
    if label:
        writer.text((width / 2, y), label, font=label_font, fill=ink, anchor="ma")
        y += label_height
    for line in lines:
        writer.text((width / 2, y), line, font=body_font, fill=(255, 255, 255, 255), anchor="ma")
        y += line_height
    if big:
        shadow = words.getchannel("A").filter(ImageFilter.GaussianBlur(round(7 * scale)))
        canvas.paste((0, 0, 0, 255), (0, 0), shadow.point(lambda a: min(255, a * 2)))
    canvas.alpha_composite(words)
    return _premultiplied(canvas)


def _label(text: CardText) -> str:
    if text.heading and text.status:
        return f"{text.heading}  /  {text.status}"
    return text.heading or text.status
