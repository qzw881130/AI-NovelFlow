from app.models.resolved_shot_assets import ResolvedShotAssets, ShotAssetHead, ResolvedImageVersion, ShotAppearanceDemand


def upgrade(bind):
    with bind.begin() as connection:
        for model in (ResolvedShotAssets, ShotAssetHead, ResolvedImageVersion, ShotAppearanceDemand):
            model.__table__.create(connection, checkfirst=True)
