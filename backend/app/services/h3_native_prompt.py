"""Text-contract checks for #14's H3-native output, independent of AV scheduling.

These checks reject structural mistakes and explicit blocking contradictions.
They do not certify cinematic feasibility, lip sync, or arbitrary prose semantics.
"""
import re

SECTIONS = (
    "subject_definitions", "summary", "retention_analysis", "detailed_description",
    "overall_soundscape", "non_diegetic_music",
)
# Product compactness guard, not a claimed MiniMax model/context limit.
MAX_PROMPT_CHARACTERS = 12000


def sections(prompt):
    headings = list(re.finditer(r"(?m)^([a-z_]+):[ \t]*$", prompt))
    if [m[1] for m in headings] != list(SECTIONS) or prompt[:headings[0].start()].strip():
        return {}
    return {m[1]: prompt[m.end():headings[i + 1].start() if i + 1 < len(headings) else len(prompt)].strip()
            for i, m in enumerate(headings)}


def declared_duration(prompt):
    """Read a natural total duration; never infer dialogue/anchor timestamps."""
    parts = sections(prompt)
    if parts:
        values = re.findall(r"\b(\d+(?:\.\d+)?)[ -]second\b", parts["summary"], re.I)
    else:
        # Historical records remain inspectable. New outputs must pass sections().
        values = re.findall(r"(?m)^\s*duration:\s*([\d.]+)s\s*$", prompt)
    return float(values[0]) if len(values) == 1 else None


def speaker_bindings(canonical):
    result = {}
    for event in canonical:
        result.setdefault(event["speaker"], f"S{len(result) + 1}")
    return result


def dialogue_events(prompt):
    detail = sections(prompt).get("detailed_description", "")
    pattern = r"(<Subject \d+>)\s+\((S\d+)\)\s+([^<>]+?)<d>\[([^\]\n]+)\][ \t]?(.*?)</d>"
    result, previous_end = [], 0
    for match in re.finditer(pattern, detail, re.S):
        result.append({"speaker": match[1], "speaker_id": match[2], "language": match[4],
                       "exact_dialogue": match[5], "prelude": detail[previous_end:match.start()],
                       "speech_lead": match[3], "span_start": match.start(), "span_end": match.end()})
        previous_end = match.end()
    return result


