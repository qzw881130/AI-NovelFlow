"""Shared pytest profiles with process-private application resources."""

from contextlib import asynccontextmanager
import inspect
import os
import sys
import tempfile
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
_CONFTEST = Path(__file__).resolve()
sys.path.insert(0, str(BACKEND))

_early_application_modules = {
    "app.core.config", "app.core.database", "app.services.file_storage", "app.main",
}.intersection(sys.modules)
if _early_application_modules:
    raise RuntimeError(f"Application imported before pytest isolation: {sorted(_early_application_modules)}")

_sandbox_handle = tempfile.TemporaryDirectory(prefix="novelflow-pytest-", dir="/tmp")
_sandbox = Path(_sandbox_handle.name).resolve()
# Override hostile or production-looking caller values before importing any app module.
os.environ["DATABASE_URL"] = f"sqlite:///{_sandbox / 'bootstrap.sqlite3'}"
os.environ["NOVELFLOW_STORAGE_ROOT"] = str(_sandbox / "storage")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


_CANONICAL_FIXTURES = {"canonical_storage_root", "db_engine", "db_session", "client"}


def pytest_configure(config):
    challenge = os.environ.get("R5_RUNNER_GUARD_CHALLENGE")
    if challenge:
        os.environ["R5_RUNNER_CONFTEST_RESPONSE"] = challenge
        os.environ["R5_RUNNER_GUARD_SOURCE"] = str(_CONFTEST)


def _uses_shared_canonical_fixture(item):
    fixture_info = getattr(item, "_fixtureinfo", None)
    if fixture_info is None:
        return False
    for name in _CANONICAL_FIXTURES:
        definitions = fixture_info.name2fixturedefs.get(name) or ()
        if definitions:
            source = inspect.getsourcefile(definitions[-1].func)
            if source and Path(source).resolve() == _CONFTEST:
                return True
    return False


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        declared = {name for name in ("PURE", "CANONICAL_DB") if item.get_closest_marker(name)}
        uses_canonical = _uses_shared_canonical_fixture(item)
        if len(declared) > 1:
            raise pytest.UsageError(f"{item.nodeid} declares both R5 profiles")
        if declared == {"PURE"} and uses_canonical:
            raise pytest.UsageError(f"{item.nodeid} is PURE but resolves a shared canonical fixture")
        if not declared and uses_canonical:
            item.add_marker("CANONICAL_DB")
    challenge = os.environ.get("R5_RUNNER_GUARD_CHALLENGE")
    if challenge:
        os.environ["R5_RUNNER_GUARD_RESPONSE"] = challenge


def pytest_unconfigure(config):
    database = sys.modules.get("app.core.database")
    engine = getattr(database, "engine", None)
    if engine is not None:
        engine.dispose()
    _sandbox_handle.cleanup()


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def canonical_storage_root(tmp_path, monkeypatch):
    from app.services.file_storage import file_storage

    root = (tmp_path / "storage").resolve()
    root.mkdir()
    monkeypatch.setenv("NOVELFLOW_STORAGE_ROOT", str(root))
    monkeypatch.setattr(file_storage, "base_dir", root)
    return root


@pytest.fixture
def db_engine(canonical_storage_root, monkeypatch):
    """Create one complete-registry engine isolated from application storage."""
    from app.core import database
    from app import main as main_module

    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = database.SessionLocal
    previous_bind = session_factory.kw.get("bind")
    session_factory.configure(bind=engine)
    monkeypatch.setenv("DATABASE_URL", SQLALCHEMY_DATABASE_URL)
    monkeypatch.setattr(database.settings, "DATABASE_URL", SQLALCHEMY_DATABASE_URL)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(main_module, "engine", engine)
    database.Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        database.Base.metadata.drop_all(bind=engine)
        session_factory.configure(bind=previous_bind)
        engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Yield a session from the same rebound SessionLocal seen by app aliases."""
    from app.core import database

    session = database.SessionLocal()
    assert session.bind is db_engine
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session, monkeypatch):
    """Run the full router under a test-only lifespan with no monitor or workers."""
    from app.core.database import get_db
    from app.main import app
    from app.api.config import init_system_config
    from app.api.prompt_templates import init_system_prompt_templates
    from app.api.test_cases import init_preset_test_cases
    from app.services import background_workers

    class IsolatedWorker:
        def __init__(self):
            self.jobs = []

        def enqueue(self, job_factory):
            self.jobs.append(job_factory)

    class IsolatedWorkerManager:
        def __init__(self):
            self.workers = {}

        def worker(self, name):
            return self.workers.setdefault(name, IsolatedWorker())

    production_worker_manager = background_workers.worker_manager
    isolated_worker_manager = IsolatedWorkerManager()
    monkeypatch.setattr(background_workers, "worker_manager", isolated_worker_manager)
    for module in tuple(sys.modules.values()):
        if getattr(module, "worker_manager", None) is production_worker_manager:
            monkeypatch.setattr(module, "worker_manager", isolated_worker_manager)
    monkeypatch.setattr(app.state, "pytest_worker_manager", isolated_worker_manager, raising=False)

    def override_get_db():
        yield db_session

    @asynccontextmanager
    async def isolated_lifespan(_app):
        init_system_config(db_session)
        init_system_prompt_templates(db_session)
        await init_preset_test_cases(db_session)
        yield

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(app.router, "lifespan_context", isolated_lifespan)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


@pytest.fixture
def sample_novel_data():
    """示例小说数据"""
    return {
        "title": "测试小说",
        "author": "测试作者",
        "description": "这是一个测试小说"
    }


@pytest.fixture
def sample_chapter_data():
    """示例章节数据"""
    return {
        "number": 1,
        "title": "第一章 测试章节",
        "content": "这是测试章节的内容。主角小明走进房间，看到了小红。"
    }


@pytest.fixture
def sample_parsed_data():
    """示例解析后的章节数据"""
    return {
        "characters": ["小明", "小红"],
        "scenes": ["房间"],
        "props": [],
        "transition_videos": {},
        "shots": [
            {
                "description": "主角小明走进房间",
                "characters": ["小明"],
                "scene": "房间",
                "props": [],
                "duration": 4,
                "dialogues": []
            },
            {
                "description": "小明看到了小红",
                "characters": ["小明", "小红"],
                "scene": "房间",
                "props": [],
                "duration": 4,
                "dialogues": [
                    {
                        "character_name": "小明",
                        "text": "你好，小红！"
                    }
                ]
            }
        ]
    }
