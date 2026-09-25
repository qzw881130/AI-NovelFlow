# Current Implementation State

## Production E2E Entry-Point Rule

Production end-to-end tests must trigger tasks through the currently running NovelFlow API or the normal product entry point. Do not use temporary Python scripts to dispatch tasks, directly mutate task state, or inject workflow inputs. This ensures production E2E exercises application startup, database configuration, credential loading, task lifecycle, and the real product flow. Diagnostic scripts may only read and validate state; they must not trigger generation or mutate it.

## Semantic Clip Retry Contract

`shot_video` tasks with `metadata_json.execution_scope == "CLIP"` are retried as the same semantic Clip. Retry preserves the Clip ID/index/revision, capability, planned/requested duration, dialogue assignment, and upstream approved Task/video provenance; it clears only attempt-specific result/error/ComfyUI execution state. Continuation retries fail closed if the original upstream dependency is no longer valid. The Clip worker resolves the same Clip from the saved Shot plan and uses the Task's dialogue assignment. Clip retry does not clear or replace `Shot.video_url`; only successful Final Assembly may update it. Ordinary Shot-level retries retain their existing behavior.

## Dialogue AV Handoff

Dialogue AV handoff across Clip boundaries remains unresolved and is not a Production E2E PASS. `VIDEO_CONTINUATION` and `TEMPORAL_EXTEND` retain their formal `Keep source audio` topology. `Regenerate with H3` is not a validated continuation strategy: `MiniMaxH3SourceAudioPolicy.regenerated_latent` requires the output of a separate `MiniMaxH3SourceAudioRegenMask` sampling branch; do not connect the continuation sampler output back into this policy. Design and validate boundary audio handoff separately before resuming the Long Shot E2E. C2 remains failed at output collection; do not retry until that work is explicitly resumed.
