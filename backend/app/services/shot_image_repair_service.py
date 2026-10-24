"""Durable, review-gated repair of a failed main storyboard image."""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import update

from app.core.database import SessionLocal
from app.models.image_quality_review import ImageQualityReview
from app.models.novel import Chapter, Character, Novel, Prop, Scene
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.background_workers import persistent_job, worker_manager
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.image_quality_review import image_result_key, review_image_task
from app.services.llm_service import LLMService
from app.services.required_visual_state_images import commit_visual_state_image, state_provenance
from app.services.vision_inputs import vision_proxy
from app.utils.json_parser import safe_parse_llm_json
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.workflow_seed import synchronize_prompt_rewrite_seeds


MAX_ROUNDS = 2
REPAIR_TASK_TYPE = "shot_image_repair"
REPAIR_CANDIDATE_TYPE = "shot_image_repair_candidate"
REPAIR_WORKFLOW_NAME = "Qwen image 2.1图片编辑 (任意数量参考图) API V20260926.json"
REPAIR_HANDLER = "app.services.shot_image_repair_service:run_shot_image_repair"


def _json(value, default):
    try:
        parsed = json.loads(value or "null") if isinstance(value, str) else value
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


def _metadata(task: Task) -> dict:
    return _json(task.metadata_json, {})


def _save(db, task: Task, metadata: dict, step: str, progress: int | None = None):
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    task.current_step = step
    if progress is not None:
        task.progress = progress
    db.commit()


def _review_for_image(db, task_id: str, image_url: str) -> ImageQualityReview | None:
    reviews = db.query(ImageQualityReview).filter_by(task_id=task_id, status="success").order_by(
        ImageQualityReview.created_at.desc(), ImageQualityReview.id.desc()).all()
    return next((review for review in reviews if image_result_key(
        _json(review.input_snapshot_json, {}).get("generated_image")) == image_result_key(image_url)), None)


def enqueue_shot_image_repair(db, novel_id: str, chapter_id: str, shot_id: str) -> Task:
    shot = db.get(Shot, shot_id)
    chapter = db.get(Chapter, chapter_id)
    if not shot or not chapter or chapter.novel_id != novel_id or shot.chapter_id != chapter_id:
        raise ValueError("分镜不存在")
    source = db.get(Task, shot.image_task_id) if shot.image_task_id else None
    if not source or source.type not in {"shot_image", REPAIR_CANDIDATE_TYPE} or shot.image_status != "completed" or not shot.image_url:
        raise ValueError("当前分镜没有可修复的主分镜图")
    review = _review_for_image(db, source.id, shot.image_url)
    if not review or review.overall != "FAIL":
        raise ValueError("只有当前 AI 评审为 FAIL 的主分镜图可加入修复队列")
    if not source.prompt_text:
        raise ValueError("原始分镜生图提示词不存在")
    active = db.query(Task).filter(Task.shot_id == shot_id, Task.type == REPAIR_TASK_TYPE,
                                   Task.status.in_(["pending", "running"])).order_by(Task.created_at.desc()).first()
    if active:
        return active
    generating = db.query(Task).filter(Task.shot_id == shot_id, Task.type == "shot_image",
                                       Task.status.in_(["pending", "running"])).first()
    if generating:
        raise ValueError("当前分镜正在重新生成，请稍后再加入修复队列")
    task = Task(type=REPAIR_TASK_TYPE, status="pending", novel_id=novel_id, chapter_id=chapter_id,
                shot_id=shot_id, source_task_id=source.id,
                name=f"修复主分镜图: 章回{chapter.number} · Shot{shot.index}",
                description="局部多图编辑、AI 评审，最多两轮；审核非 FAIL 后替换主分镜图",
                progress=0, current_step="等待修复 worker",
                metadata_json=json.dumps({"source_url": shot.image_url, "source_review_id": review.id,
                                          "source_provenance": state_provenance(shot, 1), "rounds": [],
                                          "max_rounds": MAX_ROUNDS}, ensure_ascii=False))
    db.add(task)
    db.commit()
    db.refresh(task)
    try:
        worker_manager.worker("shot_image_repair").enqueue(persistent_job(
            task.id, REPAIR_HANDLER, {"task_id": task.id}, lambda: run_shot_image_repair(task.id)), db=db)
    except Exception as exc:
        db.rollback()
        task.status = "failed"
        task.error_message = f"加入后台队列失败: {exc}"
        task.current_step = "修复任务未启动"
        task.completed_at = datetime.utcnow()
        db.commit()
        raise
    return task


