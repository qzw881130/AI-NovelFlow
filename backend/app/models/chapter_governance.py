from datetime import datetime
from sqlalchemy import Column,String,Integer,JSON,DateTime,Index,text
from app.core.database import Base


class ChapterLifecycle(Base):
    __tablename__='chapter_asset_lifecycle'
    chapter_id=Column(String,primary_key=True)
    novel_id=Column(String,nullable=False,index=True)
    origin=Column(String,nullable=False)  # provenance, not readiness
    origin_evidence=Column(JSON,nullable=False)
    rebuild_id=Column(String,nullable=True)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)


class ChapterRebuildRun(Base):
    __tablename__='chapter_asset_rebuilds'
    __table_args__=(Index('uq_running_book_rebuild','novel_id',unique=True,
        sqlite_where=text("status IN ('PENDING','RUNNING')"),postgresql_where=text("status IN ('PENDING','RUNNING')")),)
    id=Column(String,primary_key=True)
    task_id=Column(String,nullable=False,unique=True)
    novel_id=Column(String,nullable=False,index=True)
    chapter_id=Column(String,nullable=False,index=True)
    status=Column(String,nullable=False)
    inputs=Column(JSON,nullable=False)
    input_hash=Column(String,nullable=False)
    steps=Column(JSON,nullable=False,default=list)
    result=Column(JSON,nullable=False,default=dict)
    result_hash=Column(String,nullable=True)
    error=Column(String,nullable=True)
    claim_token=Column(String,nullable=True)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    completed_at=Column(DateTime,nullable=True)
