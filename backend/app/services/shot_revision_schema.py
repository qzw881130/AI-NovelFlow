from app.models.shot_revision import ShotRevision, ShotRevisionHead


def upgrade(engine):
    ShotRevision.__table__.create(engine, checkfirst=True)
    ShotRevisionHead.__table__.create(engine, checkfirst=True)