def _actor_pattern(subject, name):
    aliases = [re.escape(subject)]
    if name:
        aliases.append(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
    return "(?:" + "|".join(aliases) + ")"


def _positive_reblocking(text, actor):
    # Negated instructions ('does not rise', 'never walks') do not match.
    return bool(re.search(actor + r"\s+(?:(?:then|slowly|gently|now|gradually|deliberately)\s+)*"
                          r"(?:stands(?:\s+up)?|rises|gets\s+up|walks|steps|moves|advances|leaves|sits\s+down)\b", text, re.I))


def seated_subjects(raw_prompt, bindings):
    """Recognize explicit stable seated authority, allowing canonical pose changes.

    Unknown states are not guessed from role names or Subject numbers. Image-only
    pose and pronoun resolution still require the LLM and preflight review.
    """
    result = {}
    for subject, name in bindings.items():
        actor = _actor_pattern(subject, name)
        seated = re.search(actor + r"\s+(?:(?:remains|stays|is|keeps)\s+)?(?:seated|sits)\b", raw_prompt, re.I)
        seated = seated or re.search(actor + r"\s*(?:(?:继续|仍然|始终|保持|仍|稳)\s*)*(?:坐在|坐于|坐姿|坐)", raw_prompt)
        if seated and not _positive_reblocking(raw_prompt, actor):
            result[subject] = actor
    return result


def _explicit_listener_scope(prelude, incoming, authority, closed):
    """Require a local listener clause, never inherit a preceding turn's state.

    Universal visible-character wording avoids guessing off-screen membership.
    Explicit Subject lists can also cover the known cast. Image-specific visibility
    and prose beyond these patterns still require semantic preflight review.
    """
    characters = {ref.get("subject") for ref in authority.get("reference_bindings", [])
                  if ref.get("type") == "CHARACTER_IDENTITY" and ref.get("subject")}
    characters = characters or set(authority["subject_bindings"])
    listeners = characters - {incoming}
    for clause in re.split(r"[.!?]\s*|\n", prelude):
        complete_state = (re.search(closed, clause, re.I)
                          and re.search(r"listen|attentive|reaction|react|blink|breath", clause, re.I)
                          and re.search(r"natural|relaxed", clause, re.I)
                          and re.search(r"(?:no|without)\s+speech[ -]like\s+(?:mouth\s+)?(?:articulation|movement|motion)", clause, re.I))
        universal = re.search(r"\ball\s+(?:the\s+)?(?:other|remaining)\s+(?:currently\s+)?(?:visible\s+)?(?:characters|people|subjects|listeners|non-speakers)\b", clause, re.I)
        enumerated = bool(listeners) and listeners <= set(re.findall(r"<Subject \d+>", clause))
        if complete_state and (universal or enumerated):
            return True
    return False


def _handoff_evidence_is_local(actual, canonical, timeline):
    """Check provenance, participants and ordering, not arbitrary prose meaning.

    No camera-verb whitelist: equivalent natural actions remain eligible. Semantic
    preflight must still judge whether the cited action actually acquires the next
    speaker, completes before speech and preserves blocking. A cited target-state
    sentence is not itself proof of acquisition or of generated video quality.
    """
    if len(actual) != len(canonical):
        return False
    switches = [i for i in range(1, len(canonical))
                if canonical[i]["speaker"] != canonical[i - 1]["speaker"]]
    handoffs = timeline.get("handoffs", [])
    if not isinstance(handoffs, list) or len(handoffs) != len(switches):
        return False
    for i, handoff in zip(switches, handoffs):
        if not isinstance(handoff, dict):
            return False
        previous, incoming = canonical[i - 1], canonical[i]
        if (handoff.get("from"), handoff.get("to"), handoff.get("from_subject"), handoff.get("to_subject")) != (
                previous["id"], incoming["id"], previous["speaker"], incoming["speaker"]):
            return False
        evidence = handoff.get("prompt_evidence")
        if not isinstance(evidence, dict) or not isinstance(handoff.get("camera_handoff_required"), bool):
            return False
        prelude = actual[i]["prelude"]
        spans = {}
        for key in ("release", "acquisition", "listeners", "dialogue_entry"):
            excerpt = evidence.get(key)
            if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in prelude:
                return False
            start = prelude.find(excerpt)
            spans[key] = (start, start + len(excerpt))
        # The entry connects to this utterance, not an earlier 'then' in the prose.
        entry = evidence["dialogue_entry"].rstrip()
        if not prelude.rstrip().endswith(entry):
            return False
        entry_start = len(prelude.rstrip()) - len(entry)
        if (spans["release"][1] > spans["acquisition"][1]
                or any(spans[key][1] > entry_start for key in ("release", "acquisition", "listeners"))):
            return False
        if previous["speaker"] not in evidence["release"] or incoming["speaker"] not in evidence["acquisition"]:
            return False
        if handoff["camera_handoff_required"]:
            if previous["speaker"] not in evidence["acquisition"]:
                return False
        else:
            existing = evidence.get("existing_view_excerpt")
            if (not isinstance(existing, str) or not existing.strip()
                    or incoming["speaker"] not in existing or existing not in actual[i - 1]["prelude"]):
                return False
    return True


def check_native_prompt(prompt, canonical, authority, raw_prompt, timeline):
    parts = sections(prompt)
    actual = dialogue_events(prompt)
    mapping = speaker_bindings(canonical)
    checks = {
        "h3_native_six_sections": bool(parts) and all(parts.values()),
        "compact_final_prompt": 0 < len(prompt) <= MAX_PROMPT_CHARACTERS,
        "no_internal_execution_dsl": not re.search(
            r"\bPHASE\b|\bP\d{2,}\b|\b(?:PRIMARY|SECONDARY|BACKGROUND)\b|"
            r"(?m:^\s*(?:speaker|start_time|end_time|exact_dialogue|duration|duration_source|"
            r"authority_echo|execution_phases|handoff_budget|risk_level|validation_state)\s*:)|"
            r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", prompt),
        "no_final_state_machine_terms": not re.search(
            r"speaker visual acquisition|previous speaker release|state machine|ownership transfer|"
            r"(?-i:\b(?:KEEP|RETIME|DROP)\b)|canonical_visual_requirements|preserved_visual_requirements|anchor_id|reference_projection", prompt, re.I),
        "native_dialogue_markup": len(actual) == len(canonical) == prompt.count("<d>") == prompt.count("</d>"),
        "dialogue_ids_speakers_text_order": [(e["speaker"], e["exact_dialogue"]) for e in actual]
            == [(e["speaker"], e["exact_dialogue"]) for e in canonical],
        "stable_speaker_ids": len(actual) == len(canonical) and all(
            e["speaker_id"] == mapping.get(e["speaker"]) for e in actual),
        "no_silent_speaker_ids": all(mapping.get(subject) == voice for subject, voice in
            re.findall(r"(<Subject \d+>)\s+\((S\d+)\)", prompt)),
        "chinese_dialogue_language_marker": all(
            e["language"] == "Chinese" for e in actual if re.search(r"[\u3400-\u9fff]", e["exact_dialogue"])),
        "timing_internal_only": not re.search(r"\b\d+(?:\.\d+)?\s*(?:s\b|seconds?\b)",
            "\n".join(value for key, value in parts.items() if key != "summary"), re.I),
    }
    expected_tags = sum(bool(re.search(r"[\u3400-\u9fff]", e["exact_dialogue"])) for e in canonical)
    checks["chinese_marker_count"] = prompt.count("[Chinese]") == expected_tags
    # Each exact line occurs once per canonical event, including intentional repeats.
    checks["exact_dialogue_occurrence_count"] = all(
        prompt.count(e["exact_dialogue"]) == sum(c["exact_dialogue"] == e["exact_dialogue"] for c in canonical)
        for e in canonical)
    switches = [i for i in range(1, len(canonical)) if canonical[i]["speaker"] != canonical[i-1]["speaker"]]
    closed = r"closed[ -](?:mouths?|lips)|(?:mouths?|lips)\s+(?:(?:are|remain|stay|relax|settle|naturally)\s+)*(?:closed|close)"
    checks["speaker_switch_camera_evidence"] = _handoff_evidence_is_local(actual, canonical, timeline)
    checks["speaker_switch_listener_settle"] = len(actual) == len(canonical) and all(
        re.search(closed, actual[i]["prelude"], re.I)
        and re.search(r"listen|attentive|silent", actual[i]["prelude"], re.I) for i in switches)
    checks["speaker_switch_listener_scope"] = len(actual) == len(canonical) and all(
        _explicit_listener_scope(actual[i]["prelude"], actual[i]["speaker"], authority, closed)
        for i in switches)
    retention = parts.get("retention_analysis", "")
    reference_scope = parts.get("subject_definitions", "") + "\n" + retention
    state_scope = (r"anchor|visual state|canonical staging|chronological references?"
                   if authority.get("anchor_policy") else r"anchor|visual state")
    if (authority.get("continuation") or {}).get("binding_verified") is True:
        # Hyphenated compound adjectives and whitespace are equivalent only for
        # an actually verified continuation source. Never normalize final prose.
        separator = r"(?:[^\S\r\n]+|[^\S\r\n]*[-\u2010\u2011][^\S\r\n]*)"
        state_scope += (rf"|preceding{separator}(?:video|footage)"
                        rf"|previous{separator}(?:video|AV|footage)"
                        rf"|incoming{separator}(?:footage|video|context)")
    state_source = bool(re.search(state_scope, reference_scope, re.I))
    if not state_source and (authority.get("continuation") or {}).get("binding_verified") is True:
        # A carried-state retention clause may name its actual AV source in the
        # opening instruction. Keep identity/costume/blocking scope in retention;
        # do not borrow arbitrary later mentions or modify the model's prose.
        opening = parts.get("detailed_description", "").strip()
        state_source = bool(
            re.match(r"(?:carry forward|preserve|retain)\s+(?:the\s+)?incoming\s+(?:posture|state|clothing|costume)\b", retention.strip(), re.I)
            and re.match(r"(?:continue|preserve)\s+(?:the\s+)?(?:shared\s+)?(?:incoming|previous|preceding)[ -](?:footage|video|AV)\b", opening, re.I))
    checks["reference_authority_scope"] = not authority.get("reference_bindings") or all(
        re.search(pattern, reference_scope, re.I) for pattern in
        [r"costume|clothing", r"pose|posture", r"blocking|floor position", r"identit", r"face"]) and state_source
    checks["blocking_preservation_wording"] = bool(re.search(
        r"(?:preserv|maintain|retain|remain|unchanged|established).{0,100}(?:floor positions?\b|blocking|seated|standing)", prompt, re.I))
    fixed_seated = seated_subjects(raw_prompt, authority["subject_bindings"])
    phase_text = "\n".join(str(p.get("description", "")) for p in timeline.get("execution_phases", []) if isinstance(p, dict))
    for subject, actor in fixed_seated.items():
        checks[f"seated_state_preserved_{subject}"] = bool(re.search(
            actor + r"\s+(?:(?:remains|stays|is|keeps)\s+)?seated\b", prompt, re.I))
        checks[f"no_acquisition_reblocking_{subject}"] = not _positive_reblocking(prompt + "\n" + phase_text, actor)
    # Only explicit canonical spatial anchoring licenses this narrow check.
    # Natural limb/posture changes remain allowed; unknown prose needs review.
    for subject in re.findall(r"(?m)^(<Subject \d+>)[^\n]*LOCAL_MOTION\s*/\s*SPATIALLY_ANCHORED", raw_prompt):
        actor = _actor_pattern(subject, authority["subject_bindings"].get(subject))
        displacement = actor + r"\s+(?:(?:then|slowly|gently|now|gradually|deliberately)\s+)*(?:walks|steps|runs|teleports|swaps\s+positions|moves\s+to\s+(?:the\s+)?(?:other|opposite|left|right)\s+side)\b"
        checks[f"canonical_floor_position_{subject}"] = not re.search(displacement, prompt + "\n" + phase_text, re.I)
    return checks, actual
