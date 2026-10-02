"""Deterministic speech-authority guards for canonical visual text."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class VisualSpeechAuthorityMatch:
    category: str
    phrase: str
    start: int
    end: int


class CanonicalVisualSpeechAuthorityViolation(ValueError):
    """Raised when visual planning text attempts to own speech behavior."""

    def __init__(
        self,
        *,
        code: str,
        field: str,
        match: VisualSpeechAuthorityMatch,
        state_index: int | str | None = None,
    ) -> None:
        self.code = code
        self.field = field
        self.match = match
        self.state_index = state_index
        location = f"state_index={state_index} " if state_index is not None else ""
        super().__init__(
            f"{code}: {location}field={field} "
            f"category={match.category} phrase={match.phrase!r}"
        )


_AUTHORITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "SPEAKING_AUTHORITY",
        re.compile(
            r"开始说(?:话)?|正在说(?:话)?|继续说(?:话)?|停止说(?:话)?|"
            r"说话|开口|回答|答话|接话|发声|话音|陈述|"
            r"\b(?:speaks?|speaking|talks?|talking|says?|starts?\s+speaking|"
            r"continues?\s+speaking|answers?|replies?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "LISTENING_AUTHORITY",
        re.compile(
            r"倾听|听完(?:回答|答复|发言|讲话|话语|台词)|"
            r"\b(?:listens?|listening)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "MOUTH_LIP_SPEECH_STATE",
        re.compile(
            r"嘴唇[^，。！？；;\n]{0,12}(?:微启|张开|开启|闭合|合拢)|"
            r"张嘴|闭嘴|口型|唇形|lip[ -]?sync|"
            r"\blips?\s+(?:(?:is|are)\s+)?(?:part(?:s|ed|ing)?|open(?:s|ed|ing)?|close(?:s|d|ing)?)\b|"
            r"\bmouth\s+(?:(?:is|are)\s+)?(?:open(?:s|ed|ing)?|close(?:s|d|ing)?)\b",
            re.IGNORECASE,
        ),
    ),
)


def find_visual_speech_authority(text: str | None) -> list[VisualSpeechAuthorityMatch]:
    """Return explicit speech-authority matches without interpreting general emotion."""
    value = str(text or "")
    matches: list[VisualSpeechAuthorityMatch] = []
    for category, pattern in _AUTHORITY_PATTERNS:
        for found in pattern.finditer(value):
            matches.append(VisualSpeechAuthorityMatch(
                category=category,
                phrase=found.group(0),
                start=found.start(),
                end=found.end(),
            ))
    return sorted(matches, key=lambda item: (item.start, item.end, item.category))


def require_speech_neutral_visual_text(
    text: str | None,
    *,
    code: str,
    field: str,
    state_index: int | str | None = None,
) -> None:
    """Reject the first explicit speech-authority phrase in visual text."""
    matches = find_visual_speech_authority(text)
    if matches:
        raise CanonicalVisualSpeechAuthorityViolation(
            code=code,
            field=field,
            match=matches[0],
            state_index=state_index,
        )
