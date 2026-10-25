"""Record the completed C run, visual evidence, and pending human speaker review."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from run import C, ROOT, PROJECT, OUTPUT, read, save, sha


def main():
    execution = read(C / "comfyui/execution.json")
    assert execution["success"] and execution["status"] == "COMPLETED"
    assert read(C / "review/evidence_export.json")["complete"]
    assert read(C / "authority_check.json")["all_checks_pass"]
    diff = read(C / "prompt_diff.json")
    source_graph = read(C / "control_a_workflow.json")
    c_graph = read(C / "comfyui/workflow.json")
    media = read(C / "media_probe.json")
    a_media = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(ROOT / "output/optimized_original_duration.mp4")]))
    a_video = next(s for s in a_media["streams"] if s["codec_type"] == "video")
    c_video = next(s for s in media["streams"] if s["codec_type"] == "video")
    c_audio = next(s for s in media["streams"] if s["codec_type"] == "audio")
    actual_media_equal = all(a_video[key] == c_video[key] for key in ["width", "height", "avg_frame_rate", "nb_frames", "duration"])
    assert actual_media_equal
    stripped = (C / "prompt.txt").read_text()
    for change in diff["changes"]:
        stripped = stripped.replace(change["inserted_text"], "", 1)
    assert stripped.encode() == (ROOT / "optimizer/optimized_h3_prompt.txt").read_bytes()
    normalized_graph = json.loads(json.dumps(c_graph))
    for node, field in [("138", "value"), ("169", "filename_prefix")]:
        normalized_graph[node]["inputs"][field] = source_graph[node]["inputs"][field]
    assert normalized_graph == source_graph

    observations = {
        "D1": "左侧Subject3在部分检查帧中有嘴形变化；右侧非speaker Subject4在1.708/1.917s也有明显张口。是否提前执行D2、产生额外人声或抢台词，需听辨。",
        "D2": "右侧Subject4在3.5/3.917/4.375s检查帧中有张口变化，手臂保持放下；实际声源、逐字台词和同步尚未听辨。",
        "D3": "6.083333s硬切后皇帝进入较近构图；6.375/7.458s可见皇帝张口，8s嘴形收拢。左侧Subject3也有表情/嘴形变化；右侧Subject4被切出画面，无法检查其嘴。不能据此确认皇帝说出了该句或排除画外抢台词。",
        "D4": "8.5–9.208s抽查中左侧Subject3有明显嘴形变化，皇帝大体闭口，Subject2仍在右边缘。Subject4不在画内，实际语音归属与额外人声仍待核验。",
        "D5": "9.708/10.083/10.25s皇帝有明显嘴形变化，但左侧非speaker Subject3也有可疑张口。10.541667s硬切到两骗子，皇帝在D5结束10.8s之前出画。不能把可见张口视为voice ownership通过。",
        "D6": "右侧Subject4在11.5–12.833s检查帧中有明显嘴形变化并抬起双手展示空手；皇帝与Subject2在画外，实际台词、声源和额外人声仍需听辨。",
    }
    clip_manifest = read(C / "review/dialogue_clip_manifest.json")
    speakers = []
    for e, clip in zip(read(C / "canonical_dialogue.json"), clip_manifest):
        event = e["dialogue_id"]
        assert event == clip["event"]
        speakers.append({"event": event, "canonical_speaker": e["subject"], "start_time": e["start_time"],
                         "end_time": e["end_time"], "exact_dialogue": e["text"],
                         "speaker_ownership": "NEEDS_MANUAL_REVIEW", "actual_speaker": None,
                         "assigned_speaker_articulation": "NEEDS_MANUAL_REVIEW",
                         "non_speaker_articulation": "NEEDS_MANUAL_REVIEW",
                         "exact_dialogue_accuracy": "NEEDS_MANUAL_REVIEW", "extra_voices": "NEEDS_MANUAL_REVIEW",
                         "repeated_dialogue": "NEEDS_MANUAL_REVIEW", "missing_dialogue": "NEEDS_MANUAL_REVIEW",
                         "visual_observation": observations[event], "visual_observation_is_not_audio_verification": True,
                         "sequence_A": str(C / f"review/A_{event}_sequence.jpg"),
                         "sequence_C": str(C / f"review/C_{event}_sequence.jpg"), "review_clips": clip})
    speaker_review = {"status": "NEEDS_MANUAL_REVIEW", "audio_track_present": True,
                      "audio_fully_decoded": True, "audio_transcription_performed": False,
                      "reliable_chinese_voice_identity_analysis_performed": False,
                      "events": speakers, "actual_D3_speaker": None, "actual_D5_speaker": None,
                      "subject_2_has_no_canonical_dialogue": True,
                      "non_speaker_lip_articulation_improvement": "NEEDS_MANUAL_REVIEW",
                      "limitation": "The reviewed native frames show mouth shapes, not verified speech-synchronized articulation or the identity of an audible Chinese voice. Review full originals if words drift outside the canonical clip windows."}
    save("review/speaker_review.json", speaker_review)

    boundaries = read(C / "review/native_cut_manifest.json")
    confirmed_cuts = [
        {**boundaries["cuts"][0], "candidate_only_until_visual_review": False, "visually_confirmed_hard_cut": True,
         "C_before_after": "四人较宽群像瞬间变为皇帝、Subject3和Subject2的近景，Subject4出画。",
         "A_at_same_native_frame_pair": "构图连续，四人仍在画内。"},
        {**boundaries["cuts"][1], "candidate_only_until_visual_review": False, "visually_confirmed_hard_cut": True,
         "C_before_after": "皇帝近景瞬间变为两骗子近景，皇帝与Subject2出画。",
         "A_at_same_native_frame_pair": "构图连续，皇帝、两骗子和Subject2仍可见。"},
    ]
    visual = {
        "method": "完整MP4音视频解码；全片scene score>0.2；A/C同时间各44帧及6组事件序列抽查；两处C候选的相邻原生帧直接观察；KF1/2/3原始图与A/C对比。未执行可靠音频转录或声音身份识别。",
        "continuous_shot": {"status": "FAIL", "a_improvement_preserved": False,
                            "A_scene_candidates": [], "C_scene_candidates": [6.083333, 10.541667],
                            "confirmed_hard_cuts": confirmed_cuts,
                            "finding": "C重新出现两次明显硬切，时间与Baseline旧硬切不同；A的连续镜头改善没有保留。"},
        "KF2_hands_down": {"status": "PASS", "a_improvement_preserved": True,
                           "requested_anchor_time": 4.95, "native_sample_time": 119 / 24,
                           "finding": "C与A在KF2检查帧均保持Subject4双臂放下，接近Picture2；C未恢复Baseline提前抬手的状态。",
                           "evidence": str(C / "review/KF2_reference_A_C.jpg"), "scope": "anchor frame inspection"},
        "KF3_empty_hands": {"status": "PASS", "finding": "13s检查帧中Subject4双掌展示空手，未见实体布料或新增手持道具。",
                            "evidence": str(C / "review/KF3_reference_A_C.jpg"), "scope": "sampled display frames"},
        "KF3_composition_scale": {"status": "FAIL", "a_problem_resolved": False, "new_ensemble_loss": True,
                                  "finding": "A和C均比Picture3明显过近；C最终构图只保留两骗子，皇帝、总管和宝座出画，A在相同时刻仍能看到皇帝与总管。",
                                  "evidence": str(C / "review/KF3_reference_A_C.jpg")},
        "identity_costume": {"status": "NO_OBVIOUS_REGRESSION_IN_REVIEWED_FRAMES",
                             "finding": "出现在画内的角色仍可辨认，维持皇帝蓝衣红披风、骗子1绿衣黑帽、骗子2红衣棕帽、总管深色服装。未见明显身份互换或额外复制人物；这不证明全片所有身份细节通过。"},
        "blocking": {"status": "FAIL_COMPOSITION_CONTINUITY",
                     "finding": "前段群像左右关系保留；两次切镜使ensemble持续可读性回退。不能用稀疏帧确认严格floor-position lock。",
                     "floor_position_continuity": "NEEDS_MANUAL_REVIEW"},
        "new_obvious_visual_regression": True,
        "new_regressions": ["两处硬切", "尾段皇帝与总管出画，丢失A仍保留的群像关系"],
    }
    save("review/visual_review.json", visual)

    before = read(C / "isolation_before.json")["existing_experiment_files"]
    changed, missing = [], []
    for rel, digest in before.items():
        path = ROOT / rel
        if not path.is_file():
            missing.append(rel)
        elif sha(path) != digest:
            changed.append(rel)
    new = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and not p.is_relative_to(C) and str(p.relative_to(ROOT)) not in before]
    workspace_before = read(C / "workspace_before.json")
    outside_changed = [p for p, digest in workspace_before.items() if not (PROJECT / p).is_file() or sha(PROJECT / p) != digest]
    current_paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=PROJECT).decode().split("\0")
    outside_new = [p for p in current_paths if p and (PROJECT / p).is_file() and not (PROJECT / p).is_relative_to(ROOT) and p not in workspace_before]
    references = [{"picture": item["picture"], "unchanged_after_generation": sha(item["original_path"]) == item["original_sha256"]}
                  for item in read(ROOT / "baseline/input_assets.json")]
    isolation = {"status": "PASS" if not changed and not missing and new == ["output/experiment_c_speaker_binding.mp4"] and not outside_changed and not outside_new and all(r["unchanged_after_generation"] for r in references) else "FAIL",
                 "existing_experiment_file_count": len(before), "changed_existing_A_files": changed, "missing_existing_A_files": missing,
                 "new_files_outside_experiment_c": new, "changed_workspace_files_outside_experiment_root": outside_changed,
                 "new_workspace_files_outside_experiment_root": outside_new, "original_references_after_generation": references,
                 "workspace_check_scope": "git-tracked and non-ignored untracked files outside the experiment root; existing experiment artifacts include ignored files. This is not a database audit.",
                 "formal_services_or_database_write_calls": 0,
                 "checked_at_utc": datetime.now(timezone.utc).isoformat()}
    save("isolation_after.json", isolation)
    assert isolation["status"] == "PASS", isolation

    conclusion = "INCONCLUSIVE / NEEDS MANUAL SPEAKER REVIEW"
    result = {
        "experiment": "H3 Prompt Optimizer V1 — Shot 3 / C1 — Experiment C Speaker Binding",
        "conclusion": conclusion,
        "conclusion_reason": "主指标speaker ownership尚缺可靠实际播放听辨，不能确认D3/D5声源；局部嘴形线索不能证明通过。视觉证据已确认连续镜头回退及尾段群像丢失，KF2手态改善保留。",
        "source_A_prompt_id": execution["source_a_prompt_id"], "C_prompt_id": execution["prompt_id"],
        "A_user_confirmed_speaker_ownership": "FAIL", "A_failed_dialogue_event": None,
        "A_manual_review_source": str(ROOT / "review/user_speaker_review.json"),
        "C_speaker_ownership": "NEEDS_MANUAL_REVIEW", "events": speakers,
        "A_successful_real_submission_and_video": True,
        "B_single_semantic_variable_confirmed": True,
        "B_only_prompt_change": "PER_DIALOGUE_SPEAKER_OWNERSHIP_REINFORCEMENT",
        "B_only_workflow_changes": ["138.inputs.value", "169.inputs.filename_prefix"],
        "C_event_speaker_results": {e["event"]: e["speaker_ownership"] for e in speakers},
        "D_D3_actual_speaker": "NEEDS_MANUAL_REVIEW", "D_D5_actual_speaker": "NEEDS_MANUAL_REVIEW",
        "E_non_speaker_lip_articulation_improved": "NEEDS_MANUAL_REVIEW",
        "F_A_continuous_shot_improvement_preserved": False,
        "G_A_KF2_hands_down_improvement_preserved": True,
        "H_new_obvious_visual_regression": True,
        "generation": execution,
        "frozen_conditions": {
            "workflow": "Minimax H3 多参考生视频 V20260928", "seed": 3720777255, "requested_duration_seconds": 13.1,
            "resolution": [864, 480], "fps": 24, "frames": 328, "sampling": "euler/simple/steps6/denoise1",
            "unet": c_graph["127"]["inputs"], "clip": c_graph["128"]["inputs"],
            "video_vae": c_graph["119"]["inputs"], "audio_vae": c_graph["120"]["inputs"],
            "lora": c_graph["147"]["inputs"], "sigma_shift": c_graph["149"]["inputs"],
            "reference_count": 9, "original_high_resolution_references": True, "vision_proxy_used_for_video": False,
            "topology_wiring_models_and_all_other_parameters_identical_to_A": normalized_graph == source_graph,
            "actual_media_properties_equal_A": actual_media_equal, "llm_calls": 0,
        },
        "prompt": {"A_characters": diff["a_characters"], "C_characters": diff["c_characters"],
                   "A_sha256": diff["a_sha256"], "C_sha256": diff["c_sha256"], "insertions": 6,
                   "removing_insertions_restores_exact_A_bytes": True, "authority": "PASS"},
        "media": {"path": str(OUTPUT), "sha256": sha(OUTPUT), "size_bytes": OUTPUT.stat().st_size,
                  "video_duration_seconds": float(c_video["duration"]), "audio_duration_seconds": float(c_audio["duration"]),
                  "audio_codec": c_audio["codec_name"], "audio_sample_rate": c_audio["sample_rate"],
                  "audio_channels": c_audio["channels"], "full_AV_decode": "PASS"},
        "visual_comparison": visual, "isolation": isolation,
        "evidence": {
            "prompt_diff": str(C / "prompt_diff.json"), "authority_check": str(C / "authority_check.json"),
            "workflow_diff": str(C / "comfyui/workflow_diff.json"), "remote_reference_checks": str(C / "comfyui/reference_byte_check.json"),
            "real_history": str(C / "comfyui/history.json"), "probe": str(C / "media_probe.json"),
            "speaker_review": str(C / "review/speaker_review.json"), "visual_review": str(C / "review/visual_review.json"),
            "dialogue_clip_manifest": str(C / "review/dialogue_clip_manifest.json"),
            "A_C_silent_comparison": str(C / "review/A_C_comparison_silent.mp4"),
            "embedded_workflow_check": str(C / "review/embedded_workflow_check.json"),
        },
        "limitations": ["Six event statuses await reliable human playback with audio.",
                        "Clip windows follow canonical timings and have 0.2s padding; speech may drift beyond those windows.",
                        "Sampled mouth shapes do not verify spoken words, audible voice identity, or exact lip synchronization.",
                        "A user confirmed at least one Emperor line spoken by Subject4, but did not identify D3 versus D5.",
                        "One A/C pair cannot establish a general production rule or separate all backend nondeterminism."],
        "next_action": "STOP_AND_WAIT_FOR_USER_PLAYBACK_FEEDBACK", "additional_generations": 0,
    }
    save("RESULT.json", result)

    report = f"""# Experiment C — Shot 3 / C1 Speaker Binding

