# 《药》纯器乐背景音乐实验结果（2026-10-25）

目标小说：`cf65a2bd-5a15-4b65-9c94-0a7746642ec7`。本次是独立实验，未修改产品数据库、正式工作流、原视频或产品媒体目录。实验代码见 [README](/Volumes/Data/AI-NovelFlow-V2/backend/experiments/yue2_bgm/README.markdown)、[YuE2 调用脚本](/Volumes/Data/AI-NovelFlow-V2/backend/experiments/yue2_bgm/comfyui_yue2.py)、[时间轴与混音脚本](/Volumes/Data/AI-NovelFlow-V2/backend/experiments/yue2_bgm/experiment.py)；输入和输出见 [实验快照](/Volumes/Data/tmp/yue2_bgm_yao_llm/manifest.json)、[审核状态](/Volumes/Data/tmp/yue2_bgm_yao_llm/vocal_gate_review.json)。

## 配乐区间

LLM 根据小说正文、Shot 描述和对白提出草案；它没有听到实际声轨。六章成片共 586.09 秒，草案仅在 78.60 秒配乐（13.4%）。第 2、5 章全章无音乐，其余未列区间也无音乐。第 1 章只在人物出现前铺氛围，第 3 章在茶客麻木的尾镜使用极轻器乐，第 4 章用于寒冬过渡，第 6 章仅在花环终镜做克制收束。详细情节依据与对白/环境声优先级见 [配乐规划](/Volumes/Data/tmp/yue2_bgm_yao_llm/plan_review.md)。

## 更新后同条件实测

ComfyUI 节点更新并重启后，四段统一使用 T8 源码对应的纯器乐文字条件：`Instrumental music only; no singing, no vocals, no spoken voice, no choir.` 与 `[instrumental]` 标记。YuE2 先自行规划 ABC 乐谱；实验脚本把 Vocal 音符移到 Ins，再截取覆盖目标区间的完整小节。四段截取乐谱的 Vocal 音符均为 **0**。此检查只针对乐谱；生成音频没有通过人工无人声听检。

| 章节 / Shot | 视频配乐时间 | 截谱 Vocal 音符 | 乐谱时长 / 音频时长 | 对使用区间的 ASR 观察 | 状态 | 预览 |
|---|---:|---:|---:|---|---|---|
| 1 / Shot 1–2 | 0.00–13.18 s | 0 | 20.0 / 94.0 s | *music* | 时长异常，待听检 | [试听](/Volumes/Data/tmp/yue2_bgm_yao_llm/audition_cues_unreviewed/yao_llm_c1_1_after_update_first_13.2s.mp3) · [混音](/Volumes/Data/tmp/yue2_bgm_yao_llm/mixes_after_update_unreviewed/chapter_01_bgm_UNREVIEWED.mp4) |
| 3 / Shot 7–7 | 112.50–136.79 s | 0 | 28.8 / 62.0 s | Music | 时长异常，待听检 | [试听](/Volumes/Data/tmp/yue2_bgm_yao_llm/audition_cues_unreviewed/yao_llm_c3_1_after_update_first_24.3s.mp3) · [混音](/Volumes/Data/tmp/yue2_bgm_yao_llm/mixes_after_update_unreviewed/chapter_03_bgm_UNREVIEWED.mp4) |
| 4 / Shot 1–2 | 0.00–22.40 s | 0 | 26.7 / 32.6 s | Zither Harp | 待听检 | [试听](/Volumes/Data/tmp/yue2_bgm_yao_llm/audition_cues_unreviewed/yao_llm_c4_1_after_update_first_22.4s.mp3) · [混音](/Volumes/Data/tmp/yue2_bgm_yao_llm/mixes_after_update_unreviewed/chapter_04_bgm_UNREVIEWED.mp4) |
| 6 / Shot 8–8 | 75.23–93.95 s | 0 | 23.3 / 89.9 s | 反复出现“作词/作曲” | 时长异常，待听检 | [试听](/Volumes/Data/tmp/yue2_bgm_yao_llm/audition_cues_unreviewed/yao_llm_c6_1_after_update_first_18.7s.mp3) · [混音](/Volumes/Data/tmp/yue2_bgm_yao_llm/mixes_after_update_unreviewed/chapter_06_bgm_UNREVIEWED.mp4) |

Whisper 对器乐会出现描述词甚至反复的“作词/作曲”套话，因此其输出只是风险线索，不能判定是否存在真实歌声、哼唱或人声采样。所有四段仍为 `approved_for_bgm=false`。第 1、3、6 章的音频明显长于乐谱，截取时可能打断乐句，暂不视为合格配乐；第 4 章时长较接近，但也要听检。

## 与首轮对照

| 章节 | 首轮音频 | 更新后音频 | 乐谱目标 |
|---|---:|---:|---:|
| 1 | 30.9 s | 94.0 s | 20.0 s |
| 3 | 332.9 s | 62.0 s | 28.8 s |
| 4 | 41.0 s | 32.6 s | 26.7 s |
| 6 | 40.0 s | 89.9 s | 23.3 s |

节点更新与提示条件同时改变，不能把时长差归因于单一因素。首轮候选保留在 [首轮音频目录](/Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_audio_unreviewed)，更新后候选保留在 [复测音频目录](/Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_audio_after_update_unreviewed)。每段的请求、原谱、转谱检查、ComfyUI 历史、seed 与哈希分别位于 [复测任务目录](/Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_jobs_after_update)。

## 混音验证与源码结论

独立混音已按 Cue 时间段截取、淡入淡出并叠加在原声上；第 2、5 章返回 `NO_MUSIC`。四个视频都通过时长、音轨和画面帧数检查，结构化结果见 [混音摘要](/Volumes/Data/tmp/yue2_bgm_yao_llm/mixes_after_update_unreviewed/mix_summary.json)。第 3、6 章的实验音乐平均电平分别比原声低约 35、36 dB，是否过轻、是否反而削弱对白或结尾停顿，只能通过试听确定。

对照 [T8 节点源码](https://github.com/T8mars/Comfyui-YuE2-T8/blob/main/nodes.py)和[纯器乐条件实现](https://github.com/T8mars/Comfyui-YuE2-T8/blob/main/app/yue2_app/core_worker.py)：目前 ComfyUI 的 `YuE2GenerateSong` 节点接受 ABC，但未暴露 `instrumental` 或 `semantic_sampling` 输入；WebUI 的纯器乐开关实际转成上述文本条件，源码也明确说不保证完全无人声。后端可接收 `semantic_sampling`，但本次节点路径不能直接设定生成 token 上限。更新前后的 [节点输入快照](/Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_node_schema_before_update.json)、[更新后快照](/Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_node_schema_after_update.json)对外结构相同；这不能证明内部版本相同。公开源码核对提交为 `0bb6f8461e08f4b5f5ac798bf0beac35f16ef1da`，不是本机安装版本声明。

## 后续准入条件

1. 人工听完整个实际使用区间和混音上下文；任何歌声、哼唱、念白、可辨词语或拟人化人声都退回重生或弃用，不能靠降低音量掩盖。
2. 检查乐句是否在淡出前自然收束，尤其是第 1、3、6 章；评估第 3、6 章是否干脆无配乐更好。
3. 在正式功能中建立“未审核 → 已听检 → 可用”的显式状态，并增加生成长度控制或超长失败规则。当前 `mix` 只生成独立预览，不自动批准音乐。
4. 如将来用于商用，先核对 [YuE2 模型许可](https://github.com/T8mars/Comfyui-YuE2-T8/blob/main/MODEL_LICENSE)；该项目当前说明模型权重为 CC BY-NC 4.0。
