from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.audio_drive import (
    AudioEventPatchRequest,
    AudioEventTTSRequest,
    BuildAudioTimelineRequest,
    BuildClipAudioRequest,
    BuildExecutionWindowsRequest,
    PrepareAudioBatchRequest,
    PrepareAudioRequest,
    ShotAudioTTSBatchRequest,
)
from app.services.audio_drive_service import AudioDriveService


router = APIRouter()


def _return_or_raise(result: dict):
    if result.get("status_code"):
        raise HTTPException(status_code=result["status_code"], detail=result.get("message"))
    return result


@router.get("/shots/{shot_id}/audio-events", response_model=dict)
async def list_audio_events(shot_id: str, db: Session = Depends(get_db)):
    """获取 Shot 的 Audio Event 列表。"""
    return _return_or_raise(AudioDriveService(db).list_events(shot_id))


@router.patch("/audio-events/{event_id}", response_model=dict)
async def patch_audio_event(event_id: str, data: AudioEventPatchRequest, db: Session = Depends(get_db)):
    """编辑 Audio Event，并按字段变化标记下游状态失效。"""
    return _return_or_raise(AudioDriveService(db).patch_event(event_id, data.model_dump(exclude_unset=True)))


@router.post("/audio-events/{event_id}/tts", response_model=dict)
async def generate_audio_event_tts(event_id: str, data: AudioEventTTSRequest, db: Session = Depends(get_db)):
    """为单条 Audio Event 创建 TTS 任务，通过串行 worker 执行。"""
    return _return_or_raise(AudioDriveService(db).create_tts_task(event_id, force=data.force))


@router.post("/shots/{shot_id}/audio/tts/generate", response_model=dict)
async def generate_shot_audio_tts(shot_id: str, data: ShotAudioTTSBatchRequest, db: Session = Depends(get_db)):
    """批量创建 Shot 下 Audio Events 的 TTS 任务，通过串行 worker 执行。"""
    return _return_or_raise(AudioDriveService(db).create_batch_tts_tasks(
        shot_id,
        event_ids=data.eventIds,
        only_stale=data.onlyStale,
        force=data.force,
    ))


@router.get("/shots/{shot_id}/audio-timeline", response_model=dict)
async def get_audio_timeline(shot_id: str, db: Session = Depends(get_db)):
    """获取 Shot 当前 Audio Timeline。"""
    return _return_or_raise(AudioDriveService(db).get_timeline(shot_id))


@router.post("/shots/{shot_id}/audio-timeline/build", response_model=dict)
async def build_audio_timeline(shot_id: str, data: BuildAudioTimelineRequest, db: Session = Depends(get_db)):
    """基于 READY 的 TTS assets 构建 Audio Timeline，并回写 resolved duration。"""
    return _return_or_raise(AudioDriveService(db).build_timeline(shot_id, force=data.force))


@router.post("/shots/{shot_id}/audio-timeline/rebuild", response_model=dict)
async def rebuild_audio_timeline(shot_id: str, data: BuildAudioTimelineRequest, db: Session = Depends(get_db)):
    """强制重建 Audio Timeline。"""
    return _return_or_raise(AudioDriveService(db).build_timeline(shot_id, force=True or data.force))


@router.post("/shots/{shot_id}/video/execution-windows/build", response_model=dict)
async def build_execution_windows(shot_id: str, data: BuildExecutionWindowsRequest, db: Session = Depends(get_db)):
    """按 Audio Timeline / max duration 构建 execution_windows。"""
    return _return_or_raise(AudioDriveService(db).build_execution_windows(shot_id, max_clip_duration=data.maxClipDuration))


@router.post("/shots/{shot_id}/video-director/clips/{window_index}/audio/build", response_model=dict)
async def build_video_director_clip_audio(
    shot_id: str,
    window_index: int,
    data: BuildClipAudioRequest,
    db: Session = Depends(get_db),
):
    """为当前 Video Director Clip 构建 speaker_timeline，并预留 Drive/Final 音频产物元数据。"""
    return _return_or_raise(AudioDriveService(db).build_clip_audio(shot_id, window_index, force=data.force))


@router.post("/shots/{shot_id}/audio/prepare", response_model=dict)
async def prepare_shot_audio(shot_id: str, data: PrepareAudioRequest, db: Session = Depends(get_db)):
    """创建持久化 AudioDrive 准备任务，完整执行 TTS、Timeline、执行窗口和 Clip Audio。"""
    return _return_or_raise(AudioDriveService(db).create_audio_prepare_task(
        [shot_id],
        max_clip_duration=data.maxClipDuration,
        force_tts=data.forceTts,
        force_clip_audio=data.forceClipAudio,
    ))


@router.post("/audio/prepare-batch", response_model=dict)
async def prepare_batch_audio(data: PrepareAudioBatchRequest, db: Session = Depends(get_db)):
    """创建持久化批量 AudioDrive 准备任务，后端串行处理所有分镜。"""
    return _return_or_raise(AudioDriveService(db).create_audio_prepare_task(
        data.shotIds,
        max_clip_duration=data.maxClipDuration,
        force_tts=data.forceTts,
        force_clip_audio=data.forceClipAudio,
    ))
