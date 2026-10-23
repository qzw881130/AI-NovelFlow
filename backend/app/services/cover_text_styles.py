"""Ratio-aware, deterministic typography for novel video covers."""
from PIL import Image, ImageDraw, ImageFont

from app.utils.image_utils import load_chinese_font


def _font(size: int, serif: bool) -> ImageFont.ImageFont:
    paths = (
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ) if serif else (
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
    )
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            continue
    return load_chinese_font(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: float) -> list[str]:
    lines, current = [], ""
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _fit(draw: ImageDraw.ImageDraw, texts: list[str], serif: bool, preferred: int,
         width: float, height: float) -> tuple[ImageFont.ImageFont, list[list[str]], int]:
    for size in range(preferred, 7, -1):
        font = _font(size, serif)
        lines = [_wrap(draw, text, font, width) for text in texts]
        step = round(size * 1.25)
        total = (sum(len(part) for part in lines) + 0.2 * (len(texts) - 1)) * step
        if total <= height:
            return font, lines, step
    raise ValueError("封面文字过长，无法放入所选款式")


def _draw_lines(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.ImageFont,
                step: int, x: float, y: float, width: float, align: str,
                color: tuple[int, ...], shadow: bool = False) -> None:
    for index, line in enumerate(lines):
        length = draw.textlength(line, font=font)
        line_x = x if align == "left" else x + width - length if align == "right" else x + (width - length) / 2
        line_y = y + index * step
        if shadow:
            draw.text((line_x + 2, line_y + 3), line, font=font, fill=(0, 0, 0, 135))
        draw.text((line_x, line_y), line, font=font, fill=color)


def _draw_credits(draw: ImageDraw.ImageDraw, author: str, production: str, serif: bool,
                  preferred_size: int, x: float, y: float, width: float, height: float,
                  align: str, color: tuple[int, ...], shadow: bool) -> None:
    details = [("原　著", author), ("制　作", production)]
    for size in range(preferred_size, 7, -1):
        font = _font(size, serif)
        label_width = max(draw.textlength(label, font=font) for label, _ in details)
        colon_width = draw.textlength("：", font=font)
        gap = round(size * 0.12)
        value_width = width - label_width - colon_width - gap
        if value_width <= 0:
            continue
        value_lines = [_wrap(draw, value, font, value_width) for _, value in details]
        step = round(size * 1.25)
        total_height = (sum(len(lines) for lines in value_lines) + 0.2 * (len(details) - 1)) * step
        if total_height <= height:
            break
    else:
        raise ValueError("封面署名过长，无法放入所选款式")

    widest_value = max(draw.textlength(line, font=font) for lines in value_lines for line in lines)
    block_width = label_width + colon_width + gap + widest_value
    label_x = x if align == "left" else x + width - block_width if align == "right" else x + (width - block_width) / 2
    colon_x = label_x + label_width
    value_x = colon_x + colon_width + gap
    current_y = y
    for (label, _), lines in zip(details, value_lines):
        _draw_lines(draw, [label], font, step, label_x, current_y, 0, "left", color, shadow)
        _draw_lines(draw, ["："], font, step, colon_x, current_y, 0, "left", color, shadow)
        _draw_lines(draw, lines, font, step, value_x, current_y, 0, "left", color, shadow)
        current_y += (len(lines) + 0.2) * step


def _shade(canvas: Image.Image, style: str, group: str) -> Image.Image:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size)
    draw = ImageDraw.Draw(overlay)
    if style == "cinematic" and group == "wide":
        # Subtle local backing over the gap reserved for the title.
        for x in range(round(width * 0.44), round(width * 0.88)):
            opacity = max(0.0, 1 - abs(x / width - 0.64) / 0.24)
            draw.line((x, round(height * 0.27), x, round(height * 0.72)),
                      fill=(8, 13, 21, round(88 * opacity)))
    else:
        start = {
            "editorial": {"wide": 0.48, "square": 0.56, "tall": 0.61},
            "cinematic": {"square": 0.52, "tall": 0.58},
            "vintage": {"wide": 0.72, "square": 0.77, "tall": 0.79},
        }[style][group]
        maximum = {"editorial": 190, "cinematic": 145, "vintage": 105}[style]
        for y in range(round(height * start), height):
            opacity = max(0.0, (y / height - start) / (1 - start)) ** 0.9
            draw.line((0, y, width, y), fill=(8, 13, 21, round(maximum * opacity)))
    return Image.alpha_composite(canvas, overlay)


