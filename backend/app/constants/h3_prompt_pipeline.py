"""New-request default is separate from the pre-Phase-B persisted contract."""

DEFAULT_H3_PROMPT_PIPELINE = "phase_b"


def persisted_h3_prompt_pipeline(metadata: dict) -> str:
    """Never apply the new-request default to a historical Task/Job.

    Phase B has always persisted its route. Missing routes without a Phase B
    record retain Legacy semantics; inconsistent records need explicit review.
    """
    if "h3_prompt_pipeline" not in metadata:
        if metadata.get("h3_phase_b"):
            raise ValueError("H3_PROMPT_PIPELINE_MISSING: Phase B record has no persisted route")
        return "legacy"
    route = metadata["h3_prompt_pipeline"]
    if route not in ("legacy", "phase_b"):
        raise ValueError(f"H3_PROMPT_PIPELINE_INVALID: {route!r}")
    return route
