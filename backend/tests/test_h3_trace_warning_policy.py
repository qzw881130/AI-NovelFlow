"""Only a copied Clip scope instruction may be a non-blocking source quote."""
from copy import deepcopy

from app.services.h3_execution_optimizer import scope_quote_trace_warnings


def sample():
    source = "宫女1与侍从1短暂将重心从房门一侧移开。随后两人沿长廊行走。"
    scope = "Only the opening slice overlaps this Clip. Do not reach the later state."
    output = {"canonical_visual_requirements": [{
        "id": "CVR6", "requirement": "Both begin a slight weight transfer.",
        "source_id": "transition_4", "source_excerpt": scope.split(" Do not")[0],
        "prompt_excerpt": "Both begin a slight weight transfer.",
    }]}
    authority = {"anchor_policy": {"canonical_visual_sources": [{
        "id": "transition_4", "text": source,
        "clip_scope": {"execution_scope": scope},
    }]}}
    evidence = {"entries": {
        "requirements.0.source": {"status": "UNRESOLVED", "reason": "MISSING_WHOLE_FRAGMENT"},
        "requirements.0.prompt": {"status": "RESOLVED"},
    }}
    return output, authority, evidence


def test_scope_quote_warning_preserves_original_source_and_reason():
    output, authority, evidence = sample()
    before = deepcopy((output, authority, evidence))
    warnings = scope_quote_trace_warnings(output, authority, evidence)
    assert len(warnings) == 1
    assert warnings[0]["source_id"] == "transition_4"
    assert warnings[0]["source_excerpt"] == output["canonical_visual_requirements"][0]["source_excerpt"]
    assert warnings[0]["canonical_source"] == authority["anchor_policy"]["canonical_visual_sources"][0]["text"]
    assert warnings[0]["original_trace_status"] == "UNRESOLVED"
    assert (output, authority, evidence) == before


def test_wrong_source_id_or_unrelated_quote_stays_blocking():
    output, authority, evidence = sample()
    output["canonical_visual_requirements"][0]["source_id"] = "transition_5"
    assert scope_quote_trace_warnings(output, authority, evidence) is None
    output["canonical_visual_requirements"][0]["source_id"] = "transition_4"
    output["canonical_visual_requirements"][0]["source_excerpt"] = "Invented action."
    assert scope_quote_trace_warnings(output, authority, evidence) is None


def test_missing_prompt_evidence_blocks_but_optional_source_copy_warns():
    output, authority, evidence = sample()
    evidence["entries"]["requirements.0.prompt"]["status"] = "UNRESOLVED"
    assert scope_quote_trace_warnings(output, authority, evidence) is None
    evidence["entries"]["requirements.0.prompt"]["status"] = "RESOLVED"
    output["canonical_visual_requirements"][0]["source_excerpt"] = None
    warnings = scope_quote_trace_warnings(output, authority, evidence)
    assert warnings and warnings[0]["evidence_issue"] == "MISSING_SOURCE_QUOTE"


def test_mixed_trace_error_stays_blocking():
    output, authority, evidence = sample()
    second = deepcopy(output["canonical_visual_requirements"][0])
    second.update(id="CVR7", source_excerpt="Some other unsupported source.")
    output["canonical_visual_requirements"].append(second)
    evidence["entries"].update({
        "requirements.1.source": {"status": "UNRESOLVED", "reason": "MISSING_WHOLE_FRAGMENT"},
        "requirements.1.prompt": {"status": "RESOLVED"},
    })
    assert scope_quote_trace_warnings(output, authority, evidence) is None
