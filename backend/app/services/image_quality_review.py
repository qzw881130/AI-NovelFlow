"""Multimodal review of completed image tasks, independent of generation state."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from urllib.parse import urlsplit

from app.services.llm.http_retry import single_attempt_llm_request

from app.models.image_quality_review import ImageQualityReview
from app.models.novel import Character, Scene, Prop
from app.models.novel import Novel
from app.models.llm_log import LLMLog
from app.models.shot import Shot
from app.models.task import Task
from app.services.llm_service import LLMService
from app.services.novel_prompt_templates import resolve_novel_prompt_template
from app.services.vision_inputs import vision_proxy
from app.utils.json_parser import safe_parse_llm_json


IMAGE_TYPES = {"character_portrait", "shot_image", "scene_image", "prop_image", "keyframe_image", "single_image_edit"}
DIMENSIONS = ("CHARACTER_IDENTITY", "CHARACTER_COUNT", "HUMAN_ANATOMY", "ACTION_ACCURACY", "PROP_ACCURACY", "SCENE_CONSISTENCY")
BLOCKING_DIMENSIONS = frozenset(("CHARACTER_IDENTITY", "CHARACTER_COUNT", "HUMAN_ANATOMY"))
STATUSES = {"PASS", "WARNING", "FAIL"}


def _character_portrait_layout(workflow_name: str | None) -> str:
    """Use the submitted workflow's explicit layout, not the character count in its prompt."""
    name = (workflow_name or "").lower()
    if any(label in name for label in ("四视图", "4视图", "four-view", "four view", "turnaround")):
        return "four_view"
    if any(label in name for label in ("主视图", "单图", "单一形象", "single-view", "single view")):
        return "single_view"
    return "unspecified"


def _json(value, default):
    if not value:
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return default


def build_review_input(task: Task, structured_target: dict | None = None, *, generation_review: bool = False) -> dict:
    in_generation = generation_review and task.type == "shot_image" and task.status == "running"
    if task.type not in IMAGE_TYPES or (task.status != "completed" and not in_generation) or not task.result_url or not task.prompt_text:
        raise ValueError("评审需要已完成生图任务、真实生成图和原始提示词")
    metadata = _json(task.metadata_json, {})
    metadata = metadata if isinstance(metadata, dict) else {}
    manifest = metadata.get("reference_manifest") or []
    manifest = manifest if isinstance(manifest, list) else []
    reference_images = _json(task.reference_images, [])
    reference_images = reference_images if isinstance(reference_images, list) else []
    bindings = metadata.get("submitted_reference_bindings") or []
    bindings = bindings if isinstance(bindings, list) else []
    references = []
    if manifest:
        for item in manifest:
            if not isinstance(item, dict):
                raise ValueError("参考图 Manifest 格式无效")
            if not item.get("url") and not item.get("path"):
                raise ValueError("参考图 Manifest 存在缺失文件的项目")
            picture = item.get("picture") or item.get("picture_index")
            binding = next((b for b in bindings if b.get("picture") == picture), {})
            references.append({
                "picture": picture, "url": item.get("url") or item.get("path"),
                "kind": item.get("kind") or item.get("type"), "sources": item.get("sources") or binding.get("sources") or [],
                "purpose": item.get("purpose"), "name": item.get("name"), "members": item.get("members"),
                "binding": binding, "character_ids": item.get("character_ids"),
                "character_assets": item.get("character_assets"), "sha256": item.get("sha256"),
            })
    else:
        for index, item in enumerate(reference_images, 1):
            if isinstance(item, str):
                item = {"url": item}
            if not isinstance(item, dict):
                raise ValueError("参考图记录格式无效")
            picture = item.get("picture") or index
            binding = next((b for b in bindings if b.get("picture") == picture), {})
            references.append({
                "picture": picture, "url": item.get("url"), "kind": item.get("kind"),
                "sources": item.get("sources") or binding.get("sources") or [], "purpose": item.get("purpose"),
                "name": item.get("name") or item.get("label"), "members": item.get("members"),
                "binding": binding, "character_ids": item.get("character_ids"),
                "character_assets": item.get("character_assets"), "sha256": item.get("sha256"),
            })
    selector_input = metadata.get("reference_selector_input") or {}
    anchor = (selector_input.get("current_anchor") or {}) if isinstance(selector_input, dict) else {}
    target = {"current_anchor": anchor, "task_description": task.description,
              "structured_target": metadata.get("structured_target"),
              "related_records": structured_target or {},
              "authority_note": "关键帧以当前 current_anchor 和原始提示词为目标；Shot 的角色表仅是全镜头背景，不能据此判定当前帧人数。" if task.type == "keyframe_image" else "原始提示词及本任务结构化信息是目标。"}
    if task.type == "character_portrait":
        target["character_portrait_layout"] = {
            "mode": _character_portrait_layout(task.workflow_name),
            "workflow_name": task.workflow_name,
            "counting_rule": "角色形象图按不同角色身份计数。四视图中的正面、侧面、背面和头像特写是同一角色的重复展示，不是四个人；单一形象图按目标中的单幅人物构图评审。若工作流未明确版式，结合原始提示词判断，不得仅凭同一角色的多视角展示判定多出人物。",
        }
    return {
        "task_id": task.id, "task_type": task.type, "novel_id": task.novel_id,
        "chapter_id": task.chapter_id, "shot_id": task.shot_id,
        "original_prompt": task.prompt_text, "generated_image": task.result_url,
        "target": target,
        "references": references,
    }


