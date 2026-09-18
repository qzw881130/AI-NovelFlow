from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from app.schemas.shot_revision import RevisionRequest


class AudioEventPatchRequest(RevisionRequest):
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


class AudioTimingSummaryResponse(BaseModel):
    measurementBasis: str = "READY_TTS_ASSET_FILE_DURATION"
    ttsEventCount: int
    readyTtsEventCount: int
    ttsCoverageComplete: bool
    unmeasuredAudioEventIds: List[str]
    measuredTtsDurationSeconds: float = Field(description="Sum of stored READY TTS file durations, including silence inside each source.")
    measuredTtsCoverageSeconds: float = Field(description="Union of READY TTS file intervals on this timeline; not detected speech activity.")
    lastTtsFileEndSeconds: Optional[float] = Field(description="Last measured TTS file end, not an actual phoneme or action endpoint.")
    authoredFinalPauseSeconds: Optional[float] = Field(description="Final pause captured by the timeline; null when unknown in legacy metadata.")
    visualEstimatedFloorSeconds: float
    resolvedDurationSeconds: float
    remainingNonSpeechHoldSeconds: Optional[float] = Field(description="Resolved duration after the last TTS file end, including authored final pause; null for incomplete/stale coverage.")
    holdAfterAuthoredFinalPauseSeconds: Optional[float]
    longTailReviewSuggested: bool = Field(description="Review-only hint for at least 3 seconds beyond the file end plus authored final pause. Never a trim or failure.")


class AudioTimelineResponse(BaseModel):
    id: str
    shotId: str
    revision: int
    totalDuration: float
    audioRequiredDuration: Optional[float] = None
    status: str
    audioSummary: Dict[str, Any]
    events: List[Dict[str, Any]]
    timingSummary: Optional[AudioTimingSummaryResponse] = None
