"""Offline #14-to-H3 dialogue time cues using saved Shot 12 C2 model output."""
import copy
import json
from pathlib import Path

import pytest

from app.services.h3_execution_optimizer import check_authority
from app.services.h3_native_prompt import (compile_dialogue_time_cues, dialogue_events,
                                           dialogue_time_cue, sections)


FIXTURE = Path(__file__).parent / "fixtures/h3_shot12_c2_saved_preflight.json"


def saved_case():
    return json.loads(FIXTURE.read_text())


def audit(case, *, require=False):
    return check_authority(case["raw_prompt"], case["output"], case["authority"],
                           case["initial"], case["limits"], require_time_cues=require)


def test_saved_shot12_c2_cues_preserve_every_line_and_preflight():
    case = saved_case()
    original = case["output"]["optimized_prompt"]
    timeline = case["output"]["av_timeline"]
    assert audit(case)["passed"]
    case["output"]["optimized_prompt"] = compile_dialogue_time_cues(
        original, case["authority"]["dialogue_events"], timeline)
    compiled = case["output"]["optimized_prompt"]
    result = audit(case, require=True)
    assert result["passed"] and result["checks"]["dialogue_time_cues"]
    assert list(sections(compiled)) == list(sections(original))
    assert len(compiled) - len(original) < 350
    assert compiled.count("<d>") == original.count("<d>") == 7
    assert compiled.count("<Picture ") == original.count("<Picture ")
    assert [(event["speaker"], event["speaker_id"], event["exact_dialogue"])
            for event in dialogue_events(compiled)] == [
                (event["speaker"], event["speaker_id"], event["exact_dialogue"])
                for event in dialogue_events(original)]
    assert len(timeline["dialogue_events"]) == 7
    for event in timeline["dialogue_events"]:
        cue = dialogue_time_cue(event)
        assert compiled.count(cue) == 1
        assert event["optimized_start"] >= 1.625  # shared context is already included
        compiled = compiled.replace(" " + cue, "", 1)
    assert compiled == original  # no visual, camera, dialogue, or Picture prose changed


@pytest.mark.parametrize("edit", ["wrong_id", "wrong_time", "missing", "duplicate"])
def test_changed_or_missing_per_line_cue_stays_blocking(edit):
    case = saved_case()
    events = case["output"]["av_timeline"]["dialogue_events"]
    prompt = compile_dialogue_time_cues(case["output"]["optimized_prompt"],
                                        case["authority"]["dialogue_events"], case["output"]["av_timeline"])
    cue = dialogue_time_cue(events[3])  # D10 belongs to Subject 1
    replacement = {"wrong_id": cue.replace("D10", "D9"),
                   "wrong_time": cue.replace(f"{events[3]['optimized_start']:.15g}-",
                                             f"{events[3]['optimized_start'] + 0.01:.15g}-", 1),
                   "missing": "", "duplicate": cue + " " + cue}[edit]
    case["output"]["optimized_prompt"] = prompt.replace(cue, replacement, 1)
    result = audit(case, require=True)
    assert not result["passed"] and "dialogue_time_cues" in result["blocking_findings"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, 25.0])
def test_nonfinite_or_outside_generation_budget_cannot_be_compiled(invalid):
    case = saved_case()
    timeline = copy.deepcopy(case["output"]["av_timeline"])
    timeline["dialogue_events"][3]["optimized_start"] = invalid
    with pytest.raises(ValueError, match="DIALOGUE_TIME_CUE_SOURCE_INVALID"):
        compile_dialogue_time_cues(case["output"]["optimized_prompt"],
                                   case["authority"]["dialogue_events"], timeline)


def test_compiled_saved_result_is_reusable_without_duplicate_cues():
    case = saved_case()
    canonical, timeline = case["authority"]["dialogue_events"], case["output"]["av_timeline"]
    once = compile_dialogue_time_cues(case["output"]["optimized_prompt"], canonical, timeline)
    assert compile_dialogue_time_cues(once, canonical, timeline) == once