def normalize_review_response(raw: str) -> dict:
    data = safe_parse_llm_json(raw, default=None)
    if not isinstance(data, dict):
        raise ValueError("评审模型未返回 JSON 对象")
    supplied = data.get("dimensions")
    if not isinstance(supplied, dict) or not isinstance(data.get("issues"), list):
        raise ValueError("评审结果缺少维度或问题列表")
    issues = []
    for item in data["issues"]:
        if not isinstance(item, dict) or item.get("type") not in DIMENSIONS:
            raise ValueError("评审问题类型无效")
        issue = {key: str(item.get(key) or "") for key in (
            "type", "severity", "expected", "observed", "location", "evidence", "suggestion", "visibility"
        )}
        if issue["severity"] not in {"WARNING", "FAIL"}:
            raise ValueError("评审问题严重程度无效")
        issue["original_severity"] = issue["severity"]
        if issue["visibility"] not in {"OBSERVED", "OCCLUDED", "UNCERTAIN"}:
            issue["visibility"] = "UNCERTAIN"
        dimension = supplied.get(issue["type"])
        if (issue["type"] not in BLOCKING_DIMENSIONS
                or not isinstance(dimension, dict) or dimension.get("status") != "FAIL"
                or issue["visibility"] != "OBSERVED"
                or issue["location"] in {"", "无法确认", "未知"}
                or not issue["observed"] or not issue["evidence"]):
            issue["severity"] = "WARNING"
        issues.append(issue)
    dimensions = {}
    for name in DIMENSIONS:
        value = supplied.get(name)
        if not isinstance(value, dict) or value.get("status") not in STATUSES:
            raise ValueError(f"评审维度 {name} 缺失或状态无效")
        related = [issue for issue in issues if issue["type"] == name]
        status = value["status"]
        if status == "FAIL" and not any(issue["severity"] == "FAIL" for issue in related):
            status = "WARNING"
        if status in {"PASS", "WARNING"} and related:
            # Conflicting model fields are inconclusive; an issue cannot promote
            # a non-FAIL dimension into a blocking finding.
            status = "WARNING"
        if status in {"WARNING", "FAIL"} and not related:
            issues.append({"type": name, "severity": "WARNING", "expected": "按原始提示词及参考图满足要求",
                           "observed": str(value.get("summary") or "证据不足"), "location": "无法确认",
                           "evidence": "模型未给出可定位的直接视觉证据", "suggestion": "人工复核或补充清晰参考图",
                           "visibility": "UNCERTAIN"})
            status = "WARNING"
        if name not in BLOCKING_DIMENSIONS and status == "FAIL":
            status = "WARNING"
        dimensions[name] = {"status": status, "original_status": value["status"],
                            "summary": str(value.get("summary") or "")}
    overall = ("FAIL" if any(dimensions[name]["status"] == "FAIL" for name in BLOCKING_DIMENSIONS)
               else "WARNING" if any(value["status"] == "WARNING" for value in dimensions.values())
               else "PASS")
    return {"overall": overall, "summary": str(data.get("summary") or ""),
            "dimensions": dimensions, "issues": issues}


