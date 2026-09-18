"""Trusted R5 pytest profiles with pre-import path and writer isolation."""

import os
from importlib.metadata import version
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile


BACKEND = Path(__file__).resolve().parents[1]
TEST_ROOT = (BACKEND / "tests").resolve()
CONFTEST = (TEST_ROOT / "conftest.py").resolve()
PYTEST_INI = (BACKEND / "pytest.ini").resolve()

PROFILES = {"pure": "PURE", "canonical-db": "CANONICAL_DB"}
WRITER_OPTIONS = {"--junit-xml", "--junitxml", "--log-file"}
UNSAFE_OPTIONS = {
    "--asyncio-mode", "--basetemp", "--confcutdir", "--debug", "--noconftest",
    "--override-ini", "--rootdir", "-c", "-m", "-o", "-p",
}
SAFE_FLAGS = {
    "--co", "--collect-only", "--continue-on-collection-errors", "--disable-pytest-warnings",
    "--disable-warnings", "--exitfirst", "--fixtures", "--fixtures-per-test", "--full-trace",
    "--funcargs", "--keep-duplicates", "--log-cli", "--no-header", "--no-showlocals",
    "--no-summary", "--quiet", "--setup-only", "--setup-plan", "--setup-show", "--showlocals",
    "--strict-config", "--strict-markers", "--trace-config", "--verbose", "-l", "-q", "-s", "-v", "-x",
}
VALUE_OPTIONS = {
    "--capture", "--code-highlight", "--color", "--durations", "--durations-min", "--junit-prefix",
    "--log-auto-indent", "--log-cli-date-format", "--log-cli-format", "--log-cli-level",
    "--log-date-format", "--log-disable", "--log-file-date-format", "--log-file-format",
    "--log-file-level", "--log-format", "--log-level", "--maxfail",
    "--show-capture", "--tb", "--verbosity", "-k", "-r",
}
_SHORT_UNSAFE = {"-c", "-m", "-o", "-p"}
_SHORT_VALUE = {"-k", "-r"}
_RUNNER_ENV = {
    "R5_RUNNER_BOOTSTRAP_ROOT", "R5_RUNNER_CONFTEST_RESPONSE", "R5_RUNNER_GUARD_CHALLENGE",
    "R5_RUNNER_GUARD_RESPONSE", "R5_RUNNER_GUARD_SOURCE",
}


class PreflightError(ValueError):
    pass


def _is_option(argument, option):
    if argument == option or argument.startswith(option + "="):
        return True
    return option in _SHORT_UNSAFE and argument.startswith(option) and len(argument) > len(option)


def _parse_arguments(arguments):
    options, selectors, writers = [], [], []
    index = 0
    positional_only = False
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith("@"):
            raise PreflightError(f"pytest argument files are not allowed: {argument}")
        if positional_only:
            selectors.append(argument)
            index += 1
            continue
        if argument == "--":
            positional_only = True
            index += 1
            continue
        if not argument.startswith("-") or argument == "-":
            selectors.append(argument)
            index += 1
            continue
        for unsafe in UNSAFE_OPTIONS:
            if _is_option(argument, unsafe):
                raise PreflightError(f"isolation override is not allowed: {argument}")
        writer = next((name for name in WRITER_OPTIONS if argument == name or argument.startswith(name + "=")), None)
        if writer:
            if argument == writer:
                index += 1
                if index >= len(arguments):
                    raise PreflightError(f"missing output path for {writer}")
                value = arguments[index]
            else:
                value = argument.split("=", 1)[1]
            if not value:
                raise PreflightError(f"missing output path for {writer}")
            writers.append((writer, value))
            index += 1
            continue
        if argument in SAFE_FLAGS or re.fullmatch(r"-[qv]+", argument):
            options.append(argument)
            index += 1
            continue
        value_option = next(
            (name for name in VALUE_OPTIONS if argument == name or argument.startswith(name + "=")), None
        )
        if value_option:
            if argument == value_option:
                index += 1
                if index >= len(arguments):
                    raise PreflightError(f"missing value for {value_option}")
                value = arguments[index]
                if value.startswith(("-", "@")):
                    raise PreflightError(f"unsafe value for {value_option}: {value}")
                if value_option.startswith("--"):
                    options.append(f"{value_option}={value}")
                else:
                    options.extend((value_option, value))
            else:
                options.append(argument)
            index += 1
            continue
        short_value = next(
            (name for name in _SHORT_VALUE if argument.startswith(name) and len(argument) > len(name)), None
        )
        if short_value:
            value = argument[len(short_value):].removeprefix("=")
            if not value or value.startswith(("-", "@")):
                raise PreflightError(f"unsafe value for {short_value}: {value}")
            options.extend((short_value, value))
            index += 1
            continue
        raise PreflightError(f"unsupported pytest option: {argument}")
    if len({name for name, _ in writers}) != len(writers):
        raise PreflightError("duplicate pytest output writer option")
    return options, selectors, writers


