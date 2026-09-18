from app.core.database import engine
from app.services.appearance_timeline_schema import upgrade

if __name__ == "__main__":
    upgrade(engine)
    print("Phase3 timeline schema ready; no inferred locations or appearances backfilled")
