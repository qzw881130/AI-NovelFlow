"""C01 proof that both R5 lanes execute inside process-private resources."""

import asyncio
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest


BACKEND = Path(__file__).resolve().parents[1]
TEST_ROOT = (BACKEND / "tests").resolve()
RUNNER = TEST_ROOT / "r5_runner.py"
ARTIFACT_PARENT = Path("/tmp").resolve()
RUNNER_ENV = {
    "R5_ARTIFACT_ROOT", "R5_RUNNER_BOOTSTRAP_ROOT", "R5_RUNNER_CONFTEST_RESPONSE",
    "R5_RUNNER_GUARD_CHALLENGE", "R5_RUNNER_GUARD_RESPONSE", "R5_RUNNER_GUARD_SOURCE",
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runner_env(**updates):
    environment = os.environ.copy()
    for name in RUNNER_ENV:
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update({name: str(value) for name, value in updates.items()})
    return environment


def _run_runner(arguments, *, environment=None):
    return subprocess.run(
        [sys.executable, str(RUNNER), "pure", *arguments], cwd=BACKEND,
        env=environment or _runner_env(), capture_output=True, text=True, timeout=60,
    )


def _assert_preflight_reject(result, *canaries):
    assert result.returncode == 2, result.stdout + result.stderr
    assert "R5_PREFLIGHT_REJECT:" in result.stderr
    assert " passed" not in result.stdout
    for path, expected_hash in canaries:
        assert _sha256(path) == expected_hash


@contextmanager
def _internal_execution_probe(tmp_path):
    marker = tmp_path / f"pytest-execution-{uuid4().hex}.canary"
    marker.write_bytes(b"PYTEST_NOT_EXECUTED")
    probe = TEST_ROOT / f"test_r5_runner_probe_{uuid4().hex}.py"
    probe.write_text(
        "from pathlib import Path\n"
        "import logging\n"
        "import pytest\n"
        "pytestmark = pytest.mark.PURE\n"
        "def test_runner_probe():\n"
        "    logging.getLogger(__name__).warning('R5_PRIVATE_LOG_ARTIFACT')\n"
        f"    Path({str(marker)!r}).write_bytes(b'PYTEST_EXECUTED')\n"
    )
    try:
        yield f"tests/{probe.name}::test_runner_probe", marker
    finally:
        probe.unlink(missing_ok=True)


@pytest.mark.PURE
@pytest.mark.asyncio
async def test_pure_profile_executes_async_in_process_sandbox():
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().is_running()
    storage_root = Path(os.environ["NOVELFLOW_STORAGE_ROOT"]).resolve()
    database_path = Path(os.environ["DATABASE_URL"].removeprefix("sqlite:///")).resolve()
    assert database_path.name == "bootstrap.sqlite3"
    assert database_path.parent == storage_root.parent
    assert database_path.parent.name.startswith("novelflow-pytest-")
    assert not storage_root.is_relative_to(BACKEND)
    challenge = os.environ["R5_RUNNER_GUARD_CHALLENGE"]
    assert os.environ["R5_RUNNER_CONFTEST_RESPONSE"] == challenge
    assert os.environ["R5_RUNNER_GUARD_RESPONSE"] == challenge
    assert Path(os.environ["R5_RUNNER_GUARD_SOURCE"]).resolve() == TEST_ROOT / "conftest.py"
    runner_bootstrap = Path(os.environ["R5_RUNNER_BOOTSTRAP_ROOT"]).resolve()
    assert runner_bootstrap.is_dir()
    assert runner_bootstrap.name.startswith("novelflow-r5-runner-")
    assert not runner_bootstrap.is_relative_to(BACKEND)


@pytest.mark.PURE
@pytest.mark.parametrize("scenario", [
    "isolation-options", "external-selector", "junit-canary", "log-canary", "positive-private-artifacts",
])
def test_profile_runner_rejects_isolation_overrides(scenario, tmp_path):
    if scenario == "isolation-options":
        attacks = [
            ["--noconftest"], ["-mPURE"], ["-oaddopts="], ["--override-ini=addopts="],
            ["-pno:conftest"], ["-cother.ini"], ["--rootdir=/tmp"], ["--confcutdir=/tmp"],
            ["--asyncio-mode=auto"], ["--basetemp=/tmp/r5-fixed"],
        ]
        for attack in attacks:
            _assert_preflight_reject(_run_runner(attack))
        return

    if scenario == "external-selector":
        marker = tmp_path / "external-selector.canary"
        marker.write_bytes(b"PYTEST_NOT_EXECUTED")
        expected = _sha256(marker)
        outside = tmp_path / "test_boundary_probe.py"
        outside.write_text(
            "from pathlib import Path\n"
            "import pytest\n"
            "pytestmark = pytest.mark.PURE\n"
            "def test_external_boundary():\n"
            f"    Path({str(marker)!r}).write_bytes(b'PYTEST_EXECUTED')\n"
        )
        absolute = _run_runner([str(outside), "-q"])
        _assert_preflight_reject(absolute, (marker, expected))
        return

    if scenario == "junit-canary":
        with _internal_execution_probe(tmp_path) as (selector, execution_marker):
            execution_hash = _sha256(execution_marker)
            database_canary = tmp_path / "canary-database.sqlite3"
            database_canary.write_bytes(b"PRIVATE_DATABASE_CANARY")
            database_hash = _sha256(database_canary)
            result = _run_runner([selector, f"--junitxml={database_canary}", "-q"])
            _assert_preflight_reject(result, (execution_marker, execution_hash), (database_canary, database_hash))
        return

    if scenario == "log-canary":
        with _internal_execution_probe(tmp_path) as (selector, execution_marker):
            execution_hash = _sha256(execution_marker)
            media_root = tmp_path / "canary-media"
            media_root.mkdir()
            media_canary = media_root / "keep.txt"
            media_canary.write_bytes(b"PRIVATE_MEDIA_CANARY")
            media_hash = _sha256(media_canary)
            result = _run_runner([selector, f"--log-file={media_canary}", "-q"])
            _assert_preflight_reject(result, (execution_marker, execution_hash), (media_canary, media_hash))
        return

    with _internal_execution_probe(tmp_path) as (selector, execution_marker):
        result = _run_runner([
            selector, "--junitxml=private-results.xml", "--log-file=private-pytest.log", "-q",
            "--disable-warnings",
        ])
        assert result.returncode == 0, result.stdout + result.stderr
        match = re.search(r"^R5_ARTIFACT_ROOT=(.+)$", result.stderr, re.MULTILINE)
        assert match
        root = Path(match.group(1)).resolve()
        try:
            assert root.parent == ARTIFACT_PARENT
            assert root.stat().st_mode & 0o077 == 0
            assert (root / "private-results.xml").is_file()
            assert (root / "private-pytest.log").is_file()
            assert "test_runner_probe" in (root / "private-results.xml").read_text()
            assert "R5_PRIVATE_LOG_ARTIFACT" in (root / "private-pytest.log").read_text()
            assert execution_marker.read_bytes() == b"PYTEST_EXECUTED"
        finally:
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.CANONICAL_DB
def test_canonical_profile_isolates_registry_database_storage_and_lifespan(
    client, db_engine, canonical_storage_root,
):
    from sqlalchemy.orm import configure_mappers
    from app import main as main_module
    from app.api import shots as shots_api
    from app.core import database
    from app.services.file_storage import file_storage

    configure_mappers()
    assert len(list(database.Base.registry.mappers)) >= 45
    assert db_engine.url.database == ":memory:"
    assert database.engine is main_module.engine is db_engine
    assert database.SessionLocal.kw["bind"] is db_engine
    assert file_storage.base_dir == canonical_storage_root
    assert not canonical_storage_root.is_relative_to(BACKEND)
    assert Path(os.environ["NOVELFLOW_STORAGE_ROOT"]).resolve() == canonical_storage_root
    assert main_module.app.router.lifespan_context is not main_module.lifespan
    isolated_workers = main_module.app.state.pytest_worker_manager
    assert isolated_workers.workers == {}
    assert shots_api.worker_manager is isolated_workers
    isolated_workers.worker("r5-proof").enqueue(lambda: None)
    assert len(isolated_workers.workers["r5-proof"].jobs) == 1
    assert not hasattr(isolated_workers.workers["r5-proof"], "_runner")
    worker_state = (
        "task_reconcile_task", "audio_drive_tts_task", "audio_drive_prepare_task", "shot_video_batch_task",
        "shot_video_task", "appearance_task", "rsa_image_task", "rebuild_task",
    )
    assert not any(hasattr(main_module.app.state, name) for name in worker_state)
    assert client.get("/").status_code == 200


@pytest.mark.CANONICAL_DB
def test_c02_isolators_reference_one_canonical_registry():
    from sqlalchemy import inspect
    from sqlalchemy.orm import configure_mappers
    from app.core import database
    from app.models.appearance_timeline import CharacterAppearance
    from app.models.chapter_shot_split import ShotSource
    from app.models.resolved_shot_assets import ResolvedShotAssets
    from app.models.rsa_media import RsaImageAttempt
    from app.models.shot import Shot
    from app.models.shot_revision import ShotRevision
    import test_execution_integrity_api as api_isolator
    import test_h3_prompt_worker as worker_isolator

    configure_mappers()
    required_tables = {
        "character_appearances", "external_failure_observations", "resolved_shot_assets",
        "rsa_image_attempts", "shot_revisions", "shot_sources", "asset_resolution_omissions",
    }
    assert len(database.Base.metadata.tables) == 47
    assert required_tables <= set(database.Base.metadata.tables)
    assert all(inspect(model).registry is database.Base.registry for model in (
        CharacterAppearance, ResolvedShotAssets, RsaImageAttempt, Shot, ShotRevision, ShotSource,
    ))
    assert not hasattr(api_isolator, "declarative_base")
    assert not hasattr(worker_isolator, "declarative_base")
    assert worker_isolator.Shot is Shot
    assert api_isolator.APP_BASE is database.Base
    assert api_isolator._API_MODELS["shot"].Shot is Shot
    assert {id(mapper.registry) for mapper in database.Base.registry.mappers} == {id(database.Base.registry)}
