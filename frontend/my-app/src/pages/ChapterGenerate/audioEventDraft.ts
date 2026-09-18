import type { AudioDriveEvent } from '../../api/audioDrive';

/** Update a binding as a unit. The authority resolves cleared IDs in ChapterScope. */
export function editAudioEvent(event: AudioDriveEvent, field: keyof AudioDriveEvent, value: string | boolean): AudioDriveEvent {
  const next = {...event, [field]: value};
  if (field === 'voiceOwnerName') {
    next.voiceOwnerCharacterId = null;
    if (event.type === 'DIALOGUE' && event.visibleSpeakerName === event.voiceOwnerName) {
      next.visibleSpeakerName = String(value) || null;
      next.visibleSpeakerCharacterId = null;
      next.requiresVisibleLipsync = Boolean(value);
    }
  }
  if (field === 'visibleSpeakerName') {
    next.visibleSpeakerCharacterId = null;
    next.visibleSpeakerName = String(value) || null;
    next.requiresVisibleLipsync = Boolean(value);
    if (value) {next.voiceOwnerName = String(value); next.voiceOwnerCharacterId = null;}
  }
  if (field === 'requiresVisibleLipsync') {
    next.visibleSpeakerName = value ? next.voiceOwnerName : null;
    next.visibleSpeakerCharacterId = null;
  }
  if (next.type === 'NARRATION') {
    next.voiceOwnerName = '旁白'; next.voiceOwnerCharacterId = null;
  } else if (field === 'type' && next.voiceOwnerName === '旁白') {
    next.voiceOwnerName = ''; next.voiceOwnerCharacterId = null;
  }
  if (next.type !== 'DIALOGUE') {
    next.visibleSpeakerName = null; next.visibleSpeakerCharacterId = null; next.requiresVisibleLipsync = false;
  }
  return next;
}
