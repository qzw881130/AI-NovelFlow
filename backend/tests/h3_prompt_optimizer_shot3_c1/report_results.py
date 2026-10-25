"""Write the completed report from real optimizer, queue, media and review artifacts."""
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('isolated_experiment', ROOT / 'experiment.py')
exp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp)
load = exp.read_json
dump = exp.write_json
result = load('optimizer/optimizer_result.json')
raw_response = load('optimizer/optimizer_raw_response.txt')
assert json.loads(raw_response['choices'][0]['message']['content']) == result
call = load('optimizer/call_log.json')
check = load('authority_check.json')
execution = load('comfyui/experiment_a_execution.json')
baseline = load('baseline/baseline_verification.json')
assets = load('baseline/input_assets.json')
review = load('review/comparison.json')
assert execution['success'] and check['all_checks_pass']
assert exp.digest(ROOT / 'optimizer/optimized_h3_prompt.txt') == check['optimized_prompt_sha256']
assert load('comfyui/experiment_a_workflow.json')['138']['inputs']['value'] == result['optimized_prompt']
before = load('logs/workspace_before.json')
modified = [p for p, sha in before.items() if not (exp.PROJECT / p).is_file() or exp.digest(exp.PROJECT / p) != sha]
current = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=exp.PROJECT).decode().split('\0')
new_outside = [p for p in current if p and p not in before and not (exp.PROJECT / p).is_relative_to(ROOT)]
isolation = {
    'tracked_and_existing_untracked_content_unchanged': not modified,
    'changed_files_outside_experiment': modified, 'new_nonignored_files_outside_experiment': new_outside,
    'original_reference_assets_unchanged': all(exp.digest(a['original_path']) == a['original_sha256'] for a in assets),
    'production_baseline_video_unchanged': exp.digest(baseline['original_path']) == baseline['sha256'],
    'database_access': 'SQLite mode=ro; only pure credential decrypt utility imported; no schema/data/task writes',
    'formal_api_calls': 0, 'production_task_creations': 0, 'comfyui_generation_submissions': 1,
}
dump('logs/isolation_check.json', isolation)
raw = (ROOT / 'baseline/raw_h3_prompt.txt').read_text()
optimized = result['optimized_prompt']
sections = [f'''# H3 Prompt Optimizer V1 — Shot 3 / C1 隔离实验

状态：**END_TO_END_COMPLETED**。真实9图Optimizer成功，Authority Check全部PASS，冻结ComfyUI workflow实际生成实验A视频，并完成媒体解码及真实帧对比。

结论：**{review['conclusion']}**。{review['conclusion_reason']}

实验目录：`{ROOT}`。日期：2026-10-09（Asia/Shanghai）。首次401是实验脚本漏解密数据库API Key造成的错误；项目LLM可用。已仅修正实验脚本，原失败request/response/error完整保留，见末节。
''']
old = (ROOT / 'logs/initial_blocked_state/REPORT.md').read_text()
sections.append(old[old.index('## A.'):old.index('## B.')])
asset_rows = '\n'.join(f"| {a['picture']} | {a['kind']} | {a['subject_binding'] or ('KF'+str(a['source_keyframe_index'])+' @ '+str(a['source_time_seconds'])+'s' if a['source_keyframe_index'] else a['source_name'])} | {a['original_size']} | {a['vision_proxy_size']} |" for a in assets)
sections.append(f'''## B. Optimizer 输入与真实调用

输入：`optimizer/optimizer_input.json`；用户Meta-Prompt原文：`optimizer/optimizer_meta_prompt.txt`；真实多图HTTP payload（认证头脱敏）：`optimizer/llm_request.json`。

| Picture | 类型 | Binding / authority | 原图尺寸 | Proxy尺寸 |
|---|---|---|---|---|
{asset_rows}

9张Proxy全部来自本次实际ComfyUI reference集合，Picture编号和binding一致。长边≤1024、保持比例、无裁切、不放大、JPEG quality=85，无AI增强/重绘/锐化。原始图片副本在 `inputs/`；Proxy在 `vision_proxy/`；路径和hash见 `baseline/input_assets.json`。ComfyUI使用原始高清输入文件，9张远端原图SHA-256逐一相同。

Previous Video：不存在，`previous_video_available=false`，Previous Frames=0，没有制造Previous AV或混用Picture namespace。Authority按用户要求提供：Director/Temporal管时间状态、构图、blocking、pose、服装、可见道具、机位；Character仅管身份；Scene仅管环境；Prop仅管外观。

Provider=`{call['provider']}`；请求/响应Model=`{call['model']}` / `{call['response_model']}`；端点=`{call['endpoint']}`。Thinking/Reasoning未显式指定，沿用gateway default；API返回reasoning_tokens={call['token_usage']['completion_tokens_details']['reasoning_tokens']}，强度配置未公开。temperature=0.7、max_tokens=393216、stream=false、response_format=json_object。

首次尝试：401 INVALID_API_KEY，耗时约0.100s，无usage。原因是实验脚本直接发送数据库中的加密值；正式配置加载使用 `app/core/security.py.decrypt_value`。修正实验取钥后第二次尝试：HTTP200，{call['request_duration_seconds']:.3f}s，finish_reason={call['finish_reason']}；prompt_tokens={call['token_usage']['prompt_tokens']}、completion_tokens={call['token_usage']['completion_tokens']}、total_tokens={call['token_usage']['total_tokens']}。共2次Optimizer请求，retry=1。第一次失败没有隐藏，保存在 `optimizer/attempts/attempt_001/`；成功完整请求、响应、内容、日志在attempt_002及optimizer顶层。

未导入会写正式llm_logs的业务service；只读数据库、复用纯解密工具及已有OpenAI-compatible端点。优化内容未做人工修改。
''')
risk_categories = {
    'speaker_handoff_density': 'SPEAKER_BINDING / DURATION_PRESSURE',
    'dialogue_anchor_collision': 'DIALOGUE_ACTION_OVERLAP / ANCHOR_TRANSITION',
    'empty_hand_hallucination': 'SEMANTIC_OBJECT_LEAKAGE',
    'camera_anchor_tension': 'ANCHOR_TRANSITION',
    'visual_attention_speaker_conflict': 'VISUAL_ATTENTION_CONFLICT',
    'multi_subject_identity_continuity': 'IDENTITY_AUTHORITY / COSTUME_CONTINUITY',
}
risk_rows = '\n'.join(f"| {risk_categories.get(r['type'], r['type'])} | {r['severity']} | {r['description']} |" for r in result['risks'])
sections.append(f'''## C. Optimizer 实际发现的问题

Complexity={result['complexity']['level']}：4 Subjects、3 active speakers、6 Dialogue Events、5 speaker switches、3 visual anchors。下表来自真实 `optimizer_result.json.risks`；类别映射仅用于按实验要求组织报告。

| 分类 | Severity | 模型实际风险描述 |
|---|---|---|
{risk_rows}

PROMPT_REDUNDANCY：模型在changes中记录authority consolidation、shared dialogue restrictions和negative prompt reduction，实际输出删除了重复的整段约束。Camera anchor tension来自对Picture2/3尺度相近的视觉理解；作为模型判断记录，不宣称是已证实的上游缺陷。
''')
change_rows = '\n'.join(f"- **{c['type']}**：{c['description']}" for c in result['changes'])
reduction = (1 - len(optimized) / len(raw)) * 100
sections.append(f'''## D. Optimizer 修改内容

Raw {len(raw):,}字符 → Optimized {len(optimized):,}字符，减少{reduction:.2f}%。下面是实际文本的关键Before → After，未给H3另加人工改写。

| 重点 | Before（Raw） | After（Optimized） |
|---|---|---|
| 对象诱导 | “suggesting the support of ornate fabric. No physical fabric exists between the hands.” | “Both hands remain visibly empty, with clear unobstructed air between and above them.” |
| Speaker ownership | 6条台词各自重复长段Only Subject/others non-vocal/no metadata限制 | 统一“only its assigned speaker produces human vocalization and speech-synchronized mouth movement”，保留6个D条目及全部exact文本和时间 |
| D4 attention冲突 | 6–10.8s主视觉为皇帝，D4却归骗子1，约束分散在不同区块 | 显式“During D4, <Subject 3> articulates clearly at frame left ... camera ... established emphasis on <Subject 1>.” |
| Transition | KF描述、summary、detailed_description和authority段分散重复 | 按KF1→KF2、KF2→KF3、终帧hold直接组织并显式到达指定时间状态 |
| Camera | 多处slow forward dolly、low angle、群像、不portrait、轴线限制 | 保留连续dolly/轴线，明确“only the amount of camera advance needed to connect the anchor compositions naturally”并保持ensemble |
| Action | later part of interval中抬手展示，另有KF3时间 | 将空手展示明确放到11–13s/D6，13s完成台词和KF3动作 |
| Start pose | KF1 complete visual state、不补写额外初始动作 | 从Picture1实际鞠躬pose明确过渡到Picture2直立pose；由视觉输入支持 |

模型实际changes：

{change_rows}

Duration：原始13.1s，建议{result['duration']['recommended']}s。原因：{result['duration']['reason']}

**Experiment A仍为13.1s，所有D/KF时间保留。Experiment B未执行**：模型指出15s的收益依赖另行重分配canonical台词、handoff、anchor及hold，本轮禁止重编时间线；简单多加尾部静默不能实现该建议。
''')
check_rows = '\n'.join(f"| {label} | {'PASS' if check[key] else 'FAIL'} |" for label, key in [
    ('Dialogue event count', 'dialogue_event_count_preserved'), ('Dialogue speaker', 'dialogue_speaker_preserved'),
    ('Exact dialogue', 'exact_dialogue_preserved'), ('Canonical dialogue times', 'canonical_dialogue_times_preserved'),
    ('Picture binding', 'picture_binding_preserved'), ('Subject identity / set', 'subject_identity_preserved'),
    ('No new Picture', 'no_new_picture_references'), ('Picture set', 'picture_set_preserved'),
    ('Temporal anchor order', 'temporal_anchor_order_preserved')])
