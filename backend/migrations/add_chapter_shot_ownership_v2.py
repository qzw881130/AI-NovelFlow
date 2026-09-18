"""Add nullable F07 ownership metadata without changing historical Source rows."""
from app.services.chapter_shot_split_schema import upgrade


if __name__ == '__main__':
    from app.core.database import engine
    upgrade(engine)