结论：**{conclusion}**。

C 已真实生成，单变量检查通过。D1–D6 的语音归属均为 **NEEDS_MANUAL_REVIEW**，尤其不能凭皇帝张口的静帧确认 D3/D5 已修复。可确认的视觉结果是：KF2 手态改善保留，但 A 的连续镜头改善丢失，C 出现两次硬切，尾段还将皇帝与总管切出画面。

## A. 是否成功提交并生成真实视频？

**是。** ComfyUI `/prompt` 返回 HTTP 200，prompt ID `{execution['prompt_id']}`；history 为 `success/completed`，执行耗时 **{execution['generation_time_seconds']} 秒**。直接下载 node 169 的真实 MP4，并完整解码视频与音轨，无解码错误。

- [C 完整视频，含原始音轨]({OUTPUT})
- [A 完整视频，含原始音轨]({ROOT / 'output/optimized_original_duration.mp4'})
- [实际 execution]({C / 'comfyui/execution.json'})、[ComfyUI history]({C / 'comfyui/history.json'})、[ffprobe]({C / 'media_probe.json'})、[完整 AV 解码检查]({C / 'review/decode_check.json'})

MP4：864×480，24 FPS，328 帧；视频物理时长 13.666667 秒、音轨 13.667 秒，AAC / 32 kHz / 双声道。这与 A 的帧数、FPS、分辨率和物理时长完全一致。Requested duration 仍是 **13.1 秒**，物理尾部来自冻结帧数计算，没有修改台词或 anchor 时间。

