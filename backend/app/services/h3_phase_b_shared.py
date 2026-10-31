"""Small H3 contracts used by the supported Phase B compiler.

These are kept independent of the retired #13→#14 execution path.
"""

import re

from app.constants.capability import CLIP_MAX_DURATION, VIDEO_CAPABILITY_CONTRACTS, clip_duration_maximum


def workflow_duration_limits(extension=None, capability="GENERATE"):
    """Intersect the existing validated capability with the selected workflow."""
    contract = VIDEO_CAPABILITY_CONTRACTS.get(capability, VIDEO_CAPABILITY_CONTRACTS["GENERATE"])
    extension = extension or {}
    return {
        "minimum": max(float(contract["min_duration"]), float(extension.get("min_clip_duration") or extension.get("min_seconds") or contract["min_duration"])),
        "maximum": min(float(contract["max_duration"]), clip_duration_maximum(extension)),
        "absolute_maximum": CLIP_MAX_DURATION,
        "frame_rule": "existing frozen workflow duration-to-frames conversion",
    }


def identity_picture_subjects(prompt, picture):
    """Read identity assertions without borrowing actors from later action prose."""
    pairs = set()
    for line in prompt.splitlines():
        definition = re.match(r"\s*(<Subject \d+>)\s+is\b", line)
        for sentence in re.split(r"(?<=[.!?。！？])\s+", line):
            if picture not in sentence or not re.search(r"(?i)identity|↔|\bbind|\bapply|稳定身份仅绑定到", sentence):
                continue
            subjects = set(re.findall(r"<Subject \d+>", sentence))
            if (not subjects and definition
                    and len(set(re.findall(r"<Subject \d+>", line))) == 1
                    and re.search(r"\bthis Subject\b|\b(?:his|her|their)\s+(?:permanent\s+)?identity\b", sentence, re.I)):
                subjects.add(definition[1])
            pairs.update(subjects)
    return pairs


def subject_bindings(prompt):
    bindings = {}
    for subject, name in re.findall(r"(?m)^[ \t]*(?:[-*+][ \t]+)?(<Subject \d+>)\s+is\s+([^,，\n.;；。:：]+)", prompt):
        bindings.setdefault(subject, name.strip())
    return bindings