def _choose_source(db, source_task: Task, canonical_url: str, canonical_review_id: str) -> tuple[str, str]:
    """Prefer an earlier attempt with the correct character count and fewer blocking defects."""
    candidates = [(canonical_url, canonical_review_id)]
    for attempt in (_metadata(source_task).get("shot_image_quality") or {}).get("attempts") or []:
        if isinstance(attempt, dict) and attempt.get("image_url") and attempt.get("review_id"):
            candidates.append((attempt["image_url"], attempt["review_id"]))
    ranked = []
    for index, (url, review_id) in enumerate(candidates):
        review = db.get(ImageQualityReview, review_id)
        if not review or review.status != "success" or review.overall != "FAIL" or not url_to_local_path(url):
            continue
        dimensions = _json(review.dimensions_json, {})
        issues = _json(review.issues_json, [])
        count_fail = dimensions.get("CHARACTER_COUNT", {}).get("status") == "FAIL"
        blocking = sum(item.get("severity") == "FAIL" for item in issues if isinstance(item, dict))
        # With equally severe findings, the earliest generation is a better
        # alternative to the currently published (usually last) failed image.
        ranked.append(((int(count_fail), blocking, index or len(candidates)), url, review_id))
    if not ranked:
        raise ValueError("找不到仍存在的失败图及其有效评审记录")
    _, url, review_id = min(ranked)
    return url, review_id


def _catalog(db, novel_id: str, shot: Shot) -> list[dict]:
    rows = []
    for name in _json(shot.characters, []):
        item = db.query(Character).filter_by(novel_id=novel_id, name=name).first()
        if item and item.image_url and url_to_local_path(item.image_url):
            rows.append({"kind": "character", "name": name, "url": item.image_url,
                         "appearance": (item.appearance or "")[:700]})
    if shot.scene:
        item = db.query(Scene).filter_by(novel_id=novel_id, name=shot.scene).first()
        if item and item.image_url and url_to_local_path(item.image_url):
            rows.append({"kind": "scene", "name": shot.scene, "url": item.image_url})
    for name in _json(shot.props, []):
        item = db.query(Prop).filter_by(novel_id=novel_id, name=name).first()
        if item and item.image_url and url_to_local_path(item.image_url):
            rows.append({"kind": "prop", "name": name, "url": item.image_url})
    return rows


