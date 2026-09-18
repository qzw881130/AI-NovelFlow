from app.models.rsa_media import RsaImageAttempt, RsaMediaArtifact


def upgrade(bind):
    with bind.begin() as connection:
        for model in (RsaImageAttempt,RsaMediaArtifact):
            model.__table__.create(connection,checkfirst=True)