def review_to_dict(review: ImageQualityReview) -> dict:
    return {"id": review.id, "taskId": review.task_id, "trigger": review.trigger,
            "status": review.status, "overall": review.overall, "summary": review.summary,
            "dimensions": _json(review.dimensions_json, {}), "issues": _json(review.issues_json, []),
            "input": _json(review.input_snapshot_json, {}), "rawResponse": review.raw_response,
            "templateId": review.template_id, "templateName": review.template_name,
            "templateVersion": review.template_version, "templateText": review.template_text,
            "llmLogId": review.llm_log_id, "provider": review.provider, "model": review.model,
            "error": review.error_message, "createdAt": review.created_at.isoformat() if review.created_at else None,
            "completedAt": review.completed_at.isoformat() if review.completed_at else None}


def create_image_review(db: Session, task_id: str, trigger: str = "manual") -> ImageQualityReview:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError("任务不存在")
    structured = {}
    if task.shot_id:
        shot = db.query(Shot).filter(Shot.id == task.shot_id).first()
        if shot:
            structured["shot"] = {"description": shot.description, "scene": shot.scene,
                                  "props": _json(shot.props, []),
                                  "characters": _json(shot.characters, []) if task.type == "shot_image" else None}
    for id_field, model, key, fields in (
        (task.character_id, Character, "character", ("name", "description", "appearance")),
        (task.scene_id, Scene, "scene", ("name", "description", "setting")),
        (task.prop_id, Prop, "prop", ("name", "description", "appearance")),
    ):
        if id_field:
            entity = db.query(model).filter(model.id == id_field).first()
            if entity:
                structured[key] = {field: getattr(entity, field) for field in fields}
    # Snapshot the result and active template before enqueueing; later task edits
    # and template changes must not change this attempt's input.
    review = ImageQualityReview(task_id=task_id, trigger=trigger,
                                created_at=datetime.now(timezone.utc),
                                input_snapshot_json=json.dumps({"generated_image": task.result_url}))
    try:
        snapshot = build_review_input(task, structured, generation_review=trigger == "generation")
        review.input_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        novel = db.get(Novel, task.novel_id) if task.novel_id else None
        template = resolve_novel_prompt_template(db, novel, "image_quality_review_prompt")
        if not template or not template.template.strip():
            raise ValueError("AI 图片质量评审系统提示词未登记")
        review.template_id, review.template_name = template.id, template.name
        review.template_version = hashlib.sha256(template.template.encode("utf-8")).hexdigest()
        review.template_text = template.template
    except Exception as exc:
        review.status, review.error_message = "error", str(exc)
        review.completed_at = datetime.now(timezone.utc)
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


