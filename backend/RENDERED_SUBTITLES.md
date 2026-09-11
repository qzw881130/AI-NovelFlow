# Rendered Subtitle Contract

`GET /api/novels/{novel_id}/chapters/{chapter_id}/subtitles?format=srt|ass`
exports the snapshot of `Chapter.final_video`, not a reconstruction of today's
shots or dialogue events. The response identifies `X-Subtitle-Timeline:
rendered-media-v1`. Missing, modified, unsupported or unbound artifacts return
409. Novel/chapter ownership and format validation remain enforced.

## Provenance

- New TTS generation captures the submitted text, TTS asset/task IDs, text hash,
  measured duration and downloaded file SHA-256. This records the TTS request's
  text, not an ASR verification of what the synthesizer actually pronounced.
- Clip Audio generation verifies that snapshot against the actual TTS files and
  current text binding before capturing the exact segments used by its renderer.
  Cues use the renderer's millisecond trim/delay values. An event crossing an
  execution-window boundary produces a separate, clipped cue in each window.
  Each part displays the full event text; word-level splitting is not available.
- Video generation captures the verified Clip Audio snapshot before submission.
  After download, it locally enforces the existing `lock_source` audio contract:
  copy video, replace the remote audio with the frozen canonical final audio,
  encode AAC at audio presentation time zero, without shortening the audio to
  the video. This applies to single-frame, first/last-frame and multi-clip paths.
  Changed/unverified audio is not substituted and cannot authorize subtitles.
- Automatic/manual shot merges and chapter merges compose snapshots inside the
  same low-level merge that normalizes the actual media. It records source
  SHA-256, video/audio starts, common origin, normalized frame and PCM sample
  counts, target frames/samples and cumulative offsets. Offsets advance by actual
  target frames at 24 fps (2,000 samples per frame at 48 kHz), including held
  frames, silence padding and inserted transitions. Cues retain rational timing
  until export. No resolved-duration clock is used.

## Publication and Caching

Each media file has a `.subtitles.json` sidecar with a versioned, checksummed
snapshot and recursive lineage, bound to the media's full SHA-256. Sidecars are
written through fsynced temporary files and atomic replacement. Media and sidecar
are two filesystem publications, not a transactional pair: an interruption
between them makes export/cache validation fail closed. Export validates only
the selected final file and its snapshot, so later event edits, source deletion
or source regeneration cannot rewrite the final subtitles.

Chapter merge signatures are version 3 and include source media and sidecar
hashes. Cache hits require a valid content-bound sidecar, including explicit
subtitle-unavailable mappings for legacy merges. Manual shot merge reuse also
checks its ordered source hashes/snapshots. The chapter task records merge
signature and final media SHA-256 alongside its result URL.

## Limits

- No legacy `dialogues` fallback, logical timeline fallback, ASR, or speculative
  recovery from current TTS against an old video. A DB text hash alone cannot
  prove the contents of an old TTS file. Regenerate TTS, Clip Audio, video and
  then the chapter merge to obtain the new provenance chain.
- Legacy/unbound video still merges successfully; its chapter subtitles are
  unavailable. A source proven by ffprobe to have no audio contributes no cues
  but still advances the media clock. A transition with audio but no verified
  snapshot makes subtitles unavailable, even if it sounds like only music.
- Times describe whole TTS-event intervals, including silence inside an event;
  they are not word or phoneme alignments. SRT rounds to milliseconds; ASS rounds
  to centiseconds, half up. A nonempty cue collapsing to zero at that precision
  is rejected rather than silently discarded. AAC encoding/resampling can alter
  waveform edges; sample-perfect waveform equality is not promised.
- Local sidecars are trusted application artifacts. Checksums detect corruption
  and file replacement, not hostile rewriting of both data and checksums.
- Hashing adds full-file I/O. Snapshot publication failures fail the operation
  rather than claim an unavailable mapping is ready. No database migration is
  required. This endpoint selects the chapter's final output, not arbitrary
  partial-merge task outputs.

## Verification

`tests/test_chapter_subtitles.py` covers export selection and immutability,
ownership/format errors, corruption/replacement/missing snapshots, precision and
escaping, actual clip-render boundary splitting, legacy refusal, local audio
locking, and real two-level ffmpeg merges with early/middle/late beeps. The media
test checks nine decoded waveform boundaries within 5 ms of composed cue times,
with delayed audio, held frames and a silent transition. Existing AudioDrive,
shot-generation and merge timing/progress/cache/recovery suites cover regressions.
Tests use temporary media and in-memory SQLite, not live services or generation.
