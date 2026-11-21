"""Own-brand picture when the event has no permitted matching promo photo."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False):
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, lines: int):
    words = str(text).split()
    result = []
    for word in words:
        candidate = (result[-1] + " " + word) if result else word
        if result and draw.textbbox((0, 0), candidate, font=font)[2] > width:
            if len(result) >= lines:
                break
            result.append(word)
        elif result:
            result[-1] = candidate
        else:
            result.append(candidate)
    if len(result) == lines and " ".join(result).strip() != str(text).strip():
        last = result[-1]
        while len(last) > 3 and draw.textbbox((0, 0), last + "…", font=font)[2] > width:
            last = last[:-1].rstrip()
        result[-1] = last.rstrip() + "…"
    return result


def branded_poster(title: str, city: str, date_text: str) -> bytes:
    """Return a generated JPEG; never use a random unrelated performance photo."""
    width, height = 1200, 675
    image = Image.new("RGB", (width, height), (21, 31, 52))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 18, height), fill=(211, 40, 62))
    draw.rectangle((18, 0, 36, height), fill=(255, 255, 255))
    draw.rectangle((36, 0, 54, height), fill=(35, 87, 168))
    draw.rounded_rectangle((82, 67, 460, 137), radius=12, fill=(48, 65, 98))
    draw.text((105, 78), "СЕРБИЯ 24  |  АФИША", font=_font(31, True), fill="white")
    draw.line((95, 570, 1105, 570), fill=(116, 145, 182), width=2)
    title_font = _font(65, True)
    rows = _wrap(draw, title, title_font, 1010, 3)
    y = 180
    for line in rows:
        draw.text((95, y), line, font=title_font, fill=(250, 250, 255))
        y += 93
    draw.text((98, 593), (city + "  •  " + date_text)[:100],
              font=_font(27), fill=(224, 233, 245))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=86, optimize=True)
    return buffer.getvalue()
