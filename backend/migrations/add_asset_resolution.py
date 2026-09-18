"""Phase2 creates identity/binding receipts; never guesses types or memberships for old assets."""
from app.core.database import engine
from app.models.asset_resolution import (CharacterIdentity, CharacterAlias, AssetResolutionLease,
    AssetResolutionRun, AssetResolutionDecision, AssetResolutionOmission, ChapterCharacterBinding, ChapterSceneBinding,
    ChapterPropBinding, ChapterCharacterAppearanceEvent)


def upgrade(bind):
    with bind.begin() as connection:
        for model in (CharacterIdentity, CharacterAlias, AssetResolutionLease, AssetResolutionRun,
                      AssetResolutionDecision, AssetResolutionOmission, ChapterCharacterBinding, ChapterSceneBinding,
                      ChapterPropBinding, ChapterCharacterAppearanceEvent):
            model.__table__.create(connection, checkfirst=True)


if __name__ == "__main__":
    upgrade(engine)
    print("Phase2 identity/binding tables ready; no legacy type or binding backfill")