SHA256：`{sha(OUTPUT)}`。

## B. A → C 是否还有其他 Prompt / workflow / parameter 变量？

**没有其他主动修改的语义变量。** 控制基线是 A 实际提交 graph 的 node 138 Prompt，已与 `optimizer/optimized_h3_prompt.txt` 逐字确认一致。C 只插入六段 event-local speaker ownership lock，保留 A 的全局规则。

| 检查 | 结果 |
|---|---|
| 唯一语义变化 | PER_DIALOGUE_SPEAKER_OWNERSHIP_REINFORCEMENT |
| 字符数 | A {diff['a_characters']:,} → C {diff['c_characters']:,} |
| 移除六段插入 | 与 A 原始字节完全相同 |
| 台词数量 / speaker / exact text / timing / order | 全部不变 |
| Subject / Picture / binding / reference authority | 全部不变 |
| KF timing / duration / identity lock / camera / action / chronological execution / soundscape | 全部不变 |
| graph 差异 | 仅 `138.inputs.value` 和 `169.inputs.filename_prefix` |
| workflow / topology / wiring / model / LoRA / SigmaShift / 所有其他参数 | 全部不变 |
| LLM / Optimizer 调用 | 0 |
| 参考图 | 原来九张高清图；远端字节 SHA256 与 A 原图全部一致 |

