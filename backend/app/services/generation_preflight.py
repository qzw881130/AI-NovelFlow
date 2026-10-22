"""User-visible video validation catalog and the checks available before queueing."""
import json

from app.models.novel import Character
from app.models.task import Task


CHECKS = (
    {"id": "SHOT_EXISTS", "label": "分镜归属", "description": "分镜必须属于所选章节", "configurable": False},
    {"id": "SHOT_IMAGE_READY", "label": "主分镜图", "description": "视频输入必须有主分镜图", "configurable": False},
    {"id": "CLIP_PLAN_READY", "label": "片段计划", "description": "已规划的 Clip 必须有有效修订版", "configurable": False},
    {"id": "TASK_RELATION_VALID", "label": "任务关系", "description": "不能混用旧 Shot 任务和 Clip 任务", "configurable": False},
    {"id": "ACTIVE_VIDEO_TASK", "label": "重复执行", "description": "同一分镜不能同时执行两个视频任务", "configurable": False},
    {"id": "IDENTITY_FEATURES_RECORDED", "label": "人物稳定特征", "description": "角色有独立记录的稳定外貌特征", "configurable": True},
    {"id": "IDENTITY_PORTRAIT_READY", "label": "人物参考图", "description": "角色已有独立身份参考图", "configurable": True},
)
# These checks run only after the batch starts. Keep them in the same catalog so
# users can see every blocking validation stage without claiming it was already
# evaluated by evaluate_batch(). Only descriptive-language purity is advisory.
RUNTIME_CHECKS = (
    {"id": "VISUAL_PLAN_CONTRACT", "label": "视觉状态与过渡计划", "description": "核对关键帧状态、过渡归属和正式时间轴；需要自动规划时在运行中检查。", "stage": "director", "configurable": False},
    {"id": "REQUIRED_IMAGE_RESOURCES", "label": "必需关键帧图片", "description": "核对本次视频需要的关键帧图片、版本与生成结果；准备图片后检查。", "stage": "director", "configurable": False},
    {"id": "CLIP_EXECUTION_INPUT", "label": "Clip 执行输入", "description": "核对正式片段计划、对白归属、时长与资源来源；运行到 Clip 时检查。", "stage": "director", "configurable": False},
    {"id": "VIDEO_WORKFLOW_CONFIGURATION", "label": "视频工作流配置", "description": "核对所需视频模式的工作流、节点映射及参数是否可用；不检查工作流内部流程。", "stage": "director", "configurable": False},
    {"id": "PHASE_B_SOURCE_BINDING", "label": "Phase B 输入与续接来源", "description": "核对 Canonical 状态、参考图、上一段视频及冻结来源；导演调用前检查。", "stage": "director", "configurable": False},
    {"id": "PHASE_B_PLAN_REUSE", "label": "导演计划复用", "description": "选择复用提示词时，核对原导演计划、模板、输入和工作流仍与当前任务一致。", "stage": "director", "configurable": False},
    {"id": "PHASE_B_DIRECTOR_SCHEMA", "label": "导演输出格式", "description": "核对 LLM 返回的 JSON 字段、描述翻译字段及必填内容；导演返回后检查。", "stage": "director", "configurable": False},
    {"id": "PHASE_B_TIMING_ANCHORS", "label": "对白时间与关键帧", "description": "核对时长、对白 ID 和时序、锚点决策及 Canonical 事实；导演返回后检查。", "stage": "director", "configurable": False},
    {"id": "PHASE_B_LANGUAGE_CONSISTENCY", "label": "提示词语言一致性", "description": "英文模式下检查描述中残留的中文；关闭阻断时记录警告，允许继续生成。台词和完整专名不受此项限制。", "stage": "director", "configurable": True},
    {"id": "PHASE_B_PROMPT_STRUCTURE", "label": "视频提示词结构", "description": "核对六段式结构、Subject/Speaker 绑定、原文对白及时间标记；提交前检查。", "stage": "director", "configurable": False},
    {"id": "PHASE_B_PICTURE_BINDING", "label": "图片引用绑定", "description": "核对 Picture 编号、顺序、实体身份与实际参考图；提交前检查。", "stage": "submission", "configurable": False},
    {"id": "PHASE_B_WORKFLOW_BINDING", "label": "工作流提交绑定", "description": "核对选定工作流的输入、视频续接和输出映射与提交参数；提交 ComfyUI 前检查，不检查工作流内部流程。", "stage": "submission", "configurable": False},
    {"id": "VIDEO_OUTPUT_ARTIFACT", "label": "视频输出文件", "description": "核对 ComfyUI 返回的视频、文件可读性与续接视频的物理属性；生成后检查。", "stage": "assembly", "configurable": False},
    {"id": "CLIP_RESULT_RECOVERY", "label": "Clip 结果恢复与回写", "description": "后端恢复已完成的 ComfyUI 结果时，核对原提交回执、工作流图、Clip 计划修订版、执行类型和结果归属；不一致会阻断回写。", "stage": "assembly", "configurable": False,
     "error_codes": ["CLIP_RECOVERY_RECEIPT_MISMATCH", "CLIP_RECOVERY_WORKFLOW_MISMATCH",
                     "CLIP_RECOVERY_SHOT_MISMATCH", "CLIP_RECOVERY_EXECUTION_CHANGED:PROMPT_ID",
                     "CLIP_RECOVERY_EXECUTION_CHANGED:CONTRACT", "CLIP_RECOVERY_EXECUTION_CHANGED:STATUS",
                     "CLIP_RECOVERY_PLAN_CHANGED", "CLIP_RECOVERY_SUPERSEDED",
                     "CLIP_RECOVERY_RESULT_UNAVAILABLE", "CANONICAL_RECOVERY_CONFLICT",
                     "CANDIDATE_SOURCE_CHANGED", "EXECUTION_PROJECTION_CHANGED",
                     "EXECUTION_PROJECTION_MISSING", "EXECUTION_PROJECTION_MODE_MISMATCH"]},
    {"id": "CLIP_RECEIPT_ACCEPTANCE", "label": "已完成 Clip 回执接受", "description": "人工接受已有 ComfyUI 视频回执时，核对原任务、计划、提示词、时长和回执来源；不通过时保留原任务结果。", "stage": "assembly", "configurable": False,
     "error_codes": ["CLIP_RECEIPT_ACCEPTANCE_SOURCE_MISMATCH", "CLIP_RECEIPT_ACCEPTANCE_ALREADY_STARTED",
                     "CLIP_RECEIPT_ACCEPTANCE_PLAN_CHANGED", "CLIP_RECEIPT_ACCEPTANCE_SUPERSEDED",
                     "CLIP_RECEIPT_ACCEPTANCE_PROMPT_UNVERIFIED", "CLIP_RECEIPT_ACCEPTANCE_DURATION_BINDING_MISMATCH",
                     "CLIP_RECEIPT_ACCEPTANCE_NOT_COMPLETED", "CLIP_RECEIPT_ACCEPTANCE_RECEIPT_MISMATCH",
                     "CLIP_RECEIPT_ACCEPTANCE_RESULT_UNAVAILABLE"]},
    {"id": "CLIP_ASSEMBLY_PROVENANCE", "label": "片段合并来源", "description": "核对 Clip 顺序、任务来源、上一段视频依赖与最终合并输入；合并前检查。", "stage": "assembly", "configurable": False},
)
CATALOG_CHECKS = CHECKS + RUNTIME_CHECKS
CONFIGURABLE = frozenset(item["id"] for item in CATALOG_CHECKS if item["configurable"])