def _normalize_selectors(selectors):
    normalized = []
    for selector in selectors or [str(TEST_ROOT)]:
        path_text, separator, node_suffix = selector.partition("::")
        if not path_text:
            raise PreflightError(f"invalid pytest selector: {selector}")
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = BACKEND / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PreflightError(f"pytest selector does not resolve: {selector}") from exc
        if resolved != TEST_ROOT and not resolved.is_relative_to(TEST_ROOT):
            raise PreflightError(f"pytest selector escapes approved test root: {selector}")
        normalized.append(str(resolved) + ("::" + node_suffix if separator else ""))
    return normalized


def _normalize_writer_path(root, option, value):
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise PreflightError(f"{option} output must be relative to the private artifact root: {value}")
    candidate = root / raw
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PreflightError(f"{option} output does not resolve: {value}") from exc
    if resolved == root or not resolved.is_relative_to(root):
        raise PreflightError(f"{option} output escapes approved artifact root: {value}")
    return resolved


def _prepare_writers(writers):
    if not writers:
        os.environ.pop("R5_ARTIFACT_ROOT", None)
        return []
    root = Path(tempfile.mkdtemp(prefix="novelflow-r5-artifacts-", dir="/tmp")).resolve()
    try:
        rewritten = [f"{option}={_normalize_writer_path(root, option, value)}" for option, value in writers]
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    os.environ["R5_ARTIFACT_ROOT"] = str(root)
    print(f"R5_ARTIFACT_ROOT={root}", file=sys.stderr)
    return rewritten


def _neutralize_pytest_environment():
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for name in ("PYTEST_ADDOPTS", "PYTEST_DEBUG_TEMPROOT", "PYTEST_PLUGINS", "TEMP", "TMP", "TMPDIR"):
        os.environ.pop(name, None)
    for name in _RUNNER_ENV:
        os.environ.pop(name, None)


def _establish_bootstrap():
    early = [name for name in sys.modules if name == "pytest" or name == "app" or name.startswith("app.")]
    if early:
        raise PreflightError(f"pytest/application imported before runner bootstrap: {sorted(early)[:3]}")
    handle = tempfile.TemporaryDirectory(prefix="novelflow-r5-runner-", dir="/tmp")
    root = Path(handle.name).resolve()
    challenge = secrets.token_hex(32)
    os.environ["DATABASE_URL"] = f"sqlite:///{root / 'bootstrap.sqlite3'}"
    os.environ["NOVELFLOW_STORAGE_ROOT"] = str(root / "storage")
    os.environ["R5_RUNNER_BOOTSTRAP_ROOT"] = str(root)
    os.environ["R5_RUNNER_GUARD_CHALLENGE"] = challenge
    return handle, challenge


def _run():
    if len(sys.argv) < 2 or sys.argv[1] not in PROFILES:
        choices = " | ".join(PROFILES)
        raise PreflightError(f"usage: {Path(sys.argv[0]).name} <{choices}> [pytest args]")
    profile = PROFILES[sys.argv[1]]
    options, selectors, writers = _parse_arguments(sys.argv[2:])
    selectors = _normalize_selectors(selectors)
    _neutralize_pytest_environment()
    writer_options = _prepare_writers(writers)
    if version("pytest-asyncio") != "0.23.5":
        raise PreflightError("R5 profiles require pytest-asyncio==0.23.5")
    bootstrap, challenge = _establish_bootstrap()
    sys.dont_write_bytecode = True
    os.chdir(BACKEND)
    try:
        import pytest

        class SharedGuard:
            def verify_configuration(self, session):
                source = os.environ.get("R5_RUNNER_GUARD_SOURCE")
                if (os.environ.get("R5_RUNNER_CONFTEST_RESPONSE") != challenge or not source
                        or Path(source).resolve() != CONFTEST
                        or session.config.rootpath.resolve() != BACKEND
                        or not session.config.inipath or session.config.inipath.resolve() != PYTEST_INI):
                    raise pytest.UsageError("R5 shared bootstrap/profile guard was not established")

            @pytest.hookimpl(tryfirst=True)
            def pytest_sessionstart(self, session):
                self.verify_configuration(session)

            @pytest.hookimpl(tryfirst=True)
            def pytest_collection_finish(self, session):
                self.verify_configuration(session)
                if os.environ.get("R5_RUNNER_GUARD_RESPONSE") != challenge:
                    raise pytest.UsageError("R5 shared profile collection guard did not execute")

        return pytest.main(
            ["-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider", "-c", str(PYTEST_INI),
             "--rootdir", str(BACKEND), "-o", "addopts=", "-o", "log_file=", "--strict-markers",
             "--asyncio-mode=strict", *options, *writer_options, *selectors, "-m", profile],
            plugins=[SharedGuard()],
        )
    finally:
        bootstrap.cleanup()


def main():
    try:
        return _run()
    except PreflightError as exc:
        print(f"R5_PREFLIGHT_REJECT: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