冻结条件：`Minimax H3 多参考生视频 V20260928`；seed **3720777255**；requested **13.1s**；**864×480 / 24 FPS / 328 frames**；**euler / simple / steps=6 / denoise=1**；相同端点 `{execution['endpoint']}`。完整模型、LoRA 和 SigmaShift 值记录于 RESULT 与实际 graph。

- [Prompt]({C / 'prompt.txt'})、[结构化 diff]({C / 'prompt_diff.json'})、[可读 patch]({C / 'prompt_diff.patch'})、[Authority Check]({C / 'authority_check.json'})
- [冻结 workflow 对照]({C / 'comfyui/workflow_diff.json'})、[C 提交 graph]({C / 'comfyui/workflow.json'})、[九图远端字节检查]({C / 'comfyui/reference_byte_check.json'})

MP4 内嵌 graph 额外带有 ComfyUI 自动添加的九个 `LoadImage.is_changed` 原图 SHA256 缓存字段；去除这九个元数据字段后，与实际提交 graph 完全一致。history 中的 graph 直接与提交 graph 相同。此项是输出元数据差异，没有改变节点输入或实验变量。[证据]({C / 'review/embedded_workflow_check.json'})

隔离复核 **PASS**：原有 {len(before)} 个实验文件逐文件 hash 未变，包括 A 的输入、输出、日志和视频；ROOT 中 C 目录外唯一新增文件是指定 C MP4；实验开始前已有的项目工作区改动保持原样。未调用正式服务或数据库写入路径，原始九图生成后再次核对不变。[隔离检查与覆盖范围]({C / 'isolation_after.json'})