async def execute_image_review(db: Session, review_id: str) -> ImageQualityReview:
    # An atomic claim protects against duplicate completion events/workers.
    claimed = db.query(ImageQualityReview).filter_by(id=review_id, status="pending").update(
        {"status": "running"}, synchronize_session=False)
    db.commit()
    review = db.get(ImageQualityReview, review_id)
    if not review:
        raise ValueError("评审记录不存在")
    db.refresh(review)
    if not claimed:
        return review
    snapshot = _json(review.input_snapshot_json, {})
    try:
        images = [await asyncio.to_thread(vision_proxy, snapshot["generated_image"],
                                          logical_id="GENERATED_OUTPUT", name="实际生成图", role="generated_output")]
        for ref in snapshot["references"]:
            images.append(await asyncio.to_thread(
                vision_proxy, ref["url"], logical_id=f"Picture{ref['picture']}",
                name=ref["name"] or f"参考图 {ref['picture']}", role="reference",
                reference_type=ref["kind"], sources=ref["sources"],
                members=ref["members"], purpose=ref["purpose"], binding=ref["binding"]))
            expected_hash = ref.get("sha256") or ref["binding"].get("sha256")
            if expected_hash and images[-1].get("source_sha256") != expected_hash:
                raise ValueError(f"Picture {ref['picture']} 文件已变化，无法按实际生成参考图评审")
        snapshot["submitted_images"] = [{
            "logical_id": item["logical_id"], "source_path": item.get("source_path"),
            "source_sha256": item.get("source_sha256"), "submitted_sha256": item.get("sha256"),
            "submitted_dimensions": item.get("submitted_dimensions"),
        } for item in images]
        review.input_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        db.commit()
        user_input = {"task_type": snapshot["task_type"],
                      "original_prompt": snapshot["original_prompt"], "target": snapshot["target"],
                      "images": [{"order": index + 1, "logical_id": item["logical_id"],
                                  "sources": item.get("sources"), "reference_type": item.get("reference_type"),
                                  "name": item.get("name"), "members": item.get("members"),
                                  "purpose": item.get("purpose"), "binding": item.get("binding")}
                                 for index, item in enumerate(images)]}
        llm = LLMService()
        review.provider, review.model = llm.provider, llm.model
        db.commit()
        with single_attempt_llm_request():
            response = await llm.chat_completion(
                system_prompt=review.template_text, user_content=json.dumps(user_input, ensure_ascii=False),
                response_format="json_object", task_type="image_quality_review_prompt",
                prompt_template_name=review.template_name, novel_id=snapshot.get("novel_id"),
                chapter_id=snapshot.get("chapter_id"), shot_id=snapshot.get("shot_id"), images=images)
        review.llm_log_id = response.get("log_id")
        review.raw_response = json.dumps(response.get("raw_response"), ensure_ascii=False, default=str) if response.get("raw_response") else response.get("content")
        if not response.get("success"):
            raise ValueError(response.get("error") or "评审模型调用失败")
        result = normalize_review_response(response.get("content") or "")
        review.overall, review.summary = result["overall"], result["summary"]
        review.dimensions_json = json.dumps(result["dimensions"], ensure_ascii=False)
        review.issues_json = json.dumps(result["issues"], ensure_ascii=False)
        review.status = "success"
    except Exception as exc:
        review.status = "error"
        review.error_message = str(exc)
    if review.llm_log_id:
        log = db.get(LLMLog, review.llm_log_id)
        if log:
            info = _json(log.request_info, {})
            info["imageQualityReview"] = {
                "reviewId": review.id, "taskId": review.task_id,
                "templateId": review.template_id, "templateVersion": review.template_version,
                "status": review.status, "overall": review.overall,
            }
            log.request_info = json.dumps(info, ensure_ascii=False, default=str)
    review.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    return review


async def review_image_task(db: Session, task_id: str, trigger: str = "manual") -> ImageQualityReview:
    task = db.get(Task, task_id)
    if task:
        current = current_image_reviews(db, [{"taskId": task.id, "imageUrl": task.result_url or ""}])[0]
        if current["qualityStatus"] == "PENDING":
            # A user can explicitly start a queued review even after turning
            # automatic review off; the same atomic claim prevents duplicates.
            return await execute_image_review(db, current["reviewId"])
        if current["qualityStatus"] == "RUNNING":
            return db.get(ImageQualityReview, current["reviewId"])
        if trigger == "generation" and current["reviewId"]:
            return db.get(ImageQualityReview, current["reviewId"])
    review = create_image_review(db, task_id, trigger)
    return await execute_image_review(db, review.id)


def image_result_key(url: str | None) -> str:
    parsed = urlsplit(url or "")
    # Local assets may be presented with an absolute API origin by the browser.
    return parsed.path if parsed.path.startswith("/api/files/") else (url or "")


def image_quality_state(review: ImageQualityReview | None) -> str:
    if not review:
        return "NOT_REVIEWED"
    if review.status == "success":
        return review.overall or "ERROR"
    return {"pending": "PENDING", "running": "RUNNING", "error": "ERROR"}.get(review.status, "ERROR")


def current_image_reviews(db: Session, images: list[dict]) -> list[dict]:
    """Project quality by task AND concrete result, never by visual-state index."""
    ids = {item["taskId"] for item in images if item.get("taskId")}
    reviews = db.query(ImageQualityReview).filter(ImageQualityReview.task_id.in_(ids)).order_by(
        ImageQualityReview.created_at.desc(), ImageQualityReview.id.desc()).all() if ids else []
    latest = {}
    for review in reviews:
        key = (review.task_id, image_result_key(_json(review.input_snapshot_json, {}).get("generated_image")))
        latest.setdefault(key, review)
    result = []
    for item in images:
        review = latest.get((item.get("taskId"), image_result_key(item["imageUrl"])))
        result.append({**item, "qualityStatus": image_quality_state(review),
                       "reviewId": review.id if review else None,
                       "summary": (review.summary or review.error_message) if review else None})
    return result
