"""Only add Phase6 receipts. No legacy Shot relation or image version is inferred."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import engine
from app.services.resolved_shot_assets_schema import upgrade

if __name__ == "__main__":
    upgrade(engine)
    print("Phase6 schema ready; RSA and image versions require explicit resolution")
