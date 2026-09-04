from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AudioEventPatchRequest(BaseModel):
    voiceOwnerCharacterId: Optional[str] = None
    voiceOwnerName: Optional[str] = None
    visibleSpeakerCharacterId: Optional[str] = None
    visibleSpeakerName: Optional[str] = None
    requiresVisibleLipsync: Optional[bool] = None
    text: Optional[str] = None
    emotionPrompt: Optional[str] = None
    pauseAfter: Optional[str] = None


class AudioEventTTSRequest(BaseModel):
    force: bool = False


class ShotAudioTTSBatchRequest(BaseModel):
    eventIds: Optional[List[str]] = None
    onlyStale: bool = True
    force: bool = False


class BuildAudioTimelineRequest(BaseModel):
    force: bool = False


class BuildExecutionWindowsRequest(BaseModel):
    maxClipDuration: Optional[float] = Field(default=None, gt=0)


class BuildClipAudioRequest(BaseModel):
    force: bool = False


class PrepareAudioRequest(BaseModel):
    maxClipDuration: Optional[float] = Field(default=None, gt=0)
    forceTts: bool = False
    forceClipAudio: bool = True


class PrepareAudioBatchRequest(PrepareAudioRequest):
    shotIds: List[str]


class AudioEventResponse(BaseModel):
    id: str
    shotId: str
    order: int
    type: str
    voiceOwnerCharacterId: Optional[str]
    voiceOwnerName: str
    visibleSpeakerCharacterId: Optional[str]
    visibleSpeakerName: Optional[str]
    requiresVisibleLipsync: bool
    text: str
    emotionPrompt: Optional[str]
    pauseAfter: str
    ttsStatus: str
    currentTtsAsset: Optional[Dict[str, Any]] = None


class AudioTimelineResponse(BaseModel):
    id: str
    shotId: str
    revision: int
    totalDuration: float
    status: str
    audioSummary: Dict[str, Any]
    events: List[Dict[str, Any]]
