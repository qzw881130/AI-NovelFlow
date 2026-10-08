"""Inspector-owned sidecars. No business writes, queues, or generation imports."""
import hashlib
import json
import math
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


MEDIA_ROOT = Path(__file__).resolve().parents[2] / "user_story"
CATEGORIES = (
    "PORTRAIT_DRIFT", "WRONG_SPEECH_BODY", "WRONG_MOUTH_ARTICULATION",
    "IDENTITY_DRIFT", "BODY_DUPLICATION", "SCENE_CONTINUITY_BREAK",
    "PROP_MISMATCH", "CAMERA_MISMATCH", "OTHER",
)
_WRITE_LOCK = threading.RLock()


class InspectorError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    if isinstance(value, str):
        return hashlib.sha256(value.encode()).hexdigest()
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise InspectorError("SIDECAR_UNAVAILABLE", "分析文件不可读取", 503) from exc


def safe_token(value, pattern=r"[A-Za-z0-9_-]{1,128}"):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise InspectorError("INVALID_IDENTITY", "分析身份无效")
    return value


class InspectorStore:
    def __init__(self, media_root=MEDIA_ROOT):
        self.media_root = Path(media_root).resolve()

    def story_root(self, novel_id):
        token = safe_token(novel_id)[:8]
        return self.controlled(self.media_root / f"story_{token}" / "inspector")

    def controlled(self, path):
        path = path.resolve()
        if not path.is_relative_to(self.media_root):
            raise InspectorError("UNSAFE_PATH", "文件不在受控媒体目录内", 403)
        return path

    def analysis_dir(self, analysis_id):
        safe_token(analysis_id, r"[0-9a-f-]{36}")
        matches = list(self.media_root.glob(f"story_*/inspector/analyses/{analysis_id}/manifest.json"))
        if len(matches) != 1:
            raise InspectorError("ANALYSIS_NOT_FOUND", "未找到保存的分析", 404)
        return self.controlled(matches[0].parent)

    def create(self, projection, evidence, label="A"):
        if projection["artifact"]["identity_status"] != "STABLE":
            raise InspectorError("IDENTITY_PENDING", "媒体身份尚未核验，暂不能创建耐久分析", 409)
        analysis_id = str(uuid.uuid4())
        directory = self.story_root(projection["clip_ref"]["novel_id"]) / "analyses" / analysis_id
        now = utc_now()
        manifest = {"analysis_id": analysis_id, "schema_version": 1, "revision": 1,
                    "created_at": now, "updated_at": now, "clip_ref": projection["clip_ref"],
                    "projection_version": 1, "source_quality": projection["availability"],
                    "variants": [{"variant_id": "A", "label": label, "role": "CANONICAL",
                                  "artifact_id": projection["artifact"]["artifact_id"],
                                  "projection": projection, "source_snapshot": evidence}],
                    "comparison_markers": []}
        with _WRITE_LOCK:
            # Both initial files precede publication of the manifest.
            atomic_json(directory / "observations.json", {"revision": 1, "observations": []})
            atomic_json(directory / "manifest.json", manifest)
        return self.read(analysis_id)

    def read(self, analysis_id):
        directory = self.analysis_dir(analysis_id)
        with _WRITE_LOCK:
            manifest = read_json(directory / "manifest.json")
            notes = read_json(directory / "observations.json")
        # The notes file is the single atomic revision authority for CRUD.
        return {**manifest, "revision": notes["revision"], "updated_at": notes.get("updated_at", manifest["updated_at"]),
                "observations": notes["observations"]}

    def list_analyses(self, shot_id, clip_index, revision=None):
        results = []
        for file in self.media_root.glob("story_*/inspector/analyses/*/manifest.json"):
            try:
                data = read_json(self.controlled(file))
                ref = data["clip_ref"]
                if ref["shot_id"] == shot_id and ref["clip_index"] == clip_index and (
                        revision is None or ref["clip_plan_revision"] == revision):
                    results.append({"analysis_id": data["analysis_id"], "created_at": data["created_at"],
                                    "variants": [{**{k: v[k] for k in ("variant_id", "label", "artifact_id")},
                                                  "task_id": v["projection"]["execution"]["task_id"]}
                                                 for v in data["variants"]]})
            except (InspectorError, KeyError):
                continue
        return sorted(results, key=lambda a: a["created_at"], reverse=True)

    def mutate_observation(self, analysis_id, payload=None, observation_id=None, revision=None, delete=False):
        with _WRITE_LOCK:
            analysis = self.read(analysis_id)
            if revision is None or revision != analysis["revision"]:
                raise InspectorError("REVISION_CONFLICT", "分析已被其他窗口更新，请重新载入后保存", 409)
            notes = analysis["observations"]
            old = next((n for n in notes if n["observation_id"] == observation_id), None)
            if observation_id and old is None:
                raise InspectorError("OBSERVATION_NOT_FOUND", "未找到人工标记", 404)
            if delete:
                notes = [n for n in notes if n["observation_id"] != observation_id]
            else:
                value = {**(old or {}), **(payload or {})}
                variant = next((v for v in analysis["variants"] if v["variant_id"] == value.get("variant_id", "A")), None)
                if variant is None:
                    raise InspectorError("VARIANT_NOT_FOUND", "分析版本不存在", 404)
                projection = variant["projection"]
                t, end = value.get("time_seconds"), value.get("end_time_seconds")
                maximum = projection["time_mapping"].get("axis_duration")
                if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
                    raise InspectorError("INVALID_TIME", "标记时间必须是有效非负秒数")
                if end is not None and (isinstance(end, bool) or not isinstance(end, (int, float)) or
                                        not math.isfinite(end) or end < t):
                    raise InspectorError("INVALID_TIME", "结束时间必须不早于开始时间")
                if maximum is not None and (t > maximum or (end is not None and end > maximum)):
                    raise InspectorError("INVALID_TIME", "标记时间超出分析时间轴")
                categories = value.get("categories", [])
                aliases = {"PORTRAIT_CLOSEUP": "PORTRAIT_DRIFT", "WRONG_VISIBLE_SPEAKER": "WRONG_SPEECH_BODY"}
                if not isinstance(categories, list) or not categories or len(categories) > len(CATEGORIES):
                    raise InspectorError("INVALID_CATEGORY", "请选择观察标签")
                categories = list(dict.fromkeys(aliases.get(c, c) for c in categories if isinstance(c, str)))
                if not categories or any(c not in CATEGORIES for c in categories):
                    raise InspectorError("INVALID_CATEGORY", "观察标签无效")
                note = value.get("note", "")
                if not isinstance(note, str) or len(note) > 10000:
                    raise InspectorError("INVALID_NOTE", "备注过长或无效")
                # Never trust client-supplied frame evidence. Resolve against the frozen variant.
                from app.services.inspector_frame_service import resolve_sample
                frame = resolve_sample(projection["media"], projection["time_mapping"], t)
                evidence = {k: frame.get(k) for k in ("local_frame_index0", "native_frame_index0", "native_pts", "sample_clip_time")}
                evidence.update(video_sha256=projection["artifact"].get("video_sha256"), mapping_version=1)
                now = utc_now()
                record = {"observation_id": observation_id or str(uuid.uuid4()), "analysis_id": analysis_id,
                          "variant_id": variant["variant_id"], "artifact_id": variant["artifact_id"],
                          "time_domain": projection["time_mapping"]["time_domain"], "time_seconds": t,
                          "end_time_seconds": end, "frame_evidence": evidence, "categories": categories,
                          "note": note, "origin": "HUMAN", "comparison_marker_id": None,
                          "created_at": old["created_at"] if old else now, "updated_at": now}
                notes = [record if n["observation_id"] == observation_id else n for n in notes] if old else notes + [record]
            atomic_json(self.analysis_dir(analysis_id) / "observations.json",
                        {"revision": revision + 1, "updated_at": utc_now(), "observations": notes})
            return self.read(analysis_id)
