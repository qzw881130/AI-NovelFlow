"""Independent observability API. Business sessions are used only for SELECTs."""
import asyncio
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.clip_execution_inspector_service import ClipExecutionInspectorService
from app.services.inspector_frame_service import InspectorFrameService, file_hash, sampling_manifest
from app.services.inspector_store import InspectorError, InspectorStore

router = APIRouter()
store = InspectorStore()
frames = InspectorFrameService(store)
_frame_slots = asyncio.Semaphore(1)


def invoke(action):
    try:
        return action()
    except InspectorError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    except OSError as exc:
        raise HTTPException(503, detail={"code": "INSPECTOR_STORAGE_UNAVAILABLE", "message": "分析文件保存失败，请保留草稿并重试"}) from exc


def service(db):
    return ClipExecutionInspectorService(db, store, frames)


def revision_value(if_match):
    try:
        return int(if_match.strip('"')) if if_match else None
    except ValueError:
        raise InspectorError("INVALID_REVISION", "分析版本无效")


def analysis_response(data, response):
    response.headers["ETag"] = f'"{data["revision"]}"'
    return {"success": True, "data": data}


@router.get("/shots/{shot_id}/clips/{clip_index}/artifacts")
def list_artifacts(shot_id: str, clip_index: int, revision: int | None = None, db: Session = Depends(get_db)):
    return {"success": True, "data": invoke(lambda: service(db).artifacts(shot_id, clip_index, revision))}


@router.get("/executions/{task_id}")
def execution(task_id: str, artifact_id: str | None = None, db: Session = Depends(get_db)):
    return {"success": True, "data": invoke(lambda: service(db).get(task_id, artifact_id)[0])}


@router.get("/executions/{task_id}/evidence")
def evidence(task_id: str, artifact_id: str | None = None, db: Session = Depends(get_db)):
    return {"success": True, "data": invoke(lambda: service(db).get(task_id, artifact_id)[1])}


@router.post("/executions/{task_id}/sampling")
def sampling(task_id: str, payload: dict = Body(default={}), offset: int = Query(0, ge=0),
             limit: int = Query(48, ge=1, le=48), db: Session = Depends(get_db)):
    def action():
        observations = []
        if payload.get("analysis_id"):
            analysis = store.read(payload["analysis_id"])
            variant = next((v for v in analysis["variants"] if v["variant_id"] == payload.get("variant_id", "A")), None)
            if variant is None or variant["projection"]["execution"]["task_id"] != task_id:
                raise InspectorError("SOURCE_IDENTITY_MISMATCH", "分析与执行任务不匹配", 409)
            projection = variant["projection"]
            if payload.get("artifact_id") and payload["artifact_id"] != variant["artifact_id"]:
                raise InspectorError("SOURCE_CHANGED", "分析与视频身份不匹配", 409)
            observations = [o for o in analysis["observations"] if o["variant_id"] == variant["variant_id"]]
        else:
            projection, _ = service(db).get(task_id, payload.get("artifact_id"))
        manifest = sampling_manifest(projection, payload, observations)
        frames.save_sampling(manifest)
        samples = manifest["samples"][offset:offset + limit]
        return {**manifest, "samples": samples, "offset": offset, "limit": limit,
                "next_offset": offset + limit if offset + limit < manifest["unique_frame_count"] else None}
    return {"success": True, "data": invoke(action)}


@router.get("/frames/{video_hash}/metadata/{native_frame_index0}")
def frame_metadata(video_hash: str, native_frame_index0: int):
    return {"success": True, "data": invoke(lambda: frames.frame_metadata(video_hash, native_frame_index0))}


@router.get("/frames/{video_hash}/{render_version}/{preset}/{native_frame_index0}")
async def frame(video_hash: str, render_version: str, preset: str, native_frame_index0: int):
    # Waiting frames must not occupy the shared API worker pool while decoding.
    async with _frame_slots:
        path = await run_in_threadpool(invoke, lambda: frames.extract(video_hash, [native_frame_index0], preset, render_version)[native_frame_index0])
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/analyses")
def create_analysis(response: Response, payload: dict = Body(...), db: Session = Depends(get_db)):
    def action():
        task_id = payload.get("task_id")
        if not isinstance(task_id, str):
            raise InspectorError("INVALID_IDENTITY", "请指定执行任务")
        projection, raw = service(db).get(task_id, payload.get("artifact_id"))
        label = payload.get("label", "A")
        if not isinstance(label, str) or len(label) > 100:
            raise InspectorError("INVALID_LABEL", "分析名称无效")
        return store.create(projection, raw, label)
    return analysis_response(invoke(action), response)


@router.get("/analyses/{analysis_id}")
def read_analysis(analysis_id: str, response: Response):
    def action():
        data = store.read(analysis_id)
        for variant in data["variants"]:
            artifact = variant["projection"]["artifact"]
            try:
                path = frames.resolve_path(artifact["result_url"])
                variant["source_media_status"] = "EXPLICIT" if file_hash(path) == artifact.get("video_sha256") else "SOURCE_CHANGED"
            except InspectorError:
                variant["source_media_status"] = "SOURCE_NOT_AVAILABLE"
        return data
    return analysis_response(invoke(action), response)


@router.post("/analyses/{analysis_id}/observations")
def create_observation(analysis_id: str, response: Response, payload: dict = Body(...), if_match: str | None = Header(None)):
    return analysis_response(invoke(lambda: store.mutate_observation(analysis_id, payload, revision=revision_value(if_match))), response)


@router.patch("/analyses/{analysis_id}/observations/{observation_id}")
def update_observation(analysis_id: str, observation_id: str, response: Response, payload: dict = Body(...), if_match: str | None = Header(None)):
    return analysis_response(invoke(lambda: store.mutate_observation(analysis_id, payload, observation_id, revision_value(if_match))), response)


@router.delete("/analyses/{analysis_id}/observations/{observation_id}")
def delete_observation(analysis_id: str, observation_id: str, response: Response, if_match: str | None = Header(None)):
    return analysis_response(invoke(lambda: store.mutate_observation(analysis_id, observation_id=observation_id,
                                                                   revision=revision_value(if_match), delete=True)), response)
