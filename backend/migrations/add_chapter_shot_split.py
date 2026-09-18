"""Add only receipt tables; never infer source ranges for legacy Shots."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import engine
from app.services.chapter_shot_split_schema import upgrade

if __name__ == "__main__":
    upgrade(engine)
    print("Phase5 schema ready; legacy Shot sources remain unassigned")
