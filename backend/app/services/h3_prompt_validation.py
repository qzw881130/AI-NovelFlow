"""Positive, structural validation of the director formats used by H3."""
import hashlib
import json
import re


H3_PROMPT_GATE_VERSION = 1
DIRECTOR_FIELDS = (
    "subject_definitions", "summary", "detailed_description", "overall_soundscape",
)
ANCHOR_FIELDS = ("initial_state_anchor", "frame_definitions", "keyframe_timeline")
SECTION_FIELDS = (
    *DIRECTOR_FIELDS, *ANCHOR_FIELDS, "official_character_identity_lock", "dialogue_timeline",
    "shot_description", "motion_between_pictures", "subject_manifest", "speaker_timeline",
    "audio_drive", "text_rendering_constraint",
)
SECTION_HEADER = re.compile(
    r"^[ \t]*(?:\*\*)?(" + "|".join(SECTION_FIELDS) + r")(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*",
    re.MULTILINE,
)


class H3PromptValidationError(RuntimeError):
    def __init__(self, code: str, details=None):
        self.code = code
        self.details = details
        super().__init__(f"H3 Prompt validation failed: {code}" + (f" ({details})" if details else ""))


def prompt_digest(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_h3_managed_layers(value, constraint: str = "", continuity_lock: str = "") -> str:
    if not isinstance(value, str):
        raise H3PromptValidationError("UNSUPPORTED_CONTENT_TYPE", type(value).__name__)
    core = value.strip()
    if continuity_lock and core.startswith(continuity_lock):
        remainder = core[len(continuity_lock):]
        if not remainder or remainder.startswith("\n"):
            core = remainder.strip()
    constraint = constraint.strip()
    if constraint and core == constraint:
        return ""
    marker = "text_rendering_constraint:"
    if constraint and core.endswith(constraint):
        prefix = core[:-len(constraint)]
        marker_at = prefix.rfind(marker)
        if marker_at >= 0 and re.fullmatch(r"[\s=\-_\u2501]*", prefix[marker_at + len(marker):]):
            core = prefix[:marker_at].strip()
    return core


def _has_body(value) -> bool:
    return isinstance(value, str) and any(char.isalnum() for char in value)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise H3PromptValidationError("DUPLICATE_JSON_FIELD", key)
        result[key] = value
    return result


def _invalid_json_constant(value):
    raise H3PromptValidationError("MALFORMED_DIRECTOR_JSON", value)


def validate_h3_prompt_core(value, *, allow_empty_subjects: bool = False, fallback_context: dict | None = None) -> dict:
    """Accept a director document or an independently identified program fallback.

    This validates document structure and field types, not cinematic quality.
    Unrecognized free prose is not implicitly accepted.
    """
    if not isinstance(value, str):
        raise H3PromptValidationError("UNSUPPORTED_CONTENT_TYPE", type(value).__name__)
    core = value.strip()
    if not core:
        raise H3PromptValidationError("EMPTY_CORE")
    if core.startswith("```"):
        fenced = re.fullmatch(r"```(?:json|text)?[ \t]*\r?\n(.*?)\r?\n```", core, re.DOTALL | re.IGNORECASE)
        if not fenced:
            raise H3PromptValidationError("INVALID_OUTER_FENCE")
        core = fenced.group(1).strip()
    if re.search(r"^[ \t]*```", core, re.MULTILINE):
        raise H3PromptValidationError("INVALID_OUTER_FENCE")
    if not _has_body(core):
        raise H3PromptValidationError("EMPTY_CORE")

    if core.startswith(("{", "[")):
        try:
            document = json.loads(core, object_pairs_hook=_unique_json_object, parse_constant=_invalid_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise H3PromptValidationError("MALFORMED_DIRECTOR_JSON") from exc
        if not isinstance(document, dict):
            raise H3PromptValidationError("DIRECTOR_OBJECT_REQUIRED")
        sections = {key: [body] for key, body in document.items()}
        profile = "director_json"
    else:
        headers = list(SECTION_HEADER.finditer(core))
        if not headers:
            raise H3PromptValidationError("UNSUPPORTED_DIRECTOR_FORMAT")
        preamble = core[:headers[0].start()].strip()
        sections = {}
        for index, header in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(core)
            sections.setdefault(header.group(1), []).append(core[header.end():end].strip())
        profile = "director_prose"
        if preamble:
            if fallback_context is None:
                raise H3PromptValidationError("UNSUPPORTED_DIRECTOR_PREAMBLE")
            expected = (
                f"Generate Shot {fallback_context['shot_index']} as {fallback_context['selected_mode']}.\n"
                f"Clip range: {float(fallback_context['start_time']):.3f}s to "
                f"{float(fallback_context['end_time']):.3f}s in shot time."
            )
            if not preamble.startswith(expected + "\n"):
                raise H3PromptValidationError("FALLBACK_CONTEXT_MISMATCH")
            if not all(name in sections for name in ("shot_description", "audio_drive")):
                raise H3PromptValidationError("FALLBACK_SECTIONS_MISSING")
            direction = any(_has_body(body) for body in sections["shot_description"])
            for body in sections.get("keyframe_timeline", []):
                direction = direction or any(
                    _has_body(match.group(1)) for match in re.finditer(r"^Picture \d+:.*?description=(.*)$", body, re.MULTILINE)
                )
            if not direction:
                raise H3PromptValidationError("FALLBACK_VISUAL_DIRECTION_MISSING")
            return {"version": H3_PROMPT_GATE_VERSION, "profile": "deterministic_fallback", "core": core, "core_hash": prompt_digest(core)}

    missing = [field for field in DIRECTOR_FIELDS if field not in sections]
    if missing:
        raise H3PromptValidationError("DIRECTOR_SECTIONS_MISSING", ", ".join(missing))
    for field in DIRECTOR_FIELDS[1:]:
        bodies = sections[field]
        if not all(isinstance(body, str) for body in bodies) or not any(_has_body(body) for body in bodies):
            raise H3PromptValidationError("INVALID_DIRECTOR_SECTION", field)
    subjects = sections["subject_definitions"]
    valid_subjects = False
    for body in subjects:
        if isinstance(body, str):
            valid_subjects = valid_subjects or _has_body(body) or (allow_empty_subjects and not body.strip())
        elif isinstance(body, dict):
            valid_subjects = valid_subjects or (bool(body) and all(_has_body(name) and _has_body(text) for name, text in body.items())) or (allow_empty_subjects and not body)
        else:
            raise H3PromptValidationError("INVALID_DIRECTOR_SECTION", "subject_definitions")
    if not valid_subjects:
        raise H3PromptValidationError("INVALID_DIRECTOR_SECTION", "subject_definitions")
    if not any(_has_body(body) for field in ANCHOR_FIELDS for body in sections.get(field, [])):
        raise H3PromptValidationError("VISUAL_ANCHOR_MISSING")
    for field in (*ANCHOR_FIELDS, "dialogue_timeline", "official_character_identity_lock"):
        if any(not isinstance(body, str) for body in sections.get(field, [])):
            raise H3PromptValidationError("INVALID_DIRECTOR_SECTION", field)
    return {"version": H3_PROMPT_GATE_VERSION, "profile": profile, "core": core, "core_hash": prompt_digest(core)}
