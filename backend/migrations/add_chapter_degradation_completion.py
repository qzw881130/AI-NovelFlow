"""R-CD1 additive fields. Existing Shots remain NORMAL; no degradation is inferred."""
from app.services.chapter_shot_split_schema import upgrade


def migrate(engine):
    upgrade(engine)


if __name__ == '__main__':
    from app.core.database import engine
    migrate(engine)