async def _plan_repair(db, task: Task, source_url: str, review: ImageQualityReview,
                       catalog: list[dict], original_prompt: str) -> dict:
    issues = [item for item in _json(review.issues_json, []) if isinstance(item, dict) and item.get("severity") == "FAIL"]
    if not issues:
        raise ValueError("AI 评审没有可定位的阻断问题；请人工处理")
    image = await asyncio.to_thread(vision_proxy, source_url, logical_id="FAILED_IMAGE", name="待修复分镜图")
    references = catalog[:8]
    images = [image] + [await asyncio.to_thread(vision_proxy, ref["url"],
              logical_id=f"REFERENCE_{i}", name=f'{ref["kind"]}:{ref["name"]}')
              for i, ref in enumerate(references, 1)]
    system = (
        "你是分镜图局部修复规划器。只选择一个可见且可定位的 FAIL 问题，不重新生成整幅图。"
        "输出 JSON：target_kind(character 或 scene)、target_name(必须与参考图目录完全相同)、"
        "bbox([x1,y1,x2,y2]，各值为原图宽高的千分比，框住需要修复的单个人物及少量边缘，不能覆盖其他人物)、"
        "repair_prompt(中文，明确指向<image_1>为目标角色或无人场景参考，保持框外画面及总人数)。"
        "人物身份/服装错误选对应角色参考；多出的人物选场景参考，只删除多余人物；"
        "缺少人物仅在能找到安全空白区域时才规划。没有可定位修复区域时返回 error。"
        "只根据图像中的实际像素定位，不能猜测位置或发明参考图。"
    )
    user = {"original_prompt": original_prompt, "blocking_issues": issues,
            "references": [{"kind": r["kind"], "name": r["name"], "appearance": r.get("appearance")}
                           for r in references],
            "image_order": ["FAILED_IMAGE"] + [f'{r["kind"]}:{r["name"]}' for r in references]}
    result = await LLMService().chat_completion(
        system_prompt=system, user_content=json.dumps(user, ensure_ascii=False),
        response_format="json_object", temperature=0.1, max_tokens=1200,
        task_type="shot_image_repair_plan", novel_id=task.novel_id,
        chapter_id=task.chapter_id, shot_id=task.shot_id, images=images)
    if not result.get("success"):
        raise ValueError(result.get("error") or "修复区域定位失败")
    plan = safe_parse_llm_json(result.get("content") or "", default=None)
    if not isinstance(plan, dict) or plan.get("error"):
        raise ValueError(str((plan or {}).get("error") or "修复区域无法定位"))
    target = next((r for r in references if r["kind"] == plan.get("target_kind")
                   and r["name"] == plan.get("target_name")), None)
    box = plan.get("bbox")
    if not target or not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) for v in box):
        raise ValueError("修复计划的目标参考图或遮罩范围无效")
    x1, y1, x2, y2 = [float(v) for v in box]
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000 and (x2-x1)*(y2-y1) <= 400000):
        raise ValueError("修复遮罩超出画面或覆盖范围过大")
    prompt = str(plan.get("repair_prompt") or "").strip()
    if not prompt or len(prompt) > 2000:
        raise ValueError("局部修复提示词无效")
    return {"target": target, "bbox": box, "prompt": prompt, "llm_log_id": result.get("log_id")}


def _make_mask(source_url: str, box: list, task_id: str, round_number: int) -> str:
    path = url_to_local_path(source_url)
    if not path:
        raise ValueError("待修复原图文件已不存在")
    with Image.open(path) as source:
        width, height = source.size
    points = [round(box[0]*width/1000), round(box[1]*height/1000),
              round(box[2]*width/1000), round(box[3]*height/1000)]
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(points, radius=14, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(8))
    mask_path = Path(file_storage.base_dir) / "shot_repair_masks" / f"{task_id}_round{round_number}.png"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(mask_path)
    return str(mask_path)