## C. D1–D6 speaker ownership

以下时间均为**原始完整视频的 canonical 时间**，不是自动检测出的实际发声时间。A 的用户播放反馈确认“至少一条皇帝台词被骗子2说出”，但尚未明确 D3 / D5，不能把这个 FAIL 擅自分配给某个 event。

| Event | canonical speaker | 时间 | exact dialogue | C ownership | 带声音对照片段 |
|---|---|---|---|---|---|
"""
    for e in speakers:
        event = e["event"]
        report += f"| {event} | {e['canonical_speaker'].replace('<', '&lt;').replace('>', '&gt;')} | {e['start_time']}–{e['end_time']}s | {e['exact_dialogue']} | NEEDS_MANUAL_REVIEW | [A]({C / f'review/clips/A_{event}.mp4'}) / [C]({C / f'review/clips/C_{event}.mp4'}) |\n"
    report += f"""
片段各保留前后 0.2 秒，完整声音重新编码为 AAC，未静音或替换声线。canonical event 在片段内从约 0.2 秒开始。如果台词有时间漂移，应回到完整原片复核。[片段窗口 manifest]({C / 'review/dialogue_clip_manifest.json'})

assigned speaker articulation、non-speaker speech-like articulation、额外人声、台词逐字准确性、重复或遗漏台词，六项均尚无可靠声音复核，**NEEDS_MANUAL_REVIEW**。Subject2 的 canonical Dialogue Event 仍为零；不能据此断言生成视频里完全无人声越权。

## D. D3 / D5 皇帝台词到底是谁说的？

**D3：NEEDS_MANUAL_REVIEW。** 应由皇帝 / Subject1 说“听说你们会织一种特别的布？”，5.15–8.15s。C 在 6.375 / 7.458s 检查帧可见皇帝张口，与 A 中右侧骗子2可疑张口的视觉表现不同，但没有可靠音频身份判断；不能确定实际说出这句话的人，也不能排除画外人声。[D3 C 带声音]({C / 'review/clips/C_D3.mp4'}) / [C 原生帧序列]({C / 'review/C_D3_sequence.jpg'}) / [A 同时刻序列]({C / 'review/A_D3_sequence.jpg'})。

