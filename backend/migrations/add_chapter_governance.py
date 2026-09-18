import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.database import engine
from app.services.chapter_governance_schema import upgrade
if __name__=='__main__':
    upgrade(engine)
    print('Phase8 origin snapshot ready; no Binding, Event, source range or RSA inferred')