def build_masked_repair_graph(service: ComfyUIService, workflow: Workflow, prompt: str,
                              aspect_ratio: str, seed: int, uploads: list[str],
                              denoise: float = 0.78) -> tuple[dict, str]:
    """The same Qwen inpaint node path validated by the four-shot experiment."""
    mapping = _json(workflow.node_mapping, {})
    reference_count = len(uploads) - 2
    required = {"load_image_node_1", "save_image_node_id"} | {
        f"load_image_node_{i}" for i in range(2, reference_count + 2)}
    if not 1 <= reference_count <= 8 or not required.issubset(mapping):
        raise ValueError("多图编辑工作流缺少必要图片节点映射")
    graph = service.builder.build_shot_workflow(prompt=prompt, workflow_json=workflow.workflow_json,
                  node_mapping=mapping, aspect_ratio=aspect_ratio, seed=seed, style="")
    for node_id, class_type in {"485": "TextEncodeQwenImage21", "484": "QwenImage21Cache",
                                "479": "VAELoader", "481": "VAEDecode", "515": "SaveImage"}.items():
        if graph.get(node_id, {}).get("class_type") != class_type:
            raise ValueError(f"多图编辑工作流节点 {node_id} 已变化，需重新验证遮罩映射")
    unused = {str(mapping[f"load_image_node_{i}"]) for i in range(reference_count + 2, 10)
              if mapping.get(f"load_image_node_{i}")}
    for node in graph.values():
        for key, value in list(node.get("inputs", {}).items()):
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in unused:
                del node["inputs"][key]
    for node_id in unused:
        graph.pop(node_id, None)
    base_id = str(mapping["load_image_node_1"])
    graph[base_id]["inputs"]["image"] = uploads[0]
    encoded = graph["485"]["inputs"]
    for key in list(encoded):
        if key.startswith("images.image_"):
            del encoded[key]
    for index in range(1, reference_count + 1):
        reference_id = str(mapping[f"load_image_node_{index + 1}"])
        graph[reference_id]["inputs"]["image"] = uploads[index]
        encoded[f"images.image_{index}"] = [reference_id, 0]
    graph["800"] = {"class_type": "LoadImageMask", "inputs": {"image": uploads[-1], "channel": "red"}}
    graph["801"] = {"class_type": "InpaintModelConditioning", "inputs": {
        "positive": ["485", 0], "negative": ["485", 1], "vae": ["479", 0],
        "pixels": [base_id, 0], "mask": ["800", 0], "noise_mask": True}}
    graph["802"] = {"class_type": "KSampler", "inputs": {
        "model": ["484", 0], "positive": ["801", 0], "negative": ["801", 1],
        "latent_image": ["801", 2], "denoise": denoise, "steps": 50, "cfg": 1,
        "sampler_name": "euler", "scheduler": "simple", "seed": seed}}
    graph["481"]["inputs"]["samples"] = ["802", 0]
    graph["515"]["inputs"]["images"] = ["481", 0]
    for node_id in ("482", "483", "480", "494"):
        graph.pop(node_id, None)
    synchronize_prompt_rewrite_seeds(graph)
    return graph, str(mapping["save_image_node_id"])


