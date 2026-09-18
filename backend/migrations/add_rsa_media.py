import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.database import engine
from app.services.rsa_media_schema import upgrade

if __name__ == "__main__":
    upgrade(engine)
    print("Phase7 media schema ready; no legacy image lineage inferred")