def normalize_policy(value):
    if not isinstance(value, dict) or set(value) - CONFIGURABLE or any(type(v) is not bool for v in value.values()):
        raise ValueError("质量检查策略只接受已列出的可选项目及布尔值")
    return {key: bool(value.get(key, False)) for key in sorted(CONFIGURABLE)}


def config_policy(config):
    try:
        return normalize_policy(json.loads(config.generation_quality_policy or "{}")) if config else normalize_policy({})
    except (TypeError, ValueError):
        return normalize_policy({})


def catalog(policy=None):
    policy = normalize_policy(policy or {})
    return [{**item, "stage": item.get("stage", "before_queue"),
             "blocking": True if not item["configurable"] else policy[item["id"]]}
            for item in CATALOG_CHECKS]


def _issue(check_id, status, message, *, shot=None, policy=None, evidence=None):
    check = next(item for item in CHECKS if item["id"] == check_id)
    return {"id": check_id, "status": status, "message": message,
            "blocking": bool(status == "FAIL" and (not check["configurable"] or
                                                     (policy or {}).get(check_id, False))),
            "shotId": shot.id if shot else None, "shotIndex": shot.index if shot else None,
            "evidence": evidence or {}}


def evaluate_batch(db, chapter_id, shot_ids, *, auto_prepare=False, allow_missing_image=False,
                   policy=None, ignore_task_ids=()):
    """Read-only aggregate; never creates tasks or regenerates media."""
    from app.models.shot import Shot
    policy = normalize_policy(policy or {})
    results = []
    for shot_id in dict.fromkeys(shot_ids):
        shot = db.get(Shot, shot_id)
        if not shot or shot.chapter_id != chapter_id:
            results.append(_issue("SHOT_EXISTS", "FAIL", "分镜不存在或不属于当前章节", policy=policy,
                                  evidence={"shotId": shot_id}))
            continue
        results.append(_issue("SHOT_EXISTS", "PASS", "分镜归属有效", shot=shot, policy=policy))
        try:
            plan = json.loads(shot.video_director_plan or "{}")
        except (TypeError, ValueError):
            plan = {}
        plan = plan if isinstance(plan, dict) else {}
        if shot.image_url or allow_missing_image:
            status = "DEFERRED" if not shot.image_url else "PASS"
            message = "启动后准备主分镜图" if status == "DEFERRED" else "主分镜图已存在"
        else:
            status, message = "FAIL", "缺少主分镜图"
        results.append(_issue("SHOT_IMAGE_READY", status, message, shot=shot, policy=policy))
        clips = plan.get("clip_plan")
        if auto_prepare and not clips:
            status, message = "DEFERRED", "启动后规划 Clip"
        elif clips and (plan.get("clip_plan_validation") or {}).get("passed"):
            status, message = "PASS", "片段计划有效"
        else:
            status, message = "FAIL", "片段计划不存在或未通过校验"
        results.append(_issue("CLIP_PLAN_READY", status, message, shot=shot, policy=policy,
                              evidence={"revision": plan.get("clip_plan_revision")}))
        active = db.query(Task).filter(Task.type == "shot_video", Task.shot_id == shot.id,
                                       Task.status.in_(["pending", "running"]),
                                       Task.id.notin_(list(ignore_task_ids))).first()
        results.append(_issue("ACTIVE_VIDEO_TASK", "FAIL" if active else "PASS",
                              "已有运行中的视频任务" if active else "没有并发视频任务", shot=shot,
                              policy=policy, evidence={"taskId": active.id} if active else {}))
        # Historical tasks under other batches do not conflict with a new one.
        # Flag only impossible typed scope/order pairs in existing records.
        children = db.query(Task).filter(Task.shot_id == shot.id, Task.type == "shot_video").all()
        invalid = [task.id for task in children if task.execution_scope == "CLIP" and task.batch_order is not None]
        results.append(_issue("TASK_RELATION_VALID", "FAIL" if invalid else "PASS",
                              "Clip 任务带有 Shot 批次序号" if invalid else "任务关系有效", shot=shot,
                              policy=policy, evidence={"conflictingTaskIds": invalid}))
        try:
            names = json.loads(shot.characters or "[]")
        except (TypeError, ValueError):
            names = []
        names = names if isinstance(names, list) else []
        characters = {item.name: item for item in db.query(Character).filter(
            Character.novel_id == shot.chapter.novel_id,
            Character.name.in_(names)).all()} if names else {}
        visible_names = [name for name in names if not (characters.get(name) and characters[name].is_narrator)]
        missing_features = [name for name in visible_names if not (characters.get(name) and
                            characters[name].stable_identity_features)]
        missing_portraits = [name for name in visible_names if not (characters.get(name) and
                             characters[name].image_url)]
        for check_id, missing, label in (
            ("IDENTITY_FEATURES_RECORDED", missing_features, "稳定身份特征"),
            ("IDENTITY_PORTRAIT_READY", missing_portraits, "身份参考图"),
        ):
            results.append(_issue(check_id, "FAIL" if missing else "PASS",
                                  f"以下角色缺少{label}：{'、'.join(missing)}" if missing else f"{label}已就绪",
                                  shot=shot, policy=policy, evidence={"characters": missing}))
    return {"version": 1, "ready": not any(result["blocking"] for result in results),
            "checks": results, "policy": policy}