async def _run_round(db, task: Task, metadata: dict, source_url: str, review_id: str,
                     catalog: list[dict], source_task: Task, novel: Novel, round_number: int) -> tuple[str, ImageQualityReview]:
    rounds = metadata.setdefault("rounds", [])
    while len(rounds) < round_number:
        rounds.append({"number": len(rounds) + 1})
    entry = rounds[round_number - 1]
    if not entry.get("plan"):
        review = db.get(ImageQualityReview, review_id)
        if not review or review.status != "success" or review.overall != "FAIL":
            raise ValueError("修复源图的 AI 评审记录无效")
        _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：分析失败区域", 5 + 30 * (round_number - 1))
        entry["source_url"], entry["source_review_id"] = source_url, review_id
        entry["plan"] = await _plan_repair(db, task, source_url, review, catalog, source_task.prompt_text)
        if round_number > 1:
            for previous in rounds[:round_number - 1]:
                old = previous.get("plan") or {}
                if old.get("target", {}).get("name") == entry["plan"]["target"]["name"]:
                    a, b = old["bbox"], entry["plan"]["bbox"]
                    entry["plan"]["bbox"] = [max(0, min(a[0], b[0]) - 20),
                        max(0, min(a[1], b[1]) - 20), min(1000, max(a[2], b[2]) + 20),
                        min(1000, max(a[3], b[3]) + 20)]
                    expanded = entry["plan"]["bbox"]
                    if (expanded[2] - expanded[0]) * (expanded[3] - expanded[1]) > 400000:
                        raise ValueError("连续两轮对同一角色的定位差异过大，停止自动修复")
                    break
        entry["mask_path"] = _make_mask(source_url, entry["plan"]["bbox"], task.id, round_number)
        _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：已定位局部遮罩")
    plan = entry["plan"]
    workflow = db.query(Workflow).filter_by(name=REPAIR_WORKFLOW_NAME, type="multi_image_edit", is_active=True).first()
    if not workflow:
        raise ValueError("经过验证的多图编辑工作流未启用")
    service = ComfyUIService(db=db)
    if entry.get("graph") and not task.workflow_json:
        task.workflow_json = json.dumps(entry["graph"], ensure_ascii=False)
        db.commit()
    if not entry.get("result_url"):
        if not entry.get("prompt_id"):
            _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：上传原图、角色/场景参考和遮罩")
            source_review = db.get(ImageQualityReview, review_id)
            issue_text = json.dumps(_json(source_review.issues_json, []), ensure_ascii=False) if source_review else ""
            other_refs = [ref for ref in catalog if ref["url"] != plan["target"]["url"]]
            related_characters = [ref for ref in other_refs if ref["kind"] == "character" and ref["name"] in issue_text]
            environment_refs = [ref for ref in other_refs if ref["kind"] in {"scene", "prop"}]
            ordered_refs = ([plan["target"]] + related_characters + environment_refs)[:8]
            entry["submitted_references"] = ordered_refs
            paths = [url_to_local_path(source_url)] + [url_to_local_path(ref["url"]) for ref in ordered_refs] + [entry["mask_path"]]
            if not all(paths) or not all(Path(path).is_file() for path in paths):
                raise ValueError("修复所需原图、参考图或遮罩文件不存在")
            uploads = []
            for path in paths:
                result = await service.client.upload_image(str(path))
                if not result.get("success") or not result.get("filename"):
                    raise RuntimeError(f"上传 ComfyUI 参考图失败: {result.get('error') or result}")
                uploads.append(result["filename"])
            seed = secrets.randbelow(2**31 - 1) + 1
            reference_guide = "\n参考图绑定：" + "；".join(
                f'<image_{i}>={ref["kind"]}:{ref["name"]}' for i, ref in enumerate(ordered_refs, 1))
            repair_prompt = plan["prompt"] + reference_guide + "。仅修改遮罩内目标，其他参考图只用于保持身份、场景和道具一致性。"
            denoise = (0.78, 0.88)[round_number - 1]
            graph, output_node = build_masked_repair_graph(service, workflow, repair_prompt,
                                                            novel.aspect_ratio or "16:9", seed, uploads, denoise)
            entry.update(seed=seed, denoise=denoise, graph=graph, workflow_id=workflow.id, output_node=output_node)
            _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：提交 ComfyUI 多图编辑")
            queued = await service.client.queue_prompt(graph)
            if not queued.get("success") or not queued.get("prompt_id"):
                raise RuntimeError(f"ComfyUI 提交失败: {queued.get('error') or queued}")
            entry["prompt_id"] = queued["prompt_id"]
            task.comfyui_prompt_id = entry["prompt_id"]
            task.workflow_id, task.workflow_name = workflow.id, workflow.name
            task.workflow_json = json.dumps(graph, ensure_ascii=False)
            task.reference_images = json.dumps([{"label": "待修复图", "url": source_url}] + [
                {"label": f'{ref["kind"]}:{ref["name"]}', "url": ref["url"]} for ref in ordered_refs], ensure_ascii=False)
            task.seed, task.prompt_text = seed, plan["prompt"]
            _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：ComfyUI 修复中", 12 + 30 * (round_number - 1))
        result = await service.client.wait_for_result(entry["prompt_id"], entry["graph"],
                                                     entry["output_node"], timeout=7200)
        if not result.get("success") or not result.get("image_url"):
            raise RuntimeError(f"ComfyUI 修复失败: {result.get('error') or result}")
        saved = await file_storage.download_image(result["image_url"], novel.id,
                     f"shot_repair_{task.shot_id}_{task.id}_round{round_number}",
                     image_type="shot_edit", chapter_id=task.chapter_id)
        if not saved:
            raise RuntimeError("修复候选图保存失败")
        entry["result_url"], entry["result_path"] = local_path_to_url(saved), saved
        _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：候选图已保存，开始 AI 评审", 23 + 30 * (round_number - 1))
    if not entry.get("candidate_task_id"):
        original_refs = [ref for ref in _json(source_task.reference_images, [])
                         if isinstance(ref, dict) and ref.get("url") and url_to_local_path(ref["url"])]
        references = [dict(ref, picture=index, name=ref.get("name") or ref.get("label"))
                      for index, ref in enumerate(original_refs, 1)]
        first_repair_picture = len(references)
        references.extend({"picture": first_repair_picture + index,
                           "kind": {"character": "CHARACTER_IDENTITY", "scene": "SCENE", "prop": "PROP"}[ref["kind"]],
                           "name": ref["name"],
                           "url": ref["url"], "purpose": "本轮局部修复实际传入的参考图"}
                          for index, ref in enumerate(entry.get("submitted_references") or [], 1))
        candidate = Task(type=REPAIR_CANDIDATE_TYPE, status="running", novel_id=task.novel_id,
                         chapter_id=task.chapter_id, shot_id=task.shot_id, source_task_id=task.source_task_id,
                         parent_task_id=task.id, name=f"修复候选图 · 第 {round_number} 轮",
                         description=source_task.description, prompt_text=source_task.prompt_text,
                         result_url=entry["result_url"], workflow_id=workflow.id, workflow_name=workflow.name,
                         workflow_json=task.workflow_json,
                         reference_images=json.dumps(references, ensure_ascii=False),
                         metadata_json=json.dumps({"reference_manifest": references,
                             "structured_target": {"description": db.get(Shot, task.shot_id).description,
                                                   "characters": _json(db.get(Shot, task.shot_id).characters, []),
                                                   "scene": db.get(Shot, task.shot_id).scene,
                                                   "props": _json(db.get(Shot, task.shot_id).props, [])},
                             "canonical_image_provenance": metadata.get("source_provenance"),
                             "shot_image_repair": {"repair_task_id": task.id, "round": round_number}}, ensure_ascii=False))
        db.add(candidate)
        db.commit()
        entry["candidate_task_id"] = candidate.id
        _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：AI 评审中")
    candidate = db.get(Task, entry["candidate_task_id"])
    review = await review_image_task(db, candidate.id, trigger="generation")
    if review.status == "error":
        # A process restart can interrupt an in-flight LLM response. The
        # candidate image is already durable, so retry its review once only.
        candidate.status = "completed"
        db.commit()
        review = await review_image_task(db, candidate.id, trigger="manual")
    if review.status != "success":
        candidate.status = "failed"
        candidate.error_message = review.error_message or f"AI 评审状态: {review.status}"
        candidate.completed_at = datetime.utcnow()
        db.commit()
        raise RuntimeError(f"AI 评审失败: {review.error_message or review.status}")
    candidate.status, candidate.progress, candidate.completed_at = "completed", 100, datetime.utcnow()
    entry["review_id"], entry["verdict"] = review.id, review.overall
    _save(db, task, metadata, f"第 {round_number}/{MAX_ROUNDS} 轮：AI 评审 {review.overall}", 30 * round_number)
    return entry["result_url"], review


