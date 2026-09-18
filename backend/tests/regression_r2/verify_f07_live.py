"""Independently re-open and verify the private R2-B/F07 product chain read-only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit


OWNERSHIP = "chapter-shot-ownership-v2"
RUN_VERSION = "chapter-scope-shot-split-v2.0.0"
SOURCE_TEXT = "🐺刘备在桃园站定。"


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_hashes(path):
    result = {}
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(path) + suffix)
        if target.is_file():
            result[target.name] = file_sha(target)
    return result


def protected_rows(path, tables):
    result = {}
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            require(columns, f"SOURCE_TABLE_MISSING: {table}")
            keys = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")') if row[5]]
            require(keys, f"SOURCE_PRIMARY_KEY_MISSING: {table}")
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            result[table] = {tuple(row[key] for key in keys): {column: row[column] for column in columns} for row in rows}
    return result


def verify_source_copy(source_db, private_db):
    tables = (
        "novels", "chapters", "characters", "scenes", "props", "shot_sources",
        "chapter_shot_split_runs", "shot_revisions", "llm_logs", "tasks",
    )
    source = protected_rows(source_db, tables)
    private = protected_rows(private_db, tables)
    counts = {}
    for table in tables:
        shared_columns = set(next(iter(source[table].values()), {})) & set(next(iter(private[table].values()), {}))
        for identity, expected in source[table].items():
            require(identity in private[table], f"SOURCE_ROW_MISSING: {table} {identity}")
            actual = private[table][identity]
            require(
                {key: expected[key] for key in shared_columns} == {key: actual[key] for key in shared_columns},
                f"SOURCE_ROW_CHANGED: {table} {identity}",
            )
        counts[table] = len(source[table])
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    args = parser.parse_args()
    context = json.loads((args.evidence_dir / "execution-context.json").read_text(encoding="utf-8"))
    live = json.loads((args.evidence_dir / "f07-live.json").read_text(encoding="utf-8"))
    output = args.evidence_dir / "f07-live-verification.json"
    if output.exists():
        parser.error("Preserve prior verification output")
    private_db = Path(context["database"])
    storage_root = Path(context["storageRoot"]).resolve()
    require(args.source_db.resolve() == Path(context["sourceDatabase"]).resolve(), "SOURCE_DATABASE_PATH_CHANGED")
    require(file_hashes(args.source_db) == context["sourceDatabaseHashes"], "SOURCE_DATABASE_BYTES_CHANGED")
    require(live.get("passed") is True, "UI_PRODUCT_CHAIN_NOT_PASSED")
    require(live.get("upstreamProvider") == "test (Binding/Appearance fixture only)", "FIXTURE_BOUNDARY_MISSING")
    require(live.get("realDirector") is True, "REAL_DIRECTOR_MARKER_MISSING")

    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["NOVELFLOW_STORAGE_ROOT"] = str(storage_root)
    backend = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(backend), str(backend / "tests")]
    import app.models  # noqa: F401
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from app.models.chapter_shot_split import ChapterShotSplitRun, ShotSource
    from app.models.llm_log import LLMLog
    from app.models.novel import Chapter
    from app.models.resolved_shot_assets import ResolvedImageVersion
    from app.models.shot import Shot
    from app.models.shot_revision import ShotRevision
    from app.models.system_config import SystemConfig
    from app.models.task import Task
    from app.schemas.chapter_shot_split import parse_output
    from app.services.chapter_asset_parse_service import digest
    from app.services.chapter_governance import require_rsa
    from app.services.chapter_shot_split_service import checked_source, source_payload
    from app.utils.path_utils import url_to_local_path

    engine = create_engine(f"sqlite:///file:{private_db}?mode=ro&uri=true")

    @event.listens_for(engine, "connect")
    def readonly(connection, _):
        connection.execute("PRAGMA query_only=ON")

    @event.listens_for(engine, "before_cursor_execute")
    def reads_only(connection, cursor, statement, *rest):
        verb = statement.lstrip().split()[0].upper()
        require(verb in {"SELECT", "PRAGMA"}, f"VERIFIER_WRITE_ATTEMPT: {verb}")

    verification = {
        "scope": "R2-B/F07 read-only product-chain verification",
        "privateDatabase": str(private_db),
        "privateDatabaseSha256": file_sha(private_db),
        "sourceDatabase": str(args.source_db.resolve()),
        "sourceDatabaseHashes": file_hashes(args.source_db),
    }
    with Session(engine, autoflush=False) as db:
        config = db.get(SystemConfig, "default")
        require(config is not None and config.llm_provider == "deepseek", "DEEPSEEK_CONFIG_REQUIRED")
        require(config.llm_api_key, "DEEPSEEK_KEY_MISSING")
        chapter = db.get(Chapter, context["f07"]["chapterId"])
        require(chapter is not None and chapter.content == SOURCE_TEXT and len(chapter.content) == 9, "F07_SOURCE_CHANGED")
        run = db.get(ChapterShotSplitRun, live["successfulRunId"])
        require(run is not None and run.status == "SUCCEEDED", "F07_RUN_NOT_SUCCEEDED")
        require(run.version == RUN_VERSION, "F07_RUN_VERSION_CHANGED")
        require(run.inputs.get("source_contract_version") == OWNERSHIP, "F07_INPUT_VERSION_CHANGED")
        require(digest(run.inputs) == run.input_hash and digest(run.result) == run.result_hash, "F07_RUN_HASH_CHANGED")
        source_ids = set(run.result.get("sources", {}))
        db_shot_ids = {row.id for row in db.query(Shot).filter_by(chapter_id=chapter.id)}
        require(source_ids == db_shot_ids == set(live["shotIds"]) and len(source_ids) == 1, "F07_SHOT_MEMBERSHIP_CHANGED")

        log = db.get(LLMLog, run.call.get("llm_log_id"))
        require(log is not None and log.status == "success", "F07_LLM_LOG_NOT_SUCCESS")
        require(log.provider == "deepseek" and log.model == config.llm_model, "F07_LLM_IDENTITY_CHANGED")
        request_info = json.loads(log.request_info or "{}")
        endpoint = urlsplit(request_info.get("url", ""))
        require(endpoint.scheme == "https" and endpoint.hostname == "api.deepseek.com", "F07_LLM_ENDPOINT_INVALID")
        require(endpoint.username is None and endpoint.password is None, "F07_LLM_ENDPOINT_CREDENTIALS_EXPOSED")
        require(request_info.get("provider") == "deepseek" and request_info.get("model") == log.model, "F07_REQUEST_INFO_CHANGED")
        require(request_info.get("headers", {}).get("Authorization") == "Bearer ***", "F07_REQUEST_HEADERS_NOT_REDACTED")
        payload = request_info.get("payload", {})
        require(payload.get("model") == log.model and payload.get("response_format") == {"type": "json_object"}, "F07_NATIVE_REQUEST_CHANGED")
        require(payload.get("messages") == [
            {"role": "system", "content": log.system_prompt},
            {"role": "user", "content": log.user_prompt},
        ], "F07_NATIVE_MESSAGES_CHANGED")
        require(log.system_prompt == run.inputs["system_prompt"] and log.user_prompt == run.inputs["user_prompt"], "F07_PROMPT_LOG_CHANGED")
        raw = parse_output(log.response, OWNERSHIP)
        require(raw["source_contract_version"] == OWNERSHIP, "F07_RAW_VERSION_CHANGED")
        require(len(raw["shots"]) == 1, "F07_RAW_SHOT_COUNT_CHANGED")
        planned = raw["shots"][0]
        require([item["text"] for item in planned["source_citations"]] == ["🐺刘备", "站定。"], "F07_RAW_CITATIONS_NOT_SPARSE")
        require(planned["source_ownership"]["text"] == SOURCE_TEXT, "F07_RAW_OWNERSHIP_NOT_CONTINUOUS")

        shot_id = next(iter(source_ids))
        shot = db.get(Shot, shot_id)
        base = db.get(ShotSource, shot_id)
        require(base is not None and digest(source_payload(base)) == base.seal, "F07_BASE_SOURCE_SEAL_CHANGED")
        expected_contract = {
            "version": OWNERSHIP,
            "citation_evidence": [{"text": "🐺刘备"}, {"text": "站定。"}],
            "citation_ranges": [
                {"start": 0, "end": 3, "text": "🐺刘备"},
                {"start": 6, "end": 9, "text": "站定。"},
            ],
            "ownership_evidence": {"text": SOURCE_TEXT},
            "ownership_range": {"start": 0, "end": 9, "text": SOURCE_TEXT},
        }
        require(base.source_contract == expected_contract, "F07_CANONICAL_SOURCE_CONTRACT_CHANGED")
        require((base.source_start, base.source_end, base.evidence, base.ranges) == (
            0, 9, [{"text": SOURCE_TEXT}], [{"start": 0, "end": 9, "text": SOURCE_TEXT}],
        ), "F07_CANONICAL_OWNERSHIP_CHANGED")
        middle = [
            treatment for treatment in base.treatment_contract["resolved_treatments"]
            if treatment["type"] == "VISUAL" and treatment["ranges"] == [{"start": 3, "end": 6, "text": "在桃园"}]
        ]
        require(len(middle) == 1, "F07_MIDDLE_TREATMENT_MISSING")

        current = checked_source(db, shot)
        require(current.revision == 2 and current.source_contract == expected_contract, "F07_EFFECTIVE_REVISION_INVALID")
        revisions = db.query(ShotRevision).filter_by(shot_id=shot_id).order_by(ShotRevision.revision).all()
        require([row.id for row in revisions] == live["revisionIds"] and [row.revision for row in revisions] == [1, 2], "F07_REVISION_CHAIN_CHANGED")
        require(all(row.origin == "USER_API" and digest(row.payload) == row.seal for row in revisions), "F07_REVISION_PROOF_CHANGED")
        require(all(row.payload["source"]["source_contract"] == expected_contract for row in revisions), "F07_REVISION_CHANGED_SOURCE")
        require("SHOT_REVISION_CONFLICT" in json.dumps(live["staleCas"], ensure_ascii=False), "F07_STALE_CAS_CONTROL_MISSING")

        rsa = require_rsa(db, shot_id)
        require(rsa.id == live["rsa"]["id"] and rsa.result_hash == live["rsa"]["resultHash"], "F07_RSA_IDENTITY_CHANGED")
        require(rsa.status == "READY" and rsa.inputs["logical"]["source"]["seal"] == current.visual_seal, "F07_RSA_SOURCE_NOT_CURRENT")
        references = rsa.data.get("references", {})
        require(len(references) == 2, "F07_RSA_REFERENCE_COUNT_CHANGED")
        frozen = []
        for slot, reference in sorted(references.items()):
            row = db.get(ResolvedImageVersion, reference["image_revision_id"])
            path = Path(url_to_local_path(reference["url"]))
            require(row is not None and path.is_file() and path.resolve().is_relative_to(storage_root), "F07_RSA_FILE_OUTSIDE_PRIVATE_ROOT")
            require(file_sha(path) == reference["sha256"], "F07_RSA_FILE_HASH_CHANGED")
            frozen.append({"slot": slot, "imageRevisionId": row.id, "url": reference["url"], "sha256": reference["sha256"]})
        for item in context["f07"]["rsaImageInputs"]:
            path = Path(url_to_local_path(item["url"]))
            require(path.is_file() and path.resolve().is_relative_to(storage_root), "F07_INPUT_FILE_OUTSIDE_PRIVATE_ROOT")
            require(file_sha(path) == item["sha256"], "F07_INPUT_FILE_HASH_CHANGED")
        active = db.query(Task).filter(Task.status.in_(["pending", "queued", "running"])).count()
        require(active == 0, "F07_PRIVATE_TASKS_NOT_SETTLED")
        require(not db.new and not db.dirty and not db.deleted, "F07_VERIFIER_SESSION_DIRTY")
        verification.update({
            "passed": True,
            "provider": log.provider,
            "model": log.model,
            "endpoint": request_info["url"],
            "runId": run.id,
            "llmLogId": log.id,
            "shotId": shot_id,
            "baseSourceSeal": base.seal,
            "effectiveRevision": current.revision,
            "effectiveRevisionId": current.revision_id,
            "effectiveVisualSeal": current.visual_seal,
            "revisionIds": [row.id for row in revisions],
            "sourceContract": expected_contract,
            "middleTreatment": middle[0],
            "rsa": {"id": rsa.id, "resultHash": rsa.result_hash, "seal": rsa.seal, "references": frozen},
            "activeTaskCount": active,
        })
    verification["protectedSourceRows"] = verify_source_copy(args.source_db, private_db)
    require(file_hashes(args.source_db) == context["sourceDatabaseHashes"], "SOURCE_DATABASE_CHANGED_DURING_VERIFICATION")
    output.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "passed": True,
        "runId": verification["runId"],
        "revision": verification["effectiveRevision"],
        "rsaId": verification["rsa"]["id"],
        "protectedSourceRows": sum(verification["protectedSourceRows"].values()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
