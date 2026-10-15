"""Shot 7 C1 citations: literal Canonical actions vs Clip scope guidance."""

from copy import deepcopy

import pytest

from app.services.h3_evidence import resolve_output_evidence


T3 = (
    "侍从1先在宫女1与紧闭房门之间停顿目光，随后肩膀逐渐僵硬，头部和视线避开两者，转向长廊前方。"
    "宫女1继而将身体重心从房门一侧向外撤开少许，视线转向长廊另一侧，双手缓慢收拢在身前。"
)
T4_OPENING = "起始保持突出宫女1与侍从1面部和上身的双人构图，两人维持收紧姿态，短暂将重心从紧闭的织造室房门一侧移开。"
T4 = T4_OPENING + "随后宫女1转向长廊前方并迈步；到达终点时，两人已位于长廊前方。"
T3_CITATION = "侍从1……肩膀逐渐僵硬……转向长廊前方。宫女1继而将身体重心从房门一侧向外撤开少许……双手缓慢收拢在身前"
T4_SCOPE = (
    "Only the opening slice of this original transition overlaps this Clip. "
    "Show only its initial progression; do not perform later actions or claim arrival at the unowned target state."
)


def trace(source_id, quote, *, t3=T3, t4=T4):
    authority = {
        "subject_bindings": {"<Subject 1>": "宫女1", "<Subject 2>": "侍从1"},
        "anchor_policy": {"canonical_visual_sources": [
            {"id": "transition_3", "text": t3},
            {"id": "transition_4", "text": t4, "clip_scope": {
                "clip_local_start_time": 10.5,
                "clip_local_end_time": 10.6,
                "execution_scope": T4_SCOPE,
            }},
        ]},
    }
    requirement = {
        "id": "CVR5" if source_id == "transition_3" else "CVR6",
        "requirement": "侍从1 and 宫女1 retain the quoted action",
        "source_id": source_id,
        "source_excerpt": quote,
        "prompt_excerpt": "",
    }
    before = deepcopy((authority, requirement))
    entry = resolve_output_evidence("", {"canonical_visual_requirements": [requirement]}, authority)["entries"]["requirements.0.source"]
    assert (authority, requirement) == before
    return entry


def test_t3_normal_transition_resolves_ordered_literal_fragments():
    result = trace("transition_3", T3_CITATION)
    assert result["status"] == "RESOLVED"
    assert result["method"] == "CANONICAL_EXPLICIT_ELLIPSIS"
    assert len(result["resolved_spans"]) == 5
    assert all(T3[span["start"]:span["end"]] == span["excerpt"] for span in result["resolved_spans"])


@pytest.mark.parametrize("source_id", ["transition_4", "KF5", None])
def test_t3_wrong_or_missing_source_id_does_not_borrow_action(source_id):
    assert trace(source_id, T3_CITATION)["status"] != "RESOLVED"


@pytest.mark.parametrize("t3", [
    T3.replace("肩膀逐渐僵硬", "肩膀逐渐放松"),
    T3.replace("随后肩膀逐渐僵硬", "随后没有肩膀逐渐僵硬"),
    T3.replace("随后肩膀逐渐僵硬", "随后宫女1肩膀逐渐僵硬"),
    T3.replace("随后肩膀逐渐僵硬", "随后宫女1抬头，随后肩膀逐渐僵硬"),
])
def test_t3_missing_fact_negation_or_other_actor_does_not_resolve(t3):
    assert trace("transition_3", T3_CITATION, t3=t3)["status"] != "RESOLVED"


def test_t4_opening_action_and_current_clip_scope_keep_distinct_provenance():
    opening = trace("transition_4", T4_OPENING)
    assert opening["status"] == "RESOLVED" and opening["method"] == "EXACT"
    scope = trace("transition_4", T4_SCOPE)
    assert scope["status"] == "RESOLVED"
    assert scope["resolution_status"] == "AUTHORIZED_SOURCE_REATTRIBUTED"
    assert scope["resolved_source_id"] == "transition_4.clip_scope.execution_scope"
    assert scope["mismatch_reason"] == "EXECUTION_SCOPE_QUOTED_AS_CANONICAL_SOURCE"


def test_c2_exclusive_state_and_missing_source_stay_unresolved():
    assert trace("KF5", "到达终点时，两人已位于长廊前方。")["status"] != "RESOLVED"
    assert trace(None, T4_OPENING)["status"] != "RESOLVED"


def test_t4_source_content_mismatch_stays_unresolved():
    assert trace("transition_4", T4_OPENING.replace("收紧姿态", "放松姿态"))["status"] != "RESOLVED"
