# R-P0.3 final targeted tests

Contracts: `v2-doc/角色服装系列需求/R_P0_3_SUPPORTED_CONTRACTS.md`.
Scope: creation-identity acknowledgement, strict Characters format, and bounded Source Speech/H3 product contracts. RP02-NEW-003 is P2/UNCERTAIN backlog; no RIR-009..011 deep review.

`test_supported_contracts.py` exercises complete schema/split validation, real authoring fixtures, and full H3 prepare. It includes legal audio-only narration, non-speech mouth action, explicit visible speech, and timed speaker contradictions.

Frontend tests:
- `tests/regression-p0-3-identity.test.mjs`: actual Zustand/action/projection with controlled response order; no text/order identity inference.
- `tests/regression-p0-3-live.e2e.mjs`: real private snapshot API creates UUIDs, withholds creation acknowledgement, publishes a newer revision, refreshes the real UI, releases the old map, and saves again.

Use `backend/tests/regression_review/serve_snapshot.py` for a fresh private database/authoring-only UI server (18001); Chrome CDP at 9222 is required for the live file. Set `REVIEW_EVIDENCE_DIR` to an existing temporary evidence directory. The server must be stopped after verification. Do not run live editing against production.

Do not use old arbitrary-language examples or unsupported synonym permutations as assertions of complete NLP coverage. Explicit supported speaker/grammar controls remain required, as do existing CAS, ID binding, Source and prequeue gates.