def draw_styled_cover(canvas: Image.Image, title: str, author: str, production: str,
                      style: str) -> Image.Image:
    """Draw one of three styles with separate wide, square, and portrait layouts."""
    width, height = canvas.size
    ratio = width / height
    group = "wide" if ratio >= 1.2 else "square" if ratio >= 0.85 else "tall"
    canvas = _shade(canvas, style, group)
    draw = ImageDraw.Draw(canvas)
    short = min(width, height)

    if style == "cinematic":
        if group == "wide":
            x, y, box_width, title_height, align = width * 0.51, height * 0.35, width * 0.35, height * 0.22, "left"
        else:
            x, y, box_width, title_height, align = width * 0.08, height * (0.59 if group == "square" else 0.64), width * 0.84, height * 0.17, "center"
        title_color, credit_color, serif = (235, 222, 200, 255), (213, 200, 181, 255), True
        title_size = round(short * (0.17 if group == "wide" else 0.14))
    elif style == "editorial":
        x = width * (0.055 if group == "wide" else 0.075)
        y = height * {"wide": 0.55, "square": 0.62, "tall": 0.66}[group]
        box_width = width * (0.46 if group == "wide" else 0.85)
        title_height = height * (0.22 if group == "wide" else 0.17)
        align = "left"
        title_color, credit_color, serif = (249, 244, 234, 255), (229, 219, 204, 255), False
        title_size = round(short * (0.20 if group == "wide" else 0.17))
    elif style == "vintage":
        if group == "wide":
            x, y, box_width, title_height = width * 0.48, height * 0.18, width * 0.21, height * 0.23
        else:
            x, y, box_width, title_height = width * 0.13, height * (0.17 if group == "square" else 0.20), width * 0.74, height * 0.18
        align = "center"
        title_color, credit_color, serif = (169, 83, 64, 255), (238, 223, 198, 255), True
        title_size = round(short * (0.16 if group == "wide" else 0.15))
    else:
        raise ValueError("不支持的封面文字款式")

    title_font, [title_lines], title_step = _fit(draw, [title.strip()], serif, title_size, box_width, title_height)
    _draw_lines(draw, title_lines, title_font, title_step, x, y, box_width, align, title_color,
                shadow=style != "vintage")

    if style == "vintage":
        # Fine lines echo an old book cover without boxing in the illustration.
        accent = (183, 144, 89, 205)
        top, bottom = round(y), round(y + min(title_height, len(title_lines) * title_step))
        xs = (x - width * 0.016, x + box_width + width * 0.016) if group == "wide" else (
            x + box_width * 0.05, x + box_width * 0.95)
        for line_x in xs:
            draw.line((round(line_x), top, round(line_x), bottom), fill=accent,
                      width=max(1, round(width * 0.001)))

    if style == "vintage":
        credit_x = width * (0.61 if group == "wide" else 0.10)
        credit_width = width * (0.32 if group == "wide" else 0.80)
        credit_y = height * {"wide": 0.79, "square": 0.81, "tall": 0.83}[group]
        credit_align = "right" if group == "wide" else "center"
    else:
        credit_x, credit_width, credit_align = x, box_width, align
        credit_y = y + len(title_lines) * title_step + height * 0.025
    _draw_credits(draw, author, production, serif, round(short * 0.033), credit_x, credit_y,
                  credit_width, height * 0.97 - credit_y, credit_align, credit_color,
                  shadow=style != "vintage")

    if style == "editorial":
        rule_y = round(credit_y - height * 0.015)
        rule_length = min(width * 0.055, box_width * 0.17)
        draw.rounded_rectangle((round(x), rule_y, round(x + rule_length),
                                rule_y + max(2, round(height * 0.004))),
                               radius=2, fill=(159, 78, 61, 255))
    return canvas