**D5：NEEDS_MANUAL_REVIEW。** 应由皇帝 / Subject1 说“它有多漂亮？”，9.55–10.8s。C 在 9.708 / 10.083 / 10.25s 皇帝有嘴形变化，左侧骗子1也有可疑张口；10.541667s 已切至两骗子构图，皇帝在 canonical event 结束前出画。仍需听辨实际声音与台词归属。[D5 C 带声音]({C / 'review/clips/C_D5.mp4'}) / [C 原生帧序列]({C / 'review/C_D5_sequence.jpg'}) / [A 同时刻序列]({C / 'review/A_D5_sequence.jpg'})。

## E. non-speaker lip articulation 是否改善？

**NEEDS_MANUAL_REVIEW，尚不能确认改善。** D3 / D5 皇帝出现更可见的嘴形变化是局部视觉线索；C 的 D1 非speaker Subject4仍有张口，D5 非speaker Subject3也有可疑嘴形。部分角色被切出画面，更不能用“画内没张口”替代对所有 non-speaker 的核验。静帧无法区分表情、台词漂移和与声音同步的 articulation。[逐事件记录]({C / 'review/speaker_review.json'})

## F. A 的连续镜头改善是否保留？

**否，FAIL。** C 全片 scene score>0.2 检出两处候选，并直接检查相邻原生帧确认硬切：

| 原生帧，0-based | PTS | C 实际变化 | A 同帧对 |
|---|---|---|---|
| 145→146 | 6.041667→6.083333s | 四人较宽群像硬切皇帝、骗子1与总管近景，骗子2出画 | 构图连续 |
| 252→253 | 10.500000→10.541667s | 皇帝近景硬切两骗子近景，皇帝与总管出画 | 构图连续 |

这两处不是 Baseline 原来的 6.875 / 9.375s 边界。C 保持了 Prompt 中的 camera 指令，但模型的实际执行仍回退。

- [145→146 原生帧 A/C]({C / 'review/native_cut_145_146_A_C.jpg'})、[252→253 原生帧 A/C]({C / 'review/native_cut_252_253_A_C.jpg'})、[scene 检测]({C / 'review/scene_detection.json'})
- [A 左 / C 右全片画面对照，无声音]({C / 'review/A_C_comparison_silent.mp4'})；声音判断应使用上方原片或带声音片段。

## G. KF2 手态改善是否保留？

**是，PASS（anchor 帧检查）。** 4.95s 最近原生帧是 frame119 / 4.958333s，C 的 Subject4 与 A 均双臂放下，接近 Picture2，未出现 Baseline 那种提前双手抬起的状态。[原图 / A / C 对照]({C / 'review/KF2_reference_A_C.jpg'})

## H. 是否有新的明显视觉退化？

**有。** 两次硬切使 ensemble 连续可读性回退。KF3@13s 仍能看到 Subject4 空手展示，未见布料，但构图仍远比 Picture3 近；C 只保留两骗子，皇帝、总管和宝座出画，A 在同时间仍能看到皇帝与总管。[KF3 原图 / A / C]({C / 'review/KF3_reference_A_C.jpg'})

抽查画内角色仍可辨认，主要服装颜色与左右关系未见明显身份交换或重复身体。严格地面站位、全片身份细节仍需播放复核；构图丢失不等于角色被删除。[视觉记录]({C / 'review/visual_review.json'})

## 本轮证据边界与停止点

**{conclusion}**。主指标尚缺可靠声音复核，不能宣布 speaker reinforcement 有效或无效；C 的视觉回退已可确认。单次同 seed 的 A/C 也不足以建立正式规则。

本轮仅 C 一次提交；LLM 调用 0；未做 B、15秒、timing/gap/seed/reference/KF/Clip 修改或其他生成。实际生成、视频检查、对照证据和报告已完成，**停止并等待用户播放反馈**。

[机器可读 RESULT]({C / 'RESULT.json'})。
"""
    (C / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"report": str(C / "REPORT.md"), "result": str(C / "RESULT.json"),
                      "conclusion": conclusion, "isolation": isolation["status"],
                      "A_files_unchanged": len(before), "C_hard_cuts": [6.083333, 10.541667]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
