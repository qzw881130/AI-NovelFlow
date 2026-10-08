"""Optional safe manual Inspector preview: read-only DB, no main lifespan/workers.

From backend: venv/bin/python tests/inspector_preview.py --port 8011
Build the frontend first. Writes are limited to Inspector sidecars/cache.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import uvicorn

from app.api.clip_execution_inspector import frames, router
from app.core.database import get_db

ROOT = Path(__file__).parents[2]
DATABASE = ROOT / "backend/novelflow.db"
DIST = ROOT / "frontend/my-app/dist"


def connection():
    conn = sqlite3.connect(DATABASE.as_uri() + "?mode=ro", uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only=ON")
    return conn


engine = create_engine("sqlite://", creator=connection)
app = FastAPI(title="Inspector read-only local preview")
app.include_router(router, prefix="/api/clip-execution-inspector")


def readonly_db():
    with Session(engine, autoflush=False) as session:
        yield session


app.dependency_overrides[get_db] = readonly_db


@app.get("/api/config")
@app.get("/api/config/")
def preview_config():
    return {"success": True, "data": {}}


@app.get("/api/files/{relative:path}")
def media(relative: str):
    return FileResponse(frames.resolve_path("/api/files/" + relative))


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    file = (DIST / path).resolve()
    if not file.is_relative_to(DIST.resolve()):
        raise HTTPException(403)
    if not file.is_file():
        file = DIST / "index.html"
    if not file.is_file():
        raise HTTPException(503, "Build frontend before opening Inspector preview")
    return FileResponse(file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
