from app.core.database import engine
from app.services.appearance_generation_schema import upgrade

if __name__ == "__main__":
    upgrade(engine)
    print("Phase4 generation schema ready; no image or Shot usage guessed")
