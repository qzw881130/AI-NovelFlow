"""Read-only upstream Director projections; no planning or persistence."""
from copy import deepcopy

from app.constants.prompt_template import (
    TRANSITION_CONTRACT_PREFIX, TRANSITION_INPUT_V1, TRANSITION_INPUT_V2,
    TRANSITION_V2_NAME,
)


def effective_visual_states(states, shot_description):
    """Resolve #08's START reference without changing Canonical or other states."""
    result = deepcopy(states)
    resolutions = []
    for state in result:
        if not isinstance(state, dict) or state.get("role") != "START":
            continue
        description = state.get("description")
        if description is not None and (not isinstance(description, str) or description.strip()):
            continue
        available = isinstance(shot_description, str) and bool(shot_description.strip())
        if available:
            state["description"] = shot_description
        resolutions.append({
            "keyframe_index": state.get("index"),
            "status": "RESOLVED" if available else "UNKNOWN",
            "source": "Shot.description",
            "reason": "START_REFERENCE" if available else "START_VISUAL_SOURCE_MISSING",
        })
    return result, resolutions


def transition_input_contract(template):
    """Exact protocol marker, not a natural-language semantic gate.

    Unmarked historical/user templates retain the V1 payload. Copies of V2 carry
    its marker. Unknown or ambiguous declarations fail before any LLM request.
    """
    declarations = [line.strip()[len(TRANSITION_CONTRACT_PREFIX):].strip()
                    for line in template.template.splitlines()
                    if line.strip().startswith(TRANSITION_CONTRACT_PREFIX)]
    if not declarations:
        if template.name == TRANSITION_V2_NAME:
            raise ValueError("TRANSITION_INPUT_CONTRACT_MISMATCH: V2 模板缺少 INPUT_CONTRACT 声明")
        return TRANSITION_INPUT_V1
    if len(declarations) != 1 or declarations[0] not in {TRANSITION_INPUT_V1, TRANSITION_INPUT_V2}:
        raise ValueError("TRANSITION_INPUT_CONTRACT_MISMATCH: 未知或重复的 INPUT_CONTRACT 声明")
    if template.name == TRANSITION_V2_NAME and declarations[0] != TRANSITION_INPUT_V2:
        raise ValueError("TRANSITION_INPUT_CONTRACT_MISMATCH: V2 模板与输入版本不匹配")
    return declarations[0]
