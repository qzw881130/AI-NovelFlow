"""Create empty authoring ledgers. Do not infer revisions from legacy Shot data."""
from app.services.shot_revision_schema import upgrade

if __name__ == '__main__':
    from app.core.database import engine
    upgrade(engine)
