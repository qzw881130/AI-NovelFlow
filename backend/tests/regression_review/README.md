# R-P0.1 permanent regression reproduction

Finding authority: `v2-doc/角色服装系列需求/R_P0_INDEPENDENT_REVIEW.md` (unchanged).

- `test_rir_contracts.py`: RIR-001 / 002 / 007, complete schema → split → coverage and real source/revision fixtures.
- `test_rir_h3.py`: RIR-008, full `prepare_h3_prompt` documents and opposing silence/speech controls.
- `test_rir_revision.py`: RIR-003 / 004, actual HTTP routers and authoring publication.
- `test_rir_media_dependencies.py`: RIR-010 / 011, **private SQLite copies** with existing real RSA/TTS/Timeline/multi-Clip/video receipts. Set `REVIEW_SOURCE_DB` explicitly; it is opened read-only. Without it these environment-dependent cases are reported skipped, never replaced with silent mock fixtures.

Backend (cwd `backend`; dependencies from the project venv):

```sh
REVIEW_SOURCE_DB="$PWD/novelflow.db" PYTHONPATH="$PWD:$PWD/tests" DATABASE_URL=sqlite:///:memory: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ./venv/bin/python -B -m pytest --noconftest -p no:cacheprovider tests/regression_review -q
```

Real mounted UI + real API evidence (no mock API responses):

1. Build the frontend: `npm run build` in `frontend/my-app`.
2. In `backend`, run `./venv/bin/python -B tests/regression_review/serve_snapshot.py --source-db "$PWD/novelflow.db" --database /path/to/new-private-review.db`.
3. Provide Chrome CDP at `http://127.0.0.1:9222` (or `REVIEW_CDP_URL`), then in `frontend/my-app` run:

```sh
REVIEW_EVIDENCE_DIR=/path/to/existing-evidence-directory REVIEW_RUN_LABEL=review node --test tests/regression-review-live.e2e.mjs
```

The server uses port 18001, disables lifespan/workers and restricts writes to formal Shot/Event PATCH routes. It never overwrites the source DB, existing destinations, or media. Tests operate on the six existing Wolf source IDs as **editing/media receipt fixtures**, not as the oracle for general narrative correctness. Generic narrative/H3 counterexamples are independent tests above. Stop the private server after collecting evidence.

All `CLOSED` conclusions in Builder's closure report remain subject to the original independent Code Review Session's re-attack.
