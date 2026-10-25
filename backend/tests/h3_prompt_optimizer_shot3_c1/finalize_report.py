"""Report only observed artifacts; blocked output is never represented as success."""
import json
from pathlib import Path
import importlib.util
import subprocess

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("isolated_experiment", ROOT / "experiment.py")
exp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp)


def load(path):
    return json.loads((ROOT / path).read_text())


def dump(path, value):
    exp.write_json(path, value)


task = load("baseline/task_snapshot.json")
params = load("baseline/generation_params.json")
assets = load("baseline/input_assets.json")
events = load("baseline/canonical_dialogue.json")
model_log = load("optimizer/call_log.json")
history = load("comfyui/baseline_history.json")[task["comfyui_prompt_id"]]
timestamps = {name: detail["timestamp"] for name, detail in history["status"]["messages"] if "timestamp" in detail}
generation_seconds = (timestamps["execution_success"] - timestamps["execution_start"]) / 1000
assert not (ROOT / "optimizer/optimizer_result.json").exists(), "Use a results report after the real optimizer succeeds"
blocked_authority = {
    "status": "NOT_RUN", "reason": "Optimizer request failed with HTTP 401 INVALID_API_KEY; no optimized_prompt exists.",
    "dialogue_event_count_preserved": None, "dialogue_speaker_preserved": None,
    "exact_dialogue_preserved": None, "picture_binding_preserved": None,
    "subject_identity_preserved": None, "no_new_picture_references": None,
    "temporal_anchor_order_preserved": None, "all_checks_pass": None,
    "optimized_prompt_manually_modified": False,
}
dump("authority_check.json", blocked_authority)
execution = {
    "status": "NOT_SUBMITTED", "success": False, "submission_attempts": 0, "prompt_id": None,
    "reason": "Optimizer failed authentication; substituting an invented optimized prompt would invalidate this experiment.",
    "comfyui_endpoint": "http://192.168.50.1:8288", "comfyui_reachable": True,
    "all_frozen_node_classes_available": True, "reference_byte_matches": "9/9",
    "workflow_reference": str(ROOT / "baseline/submitted_workflow.json"),
    "experiment_a_duration": 13.1, "seed": params["seed"], "resolution": params["resolution"],
    "output_path": None, "experiment_b_status": "NOT_RUN",
}
dump("comfyui/experiment_a_execution.json", execution)
observations = {
    "method": "Actual baseline MP4 ffprobe, full AV decode, timed frame inspection; no reliable audio transcription or continuous lip-sync ownership assessment.",
    "baseline_decode": load("review/baseline_decode_check.json"),
    "optimized_video_available": False,
    "items": [
        {"metric": "speaker_correctness", "status": "NEEDS_MANUAL_REVIEW", "evidence": "Canonical D4 is Subject 3 at 8.35–9.35s, while frames at 8.35 and 8.85s show only the Emperor close-up. Off-screen audio speaker cannot be determined from frames."},
        {"metric": "lip_sync_ownership", "status": "NEEDS_MANUAL_REVIEW", "evidence": "D5 belongs to Subject 1 at 9.55–10.8s; sampled Subject 4 mouth shapes change at 9.55, 9.85, 10.175, 10.5s. This suggests unwanted non-speaker articulation, but exact spoken audio and continuous synchronization have not been established."},
        {"metric": "identity", "status": "LIMITED_FRAME_OBSERVATION", "evidence": "The Emperor, steward, left tall scammer and right shorter scammer remain recognizable in sampled ensemble frames; no obvious duplicated bodies or exchanged left/right identities in these samples. Continuous identity stability needs manual playback."},
        {"metric": "costume", "status": "LIMITED_FRAME_OBSERVATION", "evidence": "Sampled costumes remain Emperor blue/red/gold, steward dark coat, Subject 3 green coat/black hat, Subject 4 red coat/brown hat. No obvious costume reset in samples."},
        {"metric": "blocking", "status": "LIMITED_FRAME_OBSERVATION", "evidence": "Subjects 3/4 occupy established left/right sides in ensemble samples; Emperor remains seated and steward beside steps. Foreground subjects become much larger late in the clip; camera-vs-body contribution needs playback."},
        {"metric": "temporal_transition", "status": "OBSERVED_DEVIATION", "evidence": "Opening bowed Subjects become upright, and Subject 4 shows empty palms; late composition at 13s is a tight foreground view rather than Picture 3's ensemble spacing."},
        {"metric": "camera", "status": "OBSERVED_DEVIATION", "evidence": "Frames at 7.5–8.85s show an isolated Emperor close-up. Frames at 9.35–13.4s emphasize close foreground scammers. Raw prompt requests an uninterrupted low-angle dolly with ensemble spatial legibility and no isolated portrait framing. Exact cut timing is not measured."},
        {"metric": "unexpected_object", "status": "LIMITED_FRAME_OBSERVATION", "evidence": "Subject 4's hands appear empty in the inspected gesture frames. No obvious physical fabric, added people or duplicate bodies observed in samples; whole-video absence needs manual review."},
        {"metric": "overall_execution", "status": "COMPARISON_UNAVAILABLE", "evidence": "No optimized video was generated, so improvement or harm cannot be compared."},
    ],
}
dump("review/video_review.json", observations)
before = load("logs/workspace_before.json")
modified = [p for p, sha in before.items() if not (exp.PROJECT / p).is_file() or exp.digest(exp.PROJECT / p) != sha]
current_files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=exp.PROJECT).decode().split("\0")
new_outside = [p for p in current_files if p and p not in before and not (exp.PROJECT / p).is_relative_to(ROOT)]
original_assets_unchanged = all(exp.digest(a["original_path"]) == a["original_sha256"] for a in assets)
baseline_unchanged = exp.digest(params["baseline_source_path"]) == params["baseline_sha256"]
dump("logs/isolation_check.json", {
    "tracked_and_existing_untracked_content_unchanged": not modified,
    "changed_files_outside_experiment": modified, "new_nonignored_files_outside_experiment": new_outside,
    "original_reference_assets_unchanged": original_assets_unchanged,
    "production_baseline_video_unchanged": baseline_unchanged,
    "database_access": "sqlite mode=ro; product services never imported; no INSERT/UPDATE/DELETE or schema writes",
    "formal_api_calls": 0, "production_task_creations": 0, "comfyui_generation_submissions": 0,
})
baseline_info = {
    "status": "REUSED_VERIFIED_COMPLETED_BASELINE", "task_id": task["id"], "prompt_id": task["comfyui_prompt_id"],
    "workflow": task["workflow_name"], "generation_time_seconds": generation_seconds,
    "graph_matches_remote_history": load("baseline/submitted_workflow.json") == history["prompt"][2],
    "prompt_matches_submitted_graph": task["prompt_text"] == history["prompt"][2]["138"]["inputs"]["value"],
    "remote_reference_bytes_match_originals": all(c["match"] for c in load("comfyui/reference_byte_check.json")),
    "original_duration": params["original_duration"], "physical_video_duration": 328 / 24,
    "seed": params["seed"], "resolution": params["resolution"], "output_path": params["baseline_copy_path"],
    "original_path": params["baseline_source_path"], "sha256": params["baseline_sha256"],
}
dump("baseline/baseline_verification.json", baseline_info)
duration = model_log["request_duration_seconds"]
switches = sum(events[i]["subject"] != events[i-1]["subject"] for i in range(1, len(events)))
rows = "\n".join(f"| {a['picture']} | {a['kind']} | {a.get('subject_binding') or ('KF'+str(a['source_keyframe_index'])+' @ '+str(a['source_time_seconds'])+'s' if a['source_keyframe_index'] else a['source_name'])} | {a['original_size'][0]}×{a['original_size'][1]} | {a['vision_proxy_size'][0]}×{a['vision_proxy_size'][1]} |" for a in assets)
dialogue_rows = "\n".join(f"| {e['dialogue_id']} | {e['subject']} / {e['speaker']} | {e['start_time']}–{e['end_time']}s | {e['text']} |" for e in events)
report = f"""# H3 Prompt Optimizer V1 — Shot 3 / C1 隔离实验

状态：**BLOCKED_AT_OPTIMIZER_AUTHENTICATION**。真实多图 Optimizer 请求收到 **HTTP 401 / INVALID_API_KEY**，因此没有 Optimized Prompt，也没有提交 Experiment A 或生成 Optimized 视频。本次未完成 Optimizer → ComfyUI → 视频输出链路，不能作为成功实验。

实验目录：`{ROOT}`。本报告以已保存的真实调用和媒体证据为依据；所有新增产物仅在此目录。日期：2026-10-09（Asia/Shanghai）。

## A. Shot 3 / C1 基线信息

| 项目 | 真实值 |
|---|---|
| Shot ID / index | `{exp.SHOT_ID}` / 3 |
| Clip ID | `{exp.SHOT_ID}:clip:1` |
| 当前已组装版本的 C1 task | `{task['id']}` |
| Novel / Chapter | 《皇帝的新装》章回体改写V5 / test 2 |
| Original Duration | **13.1s** |
| 物理视频时长 / 帧数 | 13.666666667s / 328 帧（24fps） |
| Reference 数量 | 9 |
| Reference 类型 | DIRECTOR_VISUAL_ANCHOR ×3、SCENE ×1、CHARACTER_IDENTITY ×4、PROP ×1 |
| Subjects | 4：Subject 1 皇帝、Subject 2 宫廷总管、Subject 3 骗子1、Subject 4 骗子2 |
| Dialogue Events / Active Speakers / Speaker Switches | 6 / 3 / {switches} |
| Speaker Sequence | 3 → 4 → 1 → 3 → 1 → 4 |
| Chronological Visual Anchors | 3：KF1 @0s、KF2 @4.95s、KF3 @13s |
| 专用 TEMPORAL 控制锚点 | C1 无；capability=GENERATE |
| Workflow | `{task['workflow_name']}` / `{task['workflow_id']}` |
| 实际 graph 来源 | `tasks.workflow_json`，与远端 history 的 graph 完全相等 |
| H3 Model / text encoder | minimax_h3_ref2va_bf16 / qwen3vl_32b_minimax_h3_int8_convrot |
| Seed | **{params['seed']}** |
| Resolution | **864×480**，不是系统设置中的1920×1080；以实际提交图和输出为准 |
| Sampling | euler / simple / steps=6 / denoise=1；其余模型、LoRA、SigmaShift 参数见冻结 graph |
| Previous AV | `previous_video_available=false`；未人为制造 |

当前 C1 的 `metadata.prompt_text`、`tasks.prompt_text` 和 graph node 138 `value` 完全相等，Raw Prompt 为 19,415 字符。Clip 起止为0–13.1s；当前 Shot 全长128s未用于本轮生成。当前 plan 的 assembly_task_ids[0] 指向上述 task，避免误用较早 C1 版本。

| Event | 绑定 | Canonical timing | Exact dialogue |
|---|---|---|---|
{dialogue_rows}

Baseline 无需重复生成：已有成功视频、实际提交图、Raw Prompt、seed、reference order 均可验证。视频原始路径为 `{params['baseline_source_path']}`；只复制到 `output/baseline.mp4`，未覆盖原文件。

## B. Optimizer 输入

完整输入：`optimizer/optimizer_input.json`；用户提供的 Meta-Prompt 原文保存在 `optimizer/optimizer_meta_prompt.txt`。HTTP payload 含9张带明确 Picture 标签的 JPEG data URL，保存在 `optimizer/llm_request.json`，认证头已脱敏。

| Picture | 类型 | Binding / Authority | 原图尺寸 | Vision Proxy |
|---|---|---|---|---|
{rows}

Vision Proxy：长边≤1024、保持比例、无裁切、不放大、JPEG quality=85；仅尺寸压缩，不做增强、重绘或锐化。原图字节副本在 `inputs/`，各原始路径、hash、proxy路径、hash、workflow input 节点均记录于 `baseline/input_assets.json`。ComfyUI 保留原始输入文件，远端 `/view?type=input` 返回的9张图片 SHA-256 全部与本地原图一致。

Character identity仅管身份；场景仅管环境；道具仅管外观；Director Visual Anchor 管各时点构图、blocking、pose、服装、可见道具状态。Previous Video不存在，抽帧数=0，未创建 PreviousFrame，也未占用 Picture namespace。

LLM Provider=`{model_log['provider']}`；Model=`{model_log['model']}`；端点=`{model_log['endpoint']}`。复用项目数据库中的当前配置和现有 OpenAI-compatible 请求方式，直接由实验脚本调用，避免 product LLM service 自动写正式 llm_logs。

Thinking / Reasoning：未显式传入，沿用 gateway/provider default；401响应不含可验证推理配置。Temperature=0.7；max_tokens=393216，沿用项目当前配置；response_format=json_object；stream=false；多图数=9。

调用次数=1，retry=0；请求耗时={duration:.3f}s；Token usage=API未返回；响应=`{{"code":"INVALID_API_KEY","message":"Invalid API key"}}`。另一次只读 `/models` 检查同样401，但不计为Optimizer重试。没有反复重试无效凭据。

完整响应：`optimizer/optimizer_raw_response.txt`；错误与计时：`optimizer/call_log.json`；首次失败请求、响应、输入、指令、日志另保存在 `optimizer/attempts/attempt_001/`，后续使用更新配置重试时仍保留。

## C. Optimizer 发现的问题

**没有可用的 Optimizer 输出。** 401发生在认证阶段，无法证明模型接收或分析了9张图片，因此不把人工观察写成模型发现。SPEAKER_BINDING、VISUAL_ATTENTION_CONFLICT、DIALOGUE_ACTION_OVERLAP、ANCHOR_TRANSITION、IDENTITY_AUTHORITY、COSTUME_CONTINUITY、SEMANTIC_OBJECT_LEAKAGE、PROMPT_REDUNDANCY、DURATION_PRESSURE 的 Optimizer findings 全部未获得。

## D. Optimizer 修改内容

**未发生优化。** 无 Before → After；无 Optimized Prompt 长度、duration recommendation 或 timing recommendation。不存在 `optimizer/optimizer_result.json` 或 `optimizer/optimized_h3_prompt.txt`，避免把人为内容冒充真实LLM结果。Raw Prompt保留原文。

## E. Authority Check

`authority_check.json`：status=NOT_RUN，各preserved字段为null，原因是没有优化输出。不是PASS，也不是发现Optimizer violation。

| Check | 结果 |
|---|---|
| Dialogue Event Count | NOT_RUN |
| Dialogue Speaker | NOT_RUN |
| Exact Dialogue | NOT_RUN |
| Picture Binding / 新增 Picture | NOT_RUN |
| Subject Identity / Subject 增删 | NOT_RUN |
| Temporal Anchor Order | NOT_RUN |

`experiment.py authority` 已准备轻量结构检查；只有真实Optimizer返回后才能执行。若检查发现violation，保留真实输出并记录失败，不自动修改Prompt。

## F. ComfyUI 实际执行

ComfyUI=`http://192.168.50.1:8288`，`GET /system_stats` 成功，检查时队列为空。冻结 graph 的所有 class_type 均存在于当前 `GET /object_info`。这些是只读检查，不是实验生成。

| 条件 / 结果 | Baseline（复用真实已完成任务） | Experiment A |
|---|---|---|
| Workflow | Minimax H3 多参考生视频 V20260928 | 预定完全复用Baseline实际graph |
| Prompt | `baseline/raw_h3_prompt.txt` | 未获得 |
| Requested Duration | 13.1s | 预定13.1s |
| Seed | {params['seed']} | 预定相同 |
| Resolution | 864×480 | 预定相同 |
| Generation Time | {generation_seconds:.3f}s（远端history start→success） | 未执行 |
| Output | `output/baseline.mp4` | 不存在 |
| ComfyUI prompt ID | `{task['comfyui_prompt_id']}` | 无 |
| Application task ID | `{task['id']}` | 不创建正式task |
| Success / failure | SUCCESS（真实历史执行） | NOT_SUBMITTED（Optimizer认证失败） |

Baseline原始远端输出：`video/MiniMax_H3_01322_.mp4`。输出SHA-256=`{params['baseline_sha256']}`。原始媒体完整解码成功，并非仅看API success。

现有调用链为 upload（正式服务）→ POST `/prompt`→GET `/history/{{prompt_id}}`→GET `/view`→正式task/Shot写回；实验脚本直接复用已上传的原图和实际graph，仅使用ComfyUI的queue/history/view，省略正式API、任务创建和DB写回。未导入正式生成service。

冻结实验规则：node 138 `value` 唯一生成内容变量；输出node 169的filename_prefix可改为独立实验子目录以隔离输出，该变化不影响生成条件。不改变节点、连接、模型、端口、reference wiring、resolution、seed、duration或sampling。没有有效optimized_prompt，因此尚未形成或发送实验queue request；不把Baseline历史queue当成本轮提交。

Experiment B **未执行**：没有duration recommendation，且Experiment A未完成。未重新编译Dialog/KF timing。

## G. 实际视频结果比较

Optimized视频不存在，无法进行A/B比较。已检查Baseline真实MP4：ffprobe、完整音视频解码、10张关键时点帧、另16张台词handoff帧。证据见 `review/frame_manifest.json`、`review/baseline_handoff_times.json`、`review/video_review.json`、两张contact sheet及独立帧。

| 维度 | Baseline真实观察 | Optimized |
|---|---|---|
| Speaker correctness | NEEDS_MANUAL_REVIEW；D4期间画面是皇帝特写，不能据此判断画外语音是谁 | 无视频 |
| Lip-sync ownership / non-speaker mouth | NEEDS_MANUAL_REVIEW；D5应由皇帝说，但9.55–10.5s右侧骗子2嘴形多次变化，属于可疑迹象 | 无视频 |
| Identity / 人物交换 / 重复人物 | 抽查中4人可辨识，未见明显复制或左右身份交换；连续稳定性NEEDS_MANUAL_REVIEW | 无视频 |
| Costume | 抽查保持皇帝蓝衣红披风、总管深色长衣、左骗子绿色长衣黑帽、右骗子红衣棕帽；全片NEEDS_MANUAL_REVIEW | 无视频 |
| Blocking | 群像帧仍保持骗子1左、骗子2右、皇帝居中坐、总管在阶旁；后段前景明显放大，身体/机位贡献NEEDS_MANUAL_REVIEW | 无视频 |
| Temporal Transition | 从鞠躬到直立及空手展示可见；13s最终空间尺度与Picture 3的群像不同 | 无视频 |
| Camera | **观察到偏离**：7.5–8.85s单人皇帝特写，9.35s后两骗子近景；Raw要求持续群像、不隔离portrait framing | 无视频 |
| Unexpected Object | 抽查空手展示中未见实体布料；全片不存在额外对象仍NEEDS_MANUAL_REVIEW | 无视频 |
| Exact Audio / 抢台词 / Soundscape | NEEDS_MANUAL_REVIEW；音轨可解码，但未可靠转录或听辨 | 无视频 |
| Overall Execution | 已有可观察构图偏离，无法判定Prompt优化的改善或损害 | 无视频 |

这里的mouth-shape迹象不是可靠lip-sync归属结论；静帧和解码成功无法证明exact dialogue或实际speaker。未猜测这些结果，也未只评价美观。

## H. 最终判断

**Optimizer result is inconclusive.** 唯一真实Optimizer请求认证失败，没有优化内容和A视频；无法证明有益或有害。本次仅完成真实数据定位、Baseline冻结、视觉输入准备、真实失败调用、ComfyUI前置验证和Baseline检查。端到端实验尚未完成，不能宣布方案成立。

### 已发现但未修复的原有内容风险

这些是对原文/帧的人工观察，**不是Optimizer输出**：

- **SEMANTIC_OBJECT_LEAKAGE**：Raw KF3文本含“suggesting the support of ornate fabric”，紧接着又说明无实体fabric，可能激活错误对象概念；实际帧抽查未见实体布，尚不能认定确实导致泄漏。
- **PROMPT_REDUNDANCY**：6个Dialogue Event重复整段speaker-only/非speaker限制，多个identity/authority段重复约束；未删除或调整。
- **VISUAL_ATTENTION_CONFLICT**：6–10.8s视觉优先皇帝，而D4 @8.35–9.35s归骗子1；visual attention与speech authority在原Prompt中被明确分开，因此属于执行压力，并非判定canonical错误。Baseline D4区间出现皇帝portrait framing。
- **DURATION_PRESSURE / ANCHOR_TRANSITION**：6段台词、5次speaker切换、各handoff约0.2s、D6在13.0s结束且KF3也是13.0s，Clip于13.1s结束。只记录实际时间结构，未自行延长或重排。
- **物理时长差异**：冻结node 131采用17步长帧对齐，13.1s请求实际为328帧/13.6667s。13.4s抽查中骗子2嘴形仍明显张开，是否尾部额外发声须人工听辨；没有裁剪Baseline或改workflow。

### 阻塞与继续执行

阻塞点是项目当前LLM凭据被本地gateway拒绝，ComfyUI可用。需要在项目设置中更新有效凭据，或指定另一个已配置、支持多图的LLM端点。实验脚本下一次调用会重新只读读取配置，保留attempt_001，不修改Provider系统。

从项目根目录依次运行（每一步确认真实成功后再执行下一步）：

```sh
backend/venv/bin/python -B backend/tests/h3_prompt_optimizer_shot3_c1/experiment.py optimizer
backend/venv/bin/python -B backend/tests/h3_prompt_optimizer_shot3_c1/experiment.py authority
backend/venv/bin/python -B backend/tests/h3_prompt_optimizer_shot3_c1/experiment.py submit
backend/venv/bin/python -B backend/tests/h3_prompt_optimizer_shot3_c1/experiment.py poll
backend/venv/bin/python -B backend/tests/h3_prompt_optimizer_shot3_c1/experiment.py frames
```

`submit`重新检查原始reference bytes，不会覆盖远端图片；只提交一次，之后按保存的prompt_id轮询。若未知提交状态，先恢复已有prompt_id，不能盲目重试。成功后应按真实Optimizer result、Authority和视频重写本报告；`finalize_report.py`仅用于当前认证阻塞状态。

### 隔离检查

`logs/isolation_check.json`：既有tracked与untracked源码内容无改变={not modified}；实验外新增nonignored文件数={len(new_outside)}；9张原图未改变={original_assets_unchanged}；正式Baseline视频未改变={baseline_unchanged}。正式数据库仅以mode=ro读取，不执行写操作；正式API调用=0；正式任务创建=0；本轮ComfyUI生成提交=0。用户此前已有的正式代码改动完整保留。

### 产物索引

- Raw Prompt：`baseline/raw_h3_prompt.txt`
- Baseline信息：`baseline/reference_manifest.json`、`baseline/canonical_dialogue.json`、`baseline/generation_params.json`、`baseline/input_assets.json`、`baseline/workflow_info.json`、`baseline/clip_metadata.json`
- 冻结实际提交图：`baseline/submitted_workflow.json`；真实remote history：`comfyui/baseline_history.json`
- 原始输入副本：`inputs/`；LLM Vision Proxies：`vision_proxy/`
- Optimizer request/response/error：`optimizer/llm_request.json`、`optimizer/optimizer_raw_response.txt`、`optimizer/call_log.json`、`optimizer/attempts/attempt_001/`
- Authority：`authority_check.json`（NOT_RUN）
- Baseline视频：`output/baseline.mp4`
- Experiment A状态：`comfyui/experiment_a_execution.json`（NOT_SUBMITTED）
- 视频观察：`review/video_review.json`、`review/baseline_contact_sheet.jpg`、`review/baseline_handoffs.jpg`
- Optimized Prompt、optimizer_result、A/B视频：**未产生**。
"""
(ROOT / "REPORT.md").write_text(report, encoding="utf-8")
summary = {
    "experiment_directory": str(ROOT), "shot_id": exp.SHOT_ID, "clip_id": f"{exp.SHOT_ID}:clip:1",
    "source_task_id": exp.TASK_ID, "raw_prompt": str(ROOT / "baseline/raw_h3_prompt.txt"),
    "optimized_prompt": None, "optimizer_result": None, "authority_check": str(ROOT / "authority_check.json"),
    "baseline_video": str(ROOT / "output/baseline.mp4"), "optimized_video": None, "experiment_b_video": None,
    "report": str(ROOT / "REPORT.md"), "optimizer_status": "FAILED_HTTP_401_INVALID_API_KEY",
    "comfyui_status": "NOT_SUBMITTED", "conclusion": "Optimizer result is inconclusive",
    "end_to_end_complete": False,
}
dump("experiment_summary.json", summary)
print(json.dumps(summary, ensure_ascii=False, indent=2))
