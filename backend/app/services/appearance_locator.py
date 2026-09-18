"""Exact source matching only. Offsets are zero-based Unicode code points, end exclusive."""


def occurrences(content, text, limit=128):
    if not isinstance(text, str) or not text.strip():
        return []
    matches, start = [], 0
    while True:
        start = content.find(text, start)
        if start < 0:
            return matches
        matches.append([start, start + len(text)])
        if len(matches) > limit:
            return matches
        start += 1


def locate_evidence(content, evidence, manual=None):
    matches = [{"text": item["text"], "matches": occurrences(content, item["text"])} for item in evidence]
    proof = {"offsetUnit": "UNICODE_CODE_POINT", "endExclusive": True, "evidence": matches}
    if not matches or any(not item["matches"] for item in matches):
        return {**proof, "status": "NEEDS_REVIEW", "code": "EVIDENCE_NOT_FOUND", "source_start": None, "source_end": None}
    if any(len(item["matches"]) > 128 for item in matches):
        return {**proof, "status": "NEEDS_REVIEW", "code": "TOO_MANY_SOURCE_MATCHES", "source_start": None, "source_end": None}
    if manual:
        start, end = manual["source_start"], manual["source_end"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(content)
                or content[start:end] != manual["evidence_text"]
                or not any(a <= start < end <= b for item in matches for a, b in item["matches"])):
            raise ValueError("MANUAL_LOCATION_NOT_SUPPORTED_BY_SOURCE")
        return {**proof, "status": "LOCATED", "method": "MANUAL_EXACT", "source_start": start, "source_end": end,
                "matched_text": content[start:end]}
    intersections = {tuple(span) for span in matches[0]["matches"]}
    for item in matches[1:]:
        intersections = {(max(a, c), min(b, d)) for a, b in intersections for c, d in item["matches"] if max(a, c) < min(b, d)}
    if len(intersections) != 1:
        return {**proof, "status": "NEEDS_REVIEW", "code": "AMBIGUOUS_SOURCE" if intersections else "DISJOINT_EVIDENCE",
                "source_start": None, "source_end": None, "candidate_spans": sorted(intersections)}
    start, end = next(iter(intersections))
    return {**proof, "status": "LOCATED", "method": "EXACT_INTERSECTION", "source_start": start, "source_end": end,
            "matched_text": content[start:end]}
