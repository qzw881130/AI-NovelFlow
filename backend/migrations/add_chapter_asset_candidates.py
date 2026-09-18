"""Phase 1: create evidence tables only; never infer bindings from legacy Shots.

PYTHONPATH=. venv/bin/python -B migrations/add_chapter_asset_candidates.py
"""
from app.core.database import engine
from app.models.chapter_asset_parse import ChapterAssetParseRun, ChapterAssetCandidate


def upgrade(bind):
    with bind.begin() as connection:
        ChapterAssetParseRun.__table__.create(connection, checkfirst=True)
        ChapterAssetCandidate.__table__.create(connection, checkfirst=True)


if __name__ == "__main__":
    upgrade(engine)
    print("Phase 1 candidate evidence tables ready; no legacy data backfilled")