async def run_shot_image_repair(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task or task.status in {"completed", "failed", "cancelled"}:
            return
        task.status, task.started_at = "running", task.started_at or datetime.utcnow()
        db.commit()
        metadata = _metadata(task)
        source_task = db.get(Task, task.source_task_id)
        shot = db.get(Shot, task.shot_id)
        novel = db.get(Novel, task.novel_id)
        if not source_task or not shot or not novel:
            raise ValueError("修复任务的原始分镜、小说或生图任务已不存在")
        db.refresh(shot)
        current_review = _review_for_image(db, source_task.id, shot.image_url or "")
        if (shot.image_task_id != task.source_task_id or shot.image_url != metadata["source_url"]
                or not current_review or current_review.overall != "FAIL"):
            raise ValueError("入队后的原分镜图或 AI 评审已变化，未启动修复")
        catalog = _catalog(db, novel.id, shot)
        if not catalog:
            raise ValueError("修复任务没有可用的角色或场景参考图")
        if not metadata.get("selected_source_url"):
            url, review_id = _choose_source(db, source_task, metadata["source_url"], metadata["source_review_id"])
            metadata["selected_source_url"], metadata["selected_review_id"] = url, review_id
            _save(db, task, metadata, "已选择人物数目和身份问题较少的历史候选图")
        source_url, review_id = metadata["selected_source_url"], metadata["selected_review_id"]
        for number in range(1, MAX_ROUNDS + 1):
            db.refresh(task)
            if task.status == "cancelled":
                return
            entry = (metadata.get("rounds") or [])
            if len(entry) >= number and entry[number - 1].get("verdict"):
                finished = entry[number - 1]
                source_url, review_id = finished["result_url"], finished["review_id"]
                review = db.get(ImageQualityReview, review_id)
            else:
                source_url, review = await _run_round(db, task, metadata, source_url, review_id,
                                                       catalog, source_task, novel, number)
                review_id = review.id
            if review.overall in {"PASS", "WARNING"}:
                db.refresh(task)
                if task.status == "cancelled":
                    return
                db.refresh(shot)
                if shot.image_task_id != task.source_task_id or shot.image_url != metadata["source_url"]:
                    raise ValueError("原分镜图已被其他操作替换，修复候选图保留但未覆盖新图")
                current_review = _review_for_image(db, source_task.id, shot.image_url)
                if not current_review or current_review.overall != "FAIL":
                    raise ValueError("原图评审已改变，修复候选图未替换主分镜图")
                candidate = db.get(Task, metadata["rounds"][number - 1]["candidate_task_id"])
                result_path = metadata["rounds"][number - 1]["result_path"]
                claimed = db.execute(update(Shot).where(Shot.id == shot.id,
                    Shot.image_task_id == task.source_task_id, Shot.image_url == metadata["source_url"])
                    .values(image_task_id=candidate.id)).rowcount
                if not claimed:
                    raise ValueError("主分镜图已变化，修复结果未覆盖新图")
                db.flush()
                commit_visual_state_image(db, shot, source_url, frame_index=None,
                    expected_provenance=metadata.get("source_provenance"), task_id=candidate.id,
                    local_path=result_path)
                task.status, task.progress, task.result_url = "completed", 100, source_url
                task.current_step = f"第 {number} 轮 AI 评审 {review.overall}，已替换主分镜图"
                task.completed_at = datetime.utcnow()
                db.commit()
                return
        task.status, task.progress = "failed", 100
        task.error_message = "两轮局部修复后 AI 评审仍未通过，保留原分镜图"
        task.current_step = task.error_message
        task.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        task = db.get(Task, task_id)
        if task and task.status != "cancelled":
            for round_entry in _metadata(task).get("rounds") or []:
                candidate_id = round_entry.get("candidate_task_id")
                candidate = db.get(Task, candidate_id) if candidate_id else None
                if candidate and candidate.status == "running":
                    candidate.status = "failed"
                    candidate.error_message = str(exc)
                    candidate.completed_at = datetime.utcnow()
            task.status, task.progress = "failed", 100
            task.error_message = str(exc)
            task.current_step = "修复失败；原分镜图未替换"
            task.completed_at = datetime.utcnow()
            db.commit()
        print(f"[ShotImageRepair {task_id}] {type(exc).__name__}: {exc}")
    finally:
        db.close()
