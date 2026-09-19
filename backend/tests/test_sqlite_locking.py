import sqlite3
import threading
import time

from app.core.database import configure_sqlite_connection


def connection(path):
    db = sqlite3.connect(path, timeout=0, check_same_thread=False)
    configure_sqlite_connection(db, str(path))
    return db


def test_sqlite_connections_use_wal_and_busy_timeout(tmp_path):
    db = connection(tmp_path / "locking.sqlite3")
    assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 15000
    db.close()


def test_sqlite_busy_timeout_waits_for_short_writer_lock(tmp_path):
    path = tmp_path / "writer.sqlite3"
    first, second = connection(path), connection(path)
    first.execute("CREATE TABLE values_table (value INTEGER)");first.commit()
    first.execute("BEGIN IMMEDIATE");first.execute("INSERT INTO values_table VALUES (1)")
    result = {}

    def write_second():
        try:
            second.execute("INSERT INTO values_table VALUES (2)");second.commit();result["ok"] = True
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=write_second);thread.start();time.sleep(0.1)
    assert thread.is_alive()
    first.commit();thread.join(timeout=5)
    assert result == {"ok": True}
    assert first.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 2
    first.close();second.close()


def test_sqlite_wal_writer_does_not_wait_for_reader(tmp_path):
    path = tmp_path / "reader.sqlite3"
    reader, writer = connection(path), connection(path)
    reader.execute("CREATE TABLE values_table (value INTEGER)");reader.execute("INSERT INTO values_table VALUES (1)");reader.commit()
    reader.execute("BEGIN");reader.execute("SELECT * FROM values_table").fetchall()
    writer.execute("INSERT INTO values_table VALUES (2)");writer.commit()
    assert reader.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 1
    reader.commit()
    assert reader.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 2
    reader.close();writer.close()
