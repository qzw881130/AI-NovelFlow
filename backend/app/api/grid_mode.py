"""Novel-mode gated grid generation endpoints. Legacy routes remain unchanged."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.schemas.grid_shot import load_grid_data, read_grid_clip_plan
from app.services.grid_pipeline import GridPipeline, GridPipelineError
from app.services.grid_tasks import GRID_TASK_TYPES, enqueue_grid_job
from app.services.grid_auto_batch import enqueue_grid_auto_batch

router = APIRouter()


class PanelPlanRequest(BaseModel):
    layout: str | None = None


class PanelReviewRequest(BaseModel):
    status: str
    note: str = ""


class ClipPrepareRequest(BaseModel):
    reference_strategy: str | None = None


class GridBatchRequest(BaseModel):
    step: str


class GridAutoBatchRequest(BaseModel):
    shot_ids: list[str]
    merge_chapter: bool = False


def _context(db: Session, novel_id: str, chapter_id: str, shot_id: str | None = None):
    novel = db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    if novel.video_mode != "grid":
        raise HTTPException(409, "此小说使用单镜图模式，请使用原生成页面")
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first()
    if not chapter:
        raise HTTPException(404, "章回不存在")
    shot = None
    if shot_id:
        shot = db.query(Shot).filter(Shot.id == shot_id, Shot.chapter_id == chapter_id).first()
        if not shot:
            raise HTTPException(404, "Shot 不存在")
    return novel, chapter, shot


def _shot_payload(shot):
    data = load_grid_data(shot.grid_data)
    plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=data.revision) if data else None
    return {"id": shot.id, "index": shot.index, "description": shot.description,
            "duration": shot.duration, "characters": json.loads(shot.characters or "[]"),
            "scene": shot.scene, "dialogues": json.loads(shot.dialogues or "[]"),
            "gridData": data.model_dump() if data else None,
            "gridClipPlan": plan, "videoUrl": shot.video_url}


def _queued(task: Task):
    return {"success": True, "data": {"taskId": task.id, "status": task.status,
                                        "name": task.name}}


def _enqueue(db, novel, chapter, shot, step, **kwargs):
    try:
        return _queued(enqueue_grid_job(db, novel, chapter, shot, step, **kwargs))
    except (GridPipelineError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


def _ensure_shot_idle(db: Session, shot_id: str):
    shot = db.get(Shot, shot_id)
    auto = db.query(Task).filter(Task.chapter_id == shot.chapter_id,
                                 Task.type.in_(["grid_auto_batch", "grid_board_batch"]),
                                 Task.status.in_(["pending", "running"])).first() if shot else None
    if auto and shot_id in json.loads(auto.metadata_json or "{}").get("shot_ids", []):
        raise HTTPException(409, "此 Shot 正在自动批量生成")
    active = db.query(Task.id).filter(Task.shot_id == shot_id, Task.type.in_(GRID_TASK_TYPES),
                                      Task.status.in_(["pending", "running"])).first()
    if active:
        raise HTTPException(409, "此 Shot 有宫格任务待执行或正在执行")


@router.get("/{novel_id}/chapters/{chapter_id}/grid")
def get_grid_chapter(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    novel, chapter, _ = _context(db, novel_id, chapter_id)
    shots = db.query(Shot).filter(Shot.chapter_id == chapter_id).order_by(Shot.index).all()
    return {"success": True, "data": {"novel": {"id": novel.id, "title": novel.title, "videoMode": novel.video_mode},
                                      "chapter": {"id": chapter.id, "title": chapter.title, "finalVideo": chapter.final_video},
                                      "shots": [_shot_payload(shot) for shot in shots]}}


@router.post("/{novel_id}/chapters/{chapter_id}/grid/batch")
async def enqueue_batch(novel_id: str, chapter_id: str, request: GridBatchRequest,
                        db: Session = Depends(get_db)):
    novel, chapter, _ = _context(db, novel_id, chapter_id)
    if request.step not in {"panels_plan", "board_prepare", "board_generate",
                            "clips_plan", "clip_prepare", "clip_generate", "shot_merge"}:
        raise HTTPException(422, "不支持此批量步骤")
    candidates = []
    for shot in db.query(Shot).filter(Shot.chapter_id == chapter_id).order_by(Shot.index).all():
        grid = load_grid_data(shot.grid_data)
        if request.step == "panels_plan":
            if not grid:
                candidates.append((shot, None))
        elif request.step == "board_prepare":
            if grid and not grid.board_prompt and not grid.board_image_url:
                candidates.append((shot, None))
        elif request.step == "board_generate":
            if grid and grid.board_prompt and not grid.board_image_url:
                candidates.append((shot, None))
        elif grid:
            plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=grid.revision)
            if request.step == "clips_plan":
                if not plan and grid.panels and all(p.image_url and p.review_status == "passed" for p in grid.panels):
                    candidates.append((shot, None))
            elif request.step == "shot_merge":
                if plan and not shot.video_url and all(clip.get("video_url") for clip in plan["clip_plan"]):
                    candidates.append((shot, None))
            elif plan:
                for clip in plan["clip_plan"]:
                    if request.step == "clip_prepare" and not clip.get("prompt"):
                        candidates.append((shot, clip["clip_index"]))
                    elif request.step == "clip_generate" and clip.get("prompt") and not clip.get("video_url"):
                        candidates.append((shot, clip["clip_index"]))
    if not candidates:
        raise HTTPException(422, "没有已预览且待生成的项目")
    if db.query(Task.id).filter(Task.chapter_id == chapter_id, Task.type.in_(GRID_TASK_TYPES | {"grid_auto_batch", "grid_board_batch"}),
                                Task.status.in_(["pending", "running"])).first():
        raise HTTPException(409, "本章有宫格任务正在排队或执行，请完成后再批量提交")
    labels = {"panels_plan": "规划子格", "board_prepare": "准备整板提示词",
              "board_generate": "生成宫格整板", "clips_plan": "规划 Clip",
              "clip_prepare": "编译 H3 提示词", "clip_generate": "生成 H3 Clip",
              "shot_merge": "合并 Shot"}
    batch = Task(type="grid_batch", status="pending", novel_id=novel_id, chapter_id=chapter_id,
                 name=f"批量{labels[request.step]} · {chapter.title}",
                 current_step=f"等待执行 {len(candidates)} 项", progress=0,
                 metadata_json=json.dumps({"video_mode": "grid", "grid_step": request.step,
                                           "expected_count": len(candidates)}, ensure_ascii=False))
    db.add(batch)
    db.flush()
    children = []
    try:
        for order, (shot, clip_index) in enumerate(candidates, 1):
            children.append(enqueue_grid_job(db, novel, chapter, shot, request.step,
                                             clip_index=clip_index, parent_task_id=batch.id,
                                             batch_order=order))
    except (GridPipelineError, ValueError) as exc:
        batch.status, batch.error_message, batch.current_step = "failed", str(exc), "批量提交中断"
        batch.completed_at = datetime.utcnow()
        db.commit()
        raise HTTPException(409, str(exc)) from exc
    return {"success": True, "data": {"taskId": batch.id, "status": batch.status,
                                        "children": [child.id for child in children]}}


@router.post("/{novel_id}/chapters/{chapter_id}/grid/auto-batch")
async def enqueue_auto_batch(novel_id: str, chapter_id: str, request: GridAutoBatchRequest,
                             db: Session = Depends(get_db)):
    novel, chapter, _ = _context(db, novel_id, chapter_id)
    try:
        task = enqueue_grid_auto_batch(db, novel, chapter, request.shot_ids,
                                       merge_chapter=request.merge_chapter)
    except (GridPipelineError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return _queued(task)


@router.post("/{novel_id}/chapters/{chapter_id}/grid/auto-board-batch")
async def enqueue_auto_board_batch(novel_id: str, chapter_id: str, request: GridAutoBatchRequest,
                                   db: Session = Depends(get_db)):
    novel, chapter, _ = _context(db, novel_id, chapter_id)
    try:
        task = enqueue_grid_auto_batch(db, novel, chapter, request.shot_ids,
                                       merge_chapter=request.merge_chapter, target_stage="board")
    except (GridPipelineError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return _queued(task)


@router.post("/{novel_id}/chapters/{chapter_id}/grid/plan")
async def plan_chapter(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    novel, chapter, _ = _context(db, novel_id, chapter_id)
    return _enqueue(db, novel, chapter, None, "chapter_plan")


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/panels/plan")
async def plan_panels(novel_id: str, chapter_id: str, shot_id: str, request: PanelPlanRequest,
                      db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "panels_plan", layout=request.layout)


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/board/prepare")
async def prepare_board(novel_id: str, chapter_id: str, shot_id: str, db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "board_prepare")


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/board/generate")
async def generate_board(novel_id: str, chapter_id: str, shot_id: str, db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "board_generate")


@router.patch("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/panels/{panel_index}/review")
def review_panel(novel_id: str, chapter_id: str, shot_id: str, panel_index: int,
                 request: PanelReviewRequest, db: Session = Depends(get_db)):
    _, _, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    try:
        data = GridPipeline(db).review_panel(shot, panel_index, request.status, request.note)
        return {"success": True, "data": data.model_dump()}
    except GridPipelineError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/panels/{panel_index}/prepare")
def prepare_panel_retry(novel_id: str, chapter_id: str, shot_id: str, panel_index: int,
                        db: Session = Depends(get_db)):
    novel, _, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    try:
        return {"success": True, "data": GridPipeline(db).prepare_panel_retry(novel, shot, panel_index)}
    except GridPipelineError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/panels/{panel_index}/generate")
async def generate_panel_retry(novel_id: str, chapter_id: str, shot_id: str, panel_index: int,
                               db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "panel_generate", panel_index=panel_index)


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/panels/{panel_index}/replace")
async def replace_panel(novel_id: str, chapter_id: str, shot_id: str, panel_index: int,
                        file: UploadFile = File(...), db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    try:
        data = GridPipeline(db).replace_panel(novel, chapter, shot, panel_index, await file.read())
        return {"success": True, "data": data.model_dump()}
    except (GridPipelineError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/clips/plan")
async def plan_clips(novel_id: str, chapter_id: str, shot_id: str, db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "clips_plan")


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/clips/{clip_index}/prepare")
async def prepare_clip(novel_id: str, chapter_id: str, shot_id: str, clip_index: int,
                       request: ClipPrepareRequest, db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "clip_prepare", clip_index=clip_index,
                    strategy=request.reference_strategy)


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/clips/{clip_index}/generate")
async def generate_clip(novel_id: str, chapter_id: str, shot_id: str, clip_index: int,
                        db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "clip_generate", clip_index=clip_index)


@router.post("/{novel_id}/chapters/{chapter_id}/grid/shots/{shot_id}/merge")
async def merge_shot(novel_id: str, chapter_id: str, shot_id: str, db: Session = Depends(get_db)):
    novel, chapter, shot = _context(db, novel_id, chapter_id, shot_id)
    _ensure_shot_idle(db, shot.id)
    return _enqueue(db, novel, chapter, shot, "shot_merge")


@router.post("/{novel_id}/chapters/{chapter_id}/grid/merge")
async def merge_chapter(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    novel, chapter, _ = _context(db, novel_id, chapter_id)
    return _enqueue(db, novel, chapter, None, "chapter_merge")
