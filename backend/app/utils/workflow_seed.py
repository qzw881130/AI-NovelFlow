import json
from typing import Any, Optional


def extract_workflow_seed(workflow: Any) -> Optional[int]:
    """Return the seed when all seed-bearing workflow nodes use one value."""
    if not workflow:
        return None
    if isinstance(workflow, str):
        try:
            workflow = json.loads(workflow)
        except Exception:
            return None
    if not isinstance(workflow, dict):
        return None

    seeds = set()
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key in ("seed", "noise_seed"):
            value = inputs.get(key)
            if isinstance(value, bool):
                continue
            try:
                if value is not None:
                    seeds.add(int(value))
            except (TypeError, ValueError):
                continue
    return next(iter(seeds)) if len(seeds) == 1 else None
