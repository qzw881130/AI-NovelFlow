from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()


def configure_sqlite_connection(dbapi_connection, database):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=15000")
    if database not in {None, "", ":memory:"}:
        cursor.execute("PRAGMA journal_mode=WAL")
        mode = cursor.fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError("SQLITE_WAL_REQUIRED")
    cursor.close()


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15.0} if "sqlite" in settings.DATABASE_URL else {}
)

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        configure_sqlite_connection(dbapi_connection, engine.url.database)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
