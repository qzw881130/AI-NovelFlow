"""Remove only known template style copies from persisted visual state text."""

import re


STYLE_SUFFIX = "style, high quality, detailed"


def strip_embedded_visual_style(description: str, visual_style: str) -> str:
    """Strip an exact current style (whitespace-insensitive) or legacy token.

    Other English text, including a former style that differs from the current
    novel style, is left untouched for manual review.
    """
    if not description:
        return description

    alternatives = [r"##STYLE##"]
    normalized_style = " ".join((visual_style or "").split())
    if normalized_style:
        alternatives.insert(0, r"\s+".join(re.escape(word) for word in normalized_style.split(" ")))
    pattern = re.compile(
        rf"(?:[，,]\s*)?(?<![A-Za-z0-9])(?:{'|'.join(alternatives)})"
        rf"(?:\s*{re.escape(STYLE_SUFFIX)})?"
        rf"(?=\s*(?:[。.!?；;]|\n|$))",
    )
    cleaned = pattern.sub("", description)
    # The deleted style occupied the end of Scene in the legacy templates.
    cleaned = cleaned.replace("。。\nCharacters:", "。\nCharacters:")
    cleaned = cleaned.replace(".。\nCharacters:", "。\nCharacters:")
    return cleaned
