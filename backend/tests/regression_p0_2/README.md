# R-P0.2 targeted regressions

Only new finding input: `v2-doc/角色服装系列需求/R_P0_1_INDEPENDENT_REVIEW.md`.

- `test_source_contracts.py`: TG-01/02/03/06 and actual publisher UUID mapping for TG-05. Tests use complete source/authoring publication, not a silent fixture as an audio proof.
- `test_h3_scope.py`: TG-07/08 through complete H3 `prepare_h3_prompt`, including mixed timelines and opposing controls.
- Frontend `tests/regression-p0-2-state.test.mjs`: TG-04/05 with actual zustand data slice and request projection.
- Frontend `tests/regression-p0-2-live.e2e.mjs`: actual UI/API JSON/import, partial/pending/late response and new UUID workflows on the private snapshot server.

RIR-003/006 are protected closed behaviors. RIR-009/010/011 are outside this round's deep-review; do not use an all-files review/media test command to claim their closure.

Commands, RED evidence, actual private DB and UI response locations are in `R_P0_2_CLOSURE_REPORT.md`. Builder conclusions await user-initiated independent re-attack; no cross-Session automation is used.
