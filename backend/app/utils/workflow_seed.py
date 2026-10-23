import json
import random
from typing import Any, Optional

SAMPLER_NODE_TYPES = {
    "KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced",
    "RandomNoise", "PainterSamplerLTXV",
}
QWEN_REWRITE_NODE_TYPE = "QwenPERewriteT8"
QWEN_SEED_MAX = 2**31 - 1


def set_workflow_seed(workflow: dict, seed: int) -> None:
    """Share one seed between samplers and Qwen PE, within Qwen's INT range."""
    if any(isinstance(node, dict) and node.get("class_type") == QWEN_REWRITE_NODE_TYPE for node in workflow.values()):
        seed %= QWEN_SEED_MAX + 1
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") not in SAMPLER_NODE_TYPES | {QWEN_REWRITE_NODE_TYPE}:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key in ("seed", "noise_seed"):
            if key in inputs:
                inputs[key] = seed


def synchronize_prompt_rewrite_seeds(workflow: dict) -> None:
    """Normalize prepared graphs too, before their first image submission."""
    if not any(isinstance(node, dict) and node.get("class_type") == QWEN_REWRITE_NODE_TYPE for node in workflow.values()):
        return
    seed = extract_workflow_seed(workflow)
    if seed is not None:
        set_workflow_seed(workflow, seed)


def randomize_prompt_rewrite_seeds(workflow: dict) -> bool:
    """A rewrite retry changes the shared seed, preserving graph bindings."""
    rewrite_nodes = [node for node in workflow.values() if isinstance(node, dict) and node.get("class_type") == QWEN_REWRITE_NODE_TYPE]
    if not rewrite_nodes:
        return False
    previous = [node.get("inputs", {}).get("seed") for node in rewrite_nodes]
    seed = random.randint(1, QWEN_SEED_MAX)
    while seed in previous:
        seed = seed % QWEN_SEED_MAX + 1
    set_workflow_seed(workflow, seed)
    return True


def extract_workflow_seed(workflow: Any) -> Optional[int]:
    """Return a unique generation seed; ignore historical Qwen rewrite seeds."""
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
        if node.get("class_type") == QWEN_REWRITE_NODE_TYPE:
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