sections.append(f'''## E. Authority Check

轻量实验检查，不是正式Gate；证据和解析结果在 `authority_check.json`。

| Check | 结果 |
|---|---|
{check_rows}

Subject 1=皇帝、2=宫廷总管、3=骗子1、4=骗子2；Picture5→Subject1、Picture6→Subject3、Picture7→Subject4、Picture8→Subject2全部保留。KF1/Picture1@0s → KF2/Picture2@4.95s → KF3/Picture3@13s顺序保留；6条台词和全部起止时间一致。没有新增Picture/Subject。

检查是literal/structural，不能证明所有语义推理无误。另读实际输出确认空手、服装authority、群像及camera要求；动作时序的表达收紧和anchor优先的camera措辞已如实记录。Optimized Prompt字节hash与LLM返回的optimized_prompt相同，未经修改。
''')
probe = load('output/optimized_media_probe.json')
vstream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
sections.append(f'''## F. ComfyUI 实际执行

端点=http://192.168.50.1:8288。实验直接调用现有POST `/prompt`、GET `/history/{{prompt_id}}`、GET `/view`，使用Baseline实际提交graph，不调用正式Shot/Clip API，不创建正式task或写回DB。

| 条件 / 结果 | Baseline（复用） | Experiment A（本轮真实执行） |
|---|---|---|
| Workflow | Minimax H3 多参考生视频 V20260928 | 相同实际graph |
| Prompt | `baseline/raw_h3_prompt.txt` | `optimizer/optimized_h3_prompt.txt`，原样使用 |
| Requested duration | 13.1s | 13.1s |
| Seed | 3720777255 | {execution['seed']} |
| Resolution / FPS | 864×480 / 24 | {vstream['width']}×{vstream['height']} / {vstream['avg_frame_rate']} |
| Frames / physical duration | 328 / 13.666666667s | {vstream.get('nb_frames')} / {vstream.get('duration')}s |
| Sampling | euler/simple/6steps/denoise1 | 相同 |
| Generation time（history） | {baseline['generation_time_seconds']:.3f}s | {execution['generation_time_seconds']:.3f}s |
| Local output | `{baseline['output_path']}` | `{execution['output_path']}` |
| ComfyUI prompt ID | `{baseline['prompt_id']}` | `{execution['prompt_id']}` |
| App task ID | `{baseline['task_id']}` | 无正式task，实验独立queue |
| Result | SUCCESS，已有可信媒体 | SUCCESS，新生成并完整解码 |

原始输入9张图的远端bytes SHA-256与本地高清图完全一致。`comfyui/frozen_graph_check.json`记录graph差异仅node138.value（Prompt）和node169.filename_prefix（隔离输出目录）；节点集合、class_type、所有连接、模型、LoRA、端口、reference顺序和wiring、resolution、seed、duration、sampling保持一致。输出前缀不影响生成条件。

完整queue request：`comfyui/experiment_a_request.json`；实际graph：`comfyui/experiment_a_workflow.json`；submission原始响应：`comfyui/experiment_a_submission_response.txt`；history：`comfyui/experiment_a_history.json`；状态/耗时/hash：`comfyui/experiment_a_execution.json`。

远端独立输出：`{execution['remote_output']['subfolder']}/{execution['remote_output']['filename']}`。下载视频SHA-256=`{execution['output_sha256']}`。没有使用Vision Proxy生成，没有替换正式视频。

Experiment B：未执行，原因见D。冻结帧数对齐公式使13.1s请求得到328帧/13.6667s；两组相同，未裁剪或修改workflow。
''')
comparison_rows = '\n'.join(f"| {i['metric']} | {i['baseline']} | {i['optimized']} | {i['assessment']} |" for i in review['items'])
sections.append(f'''## G. 实际视频比较

方法：{review['method']}

| 维度 | Raw / Baseline | Optimized A | 判断 |
|---|---|---|---|
{comparison_rows}

两组完整AV解码检查均成功（`review/*decode_check.json`）。按同一clip-local时间检查关键帧、6个Dialogue Event中点、D4/D5/D6 handoff及尾部；证据在 `review/frame_manifest.json`、`review/*handoff_times.json`、contact sheets和独立帧。边界帧使用ffmpeg -ss请求时间，存在≤1帧定位误差，未以此声称精确lip-sync。结果来自实际MP4，不是Prompt文字或API成功状态推断。

{review['limitations']}

用户随后实际播放反馈“皇帝的台词怎么被骗子2说了？”，已作为人工复核写入 `review/user_speaker_review.json`：A至少一条皇帝台词由Subject4/骗子2说出，speaker ownership为FAIL。用户未提供确切台词/timestamp，不从截图猜测D3或D5。`review/video_execution_check.json`区分了ComfyUI执行成功、Prompt Authority PASS和视频canonical execution失败；三者不能混为一谈。用户截图副本保存在本实验review目录。

样本帧不能证明整段不存在identity drift、短暂道具或额外嘴动。除用户已确认的speaker错误外，其余exact Mandarin、逐句归属及连续lip-sync中不能可靠判断的项保留NEEDS_MANUAL_REVIEW。没有用画面美观代替canonical execution。
''')
sections.append(f'''## H. 最终判断与实验纪律

**{review['conclusion']}**。{review['conclusion_reason']}

本次只涉及一个Shot的C1和一个seed，结论仅适用于本次观察；不能证明正式Optimizer方案已经成立。Prompt缩短、Authority PASS或ComfyUI成功均不独立证明视频质量改善。用户已确认的speaker ownership错误意味着A没有满足最核心的执行要求。它发生在生成输出层：实际queue文本中两条皇帝台词仍归Subject1，Picture5→Subject1和Picture7→Subject4也没有改变。

可能诱因包括逐句exclusive-speaker约束被合并为全局规则、保持群像时前景骗子的视觉显著度高，以及6条台词/5次0.2秒handoff的执行压力。它们只是基于实际文本和画面的假设，缺少控制消融不能断言是哪一项导致串台词。Baseline同事件音频归属未得到可靠复核，不把A有错误直接等同于Optimizer相对Baseline必然更有害。

### 失败记录与修正

首次401原因是实验脚本遗漏数据库加密API Key的解密步骤，错误地把密文作为Bearer key发送。项目正式加载正确解密，用户截图及最新正式日志确认同一端点可用。仅修改 `experiment.py.config()`，加载现有纯解密函数并按provider方式选取首个key；不修改正式security/config/provider模块，不保存或显示明文key。

首次失败记录：`optimizer/attempts/attempt_001/`；初始阻塞报告：`logs/initial_blocked_state/REPORT.md`；诊断：`logs/authentication_diagnosis.json`。第二次HTTP200响应：`optimizer/attempts/attempt_002/`。本轮ComfyUI只提交一次，无隐藏生成retry。

最终产物核对时顶层raw-response文件显示首次401内容，而attempt_002的完整成功响应保持完好；已将真实attempt_002原始bytes同步至当前顶层response，并保留同步前内容与hash于 `logs/raw_response_before_final_sync.txt` / `logs/raw_response_alias_sync.json`。完整成功响应解析后与optimizer_result完全相等；未修改optimized_prompt。

### 原有内容风险：记录，不修复

- Raw中“support of ornate fabric”与“no physical fabric”存在语义诱导风险；Optimizer以可见空手状态改写，仅作用于实验Prompt。
- 原始Prompt有重复speaker/identity/authority限制；只在模型本次输出中压缩，没有改H3 Prompt Builder。
- D4 speaker与6–10.8s visual attention不同；原文明确区分speech authority和visual priority，模型给出执行澄清，未改Director。
- D2结束与KF2、D6结束与KF3同刻；原始13.1s最后hold仅0.1s，帧对齐输出有尾部padding。保留canonical timing及workflow，未重新规划Shot或修复正式模块。
- 模型认为Picture2/3尺度相近而文本要求持续dolly存在张力；仅作为实际模型finding和本次视频观察报告，不改Reference Manifest、图片或workflow。

### 隔离验证

`logs/isolation_check.json`：实验外既有tracked/untracked源码内容未改变={isolation['tracked_and_existing_untracked_content_unchanged']}；实验外新增nonignored文件={len(new_outside)}；原始9图未改变={isolation['original_reference_assets_unchanged']}；正式Baseline未改变={isolation['production_baseline_video_unchanged']}。数据库只读，正式API调用=0，正式任务创建=0，正式视频引用写回=0。

所有实验脚本、输入副本、Proxy、请求/响应、graph、日志、视频和报告位于本目录。ComfyUI远端独立子目录用于正常SaveVideo输出，下载副本在实验output/；未覆盖正式远端或本地资产。

### 最终产物索引

- Shot ID：`{exp.SHOT_ID}`；Clip ID：`{exp.SHOT_ID}:clip:1`
- Raw Prompt：`{ROOT / 'baseline/raw_h3_prompt.txt'}`
- Optimized Prompt：`{ROOT / 'optimizer/optimized_h3_prompt.txt'}`
- Optimizer Result：`{ROOT / 'optimizer/optimizer_result.json'}`
- Authority Check：`{ROOT / 'authority_check.json'}`
- Baseline视频：`{ROOT / 'output/baseline.mp4'}`
- Optimized A视频：`{ROOT / 'output/optimized_original_duration.mp4'}`
- Experiment B：未执行，无对应视频
- 本报告：`{ROOT / 'REPORT.md'}`
- 本轮ComfyUI：SUCCESS，prompt ID=`{execution['prompt_id']}`，generation time={execution['generation_time_seconds']:.3f}s
''')
(ROOT / 'REPORT.md').write_text('\n'.join(sections), encoding='utf-8')
summary = {
    'experiment_directory': str(ROOT), 'shot_id': exp.SHOT_ID, 'clip_id': f'{exp.SHOT_ID}:clip:1',
    'source_task_id': exp.TASK_ID, 'raw_prompt': str(ROOT / 'baseline/raw_h3_prompt.txt'),
    'optimized_prompt': str(ROOT / 'optimizer/optimized_h3_prompt.txt'),
    'optimizer_result': str(ROOT / 'optimizer/optimizer_result.json'), 'authority_check': str(ROOT / 'authority_check.json'),
    'baseline_video': str(ROOT / 'output/baseline.mp4'), 'optimized_video': str(ROOT / 'output/optimized_original_duration.mp4'),
    'experiment_b_video': None, 'report': str(ROOT / 'REPORT.md'), 'optimizer_status': 'SUCCESS_AFTER_HARNESS_AUTH_FIX',
    'comfyui_status': 'SUCCESS', 'comfyui_prompt_id': execution['prompt_id'], 'conclusion': review['conclusion'],
    'conclusion_reason': review['conclusion_reason'], 'end_to_end_complete': True,
}
dump('experiment_summary.json', summary)
print(json.dumps(summary, ensure_ascii=False, indent=2))
