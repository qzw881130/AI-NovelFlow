"""Stable, user-visible checks for a Shot video batch before it is queued."""
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
CONFIGURABLE = frozenset(item["id"] for item in CHECKS if item["configurable"])


def normalize_policy(value):
    if not isinstance(value, dict) or set(value) - CONFIGURABLE or any(type(v) is not bool for v in value.values()):
        raise ValueError("质量检查策略只接受已列出的可选项目及布尔值")
    return {key: bool(value.get(key, False)) for key in sorted(CONFIGURABLE)}


def config_policy(config):
    try:
        return normalize_policy(json.loads(config.generation_quality_policy or "{}"))
    except (TypeError, ValueError):
        return normalize_policy({})


def catalog(policy=None):
    policy = normalize_policy(policy or {})
    return [{**item, "blocking": True if not item["configurable"] else policy[item["id"]]}
            for item in CHECKS]


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
