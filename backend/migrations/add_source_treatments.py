"""Add nullable provenance storage; never backfill legacy/Planner data into treatments."""
from app.services.chapter_shot_split_schema import upgrade

if __name__=='__main__':
    from app.core.database import engine
    upgrade(engine)
