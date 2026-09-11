# NovelFlow Autonomous Production Test: The Boy Who Cried Wolf

Date: 2026-09-11. Result: **PASS with in-session bug fixes and normal UI editorial work**. This is not a claim that the unmodified application completed a one-click run.

## Delivered Video

- [Play the final video](http://192.168.50.3:5173/api/files/story_aa228450/chapter_18bdefe7/merged-videos/shots_only-25ca7667aed079ad98ed3ba15db943e5a383b2d551908b949f60acf5cf233e79.mp4)
- [Open the novel in NovelFlow](http://192.168.50.3:5173/novels/aa228450-b763-4a7e-91cd-81f13592bff1)
- Local file: `backend/user_story/story_aa228450/chapter_18bdefe7/merged-videos/shots_only-25ca7667aed079ad98ed3ba15db943e5a383b2d551908b949f60acf5cf233e79.mp4`.
- Actual container duration: **95.458 seconds**. Planned duration before video generation: **92 seconds**. No overlength movie was generated and subsequently cut down to meet the limit.
- One new novel, one chapter, **13 Shots and 14 completed H3 Clips**. Shot 13 uses two Clips and a real Shot merge; the chapter merge includes all 13 Shots in order.
- H.264, 1728 x 960, nominal 24 fps, 2,291 decoded video frames; AAC stereo, 48 kHz; 70,404,410 bytes (about 67.1 MiB).
- Novel ID: `aa228450-b763-4a7e-91cd-81f13592bff1`; chapter ID: `18bdefe7-9f7e-4592-b3fa-4a800b661240`.

## Actual Product Route

Browser UI creation and saving of the novel/chapter; AI character, scene and prop parsing; reference generation; AI Shot planning; Shot image generation; existing character voice generation; Audio Events, TTS, Timeline and Clip Audio; keyframe planning/images; S/F/M video generation; Clip-to-Shot and Shot-to-chapter merging; chapter playback and download.

- Authored a short original rendition of the classic fable, displayed as 320 characters in the UI.
- Generated seven visible-character references, two scene references and two prop references. Added the omitted village-lane scene through the normal scene UI.
- Added nine short narration events through the Shot editor, retaining eight dialogue events. Generated three reference voices and 17 TTS utterances using the existing ComfyUI voice/audio functionality.
- Used normal image editing for concrete identity/prop/anatomy problems. Rejected one edit that made the image worse. No aesthetic seed sweep or rerender of the eight initially successful videos was performed.
- Replanning recovery required some replacement keyframe generation because the current UI has no historical-image rebinding picker. This was recovery work, not best-of selection.
- Every production creation, edit, generation, retry and merge was initiated in the real UI. DevTools/source/log inspection and scoped read-only SQL were used for diagnosis. No direct database insert/update, fake task completion, fabricated CID, synthetic result URL or database repair was used.
- No new TTS system or external speech-generation path was introduced. Phase 3 research and its benchmark machinery were not resumed.

## Models Actually Used

| Stage | Model / configured stack |
|---|---|
| LLM parsing, planning and prompt construction | DeepSeek `deepseek-v4-flash-vision-exp` |
| Character references | Z-image-turbo, `z_image_turbo_bf16.safetensors` |
| Scene/prop references, Shot images, keyframes and image edits | Flux2 Klein 9B, `flux-2-klein-9b.safetensors` |
| Reference voice design | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, through ComfyUI |
| Utterance synthesis / voice cloning | `Qwen/Qwen3-TTS-12Hz-1.7B-Base`, `TDQwen3TTSVoiceClone`, through ComfyUI |
| Video | Existing MiniMax H3 AudioDrive S/F/M workflows, `10Eros_Max_h3_fl2va_beta1_pruned.safetensors`, Turbo 8-step LoRA |

AudioDrive was exercised fully. TTS is derived from Audio Events and the selected voice owner. Timeline uses measured utterance durations and pauses. Drive Audio contains visible-speaker speech; Final Audio contains the dialogue/narration mix. Shot 13 includes a dialogue Clip and a later narration-only Clip. Its windows are `[0,4.137)` and `[4.137,10)`.

## Actual Bugs And Code Changes

These are this session's changes in the named files, not ownership of their entire pre-existing worktree diff.

| Problem observed in production | Code changed | Verification |
|---|---|---|
| At 1200px, side panels covered the AI split toolbar | `frontend/my-app/src/pages/ChapterGenerate/components/ThreeColumnLayout.tsx`, `ShotSplitTab.tsx` | Layout regressions; ordinary browser click succeeded at the original viewport |
| Appending narration produced duplicate event order 1 | `frontend/my-app/src/pages/ChapterGenerate/components/ShotForm.tsx`, `ShotSplitTab.tsx` | Add/delete/save regressions; normal UI resave produced 1/2 and retained READY TTS |
| Keyframe replanning replaced valid manually sized AudioDrive windows | `backend/app/api/shots.py`, `backend/app/services/audio_drive_service.py` | Window/revision/range tests; actual two-window replan retained Clip Audio 2/2 |
| Negated reference lists and a negated previous-image baseline were rejected as unbound assets | `backend/app/services/keyframe_reference_contract.py` | Exact failing clauses plus affirmative-reference counterexamples; normal UI retries succeeded |
| SINGLE readiness ignored valid audio stored in `clips` when execution windows were empty | `frontend/my-app/src/pages/ChapterGenerate/components/VideoGenTab.tsx` | Selector regressions and UI 1/1 verification; underlying audio had not been deleted |
| Historical completed-task polling overwrote an edited keyframe in frontend state | `frontend/my-app/src/pages/ChapterGenerate/stores/slices/generationSlice.ts` | Reload/polling regressions; both Clip thumbnails retained the edit. No wrong backend H3 reference submission was established for this incident |
| Batch preflight cleared its own owner; placeholder FIRST_LAST frames were treated as a complete plan | `backend/app/api/shots.py` | Ownership/concurrency and plan-completeness regressions; recovery submitted only missing Shots, preserving successful media |
| Ordinary `none of`, `No visible character performs lip-sync`, and `non-lip-sync` text caused false speech contradictions | `backend/app/services/video_director_ai.py` | Exact negative examples and true affirmative-speech counterexamples; final Shot 10 generated successfully |
| Reload shutdown could leave old background workers alive | `backend/start.sh` | Added a 10-second graceful-shutdown bound, shell syntax check, successful real restart/reload; identified orphan backend workers were stopped while application and ComfyUI queues were empty |

Added or extended tests: `frontend/my-app/tests/shot-split-layout.test.mjs`, `audio-event-order.test.mjs`, `video-generation.test.mjs`; `backend/tests/test_keyframe_audio_windows.py`, `test_keyframe_planner_modes.py`, `test_keyframe_reference_contract.py`, `test_video_ui_state_transfer.py`, `test_video_batch_failure_status.py`, `test_video_director_gate_d4.py`.

Latest checks: frontend **49 passed**; reference-contract **544 passed**; speech/audit suite **72 passed** using isolated database fixtures. The broader preflight/ownership/H3 regression run passed **3313 tests, with 3 optional external-snapshot cases skipped**. These overlapping runs are not added into a unique-test total. TypeScript, Vite build, shell syntax and `git diff --check` also passed. Python used `backend/venv/bin/python`; necessary service starts used `./start.sh` from `backend`.

The first video batch produced eight successful Shots. Five pre-submission failures were recovered without rerendering those eight. The last speech-audit failure was also pre-submission; failed task records remain as real history, not rewritten success records.

## Lightweight Acceptance

- Browser chapter player reached `ended=true` at 95.458 seconds without a media error. A 390px mobile viewport also loaded and played the same video without horizontal page overflow.
- The complete video and audio decoded successfully. A 0.25-second black-screen detector found no sustained black intervals under its stated threshold; this is not a claim of perfect frames.
- Chronological frame review covers grazing, the first false alarm and arrival, the second deception, the real wolf, ignored help, the chase/loss and the lesson.
- Audio is present and source events/speaker bindings were checked. Measured peak is about -14.2 dBFS; the mix is quiet. This is not a word-by-word human listening or frame-accurate phoneme-sync certification.

## Quality Limits And Next Three Improvements

The above failures were functional bugs. Remaining output limitations are separate: character age/costume/prop details drift across Shots; some secondary figures disappear or change during transitions; framing is repetitive; movement and joins are not hand-polished. These observations do not establish a theoretical model ceiling.

The movie also lacks a finished sound mix and editorial polish. Voice level is conservative, some holds are long, and music/ambience/rhythm have not received an editor's finishing pass. The chapter list's generic status can still say waiting despite an available completed merged video; playback/download are the authoritative delivered result here.

If only three improvements are allowed next, based on this actual movie:

1. Stabilize recurring character age, costume, props and visual style across Shots.
2. Finish dialogue/narration loudness and ambience consistently, using the existing audio chain.
3. Tighten pauses and Shot joins around actual speech/action endings; improve repetitive framing and awkward turns/exits.

No further generation or capability research is required to open the delivered video.
