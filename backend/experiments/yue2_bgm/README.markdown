# 《药》YuE2 背景音乐离线实验

这个目录验证“已有章节成片 → 配乐区间草案 → YuE2 生成器乐候选 → 独立混音预览”的链路。`experiment.py` 只读产品 SQLite 和现有 MP4，不调用 AI 服务。经用户追加授权，`llm_plan.py` 可显式调用已配置的 LLM；经后续授权，`comfyui_yue2.py` 可显式调用已配置的 ComfyUI。所有实验输出均在生产媒体目录之外，不修改产品数据库、工作流或原始视频。

## 已知输入与边界

- 目标小说 ID：`cf65a2bd-5a15-4b65-9c94-0a7746642ec7`（《药》）。六章目前各有 `shots_only` 章节成片和原声音轨，第一、三、五章成片含已批准姓名牌。
- `cues_yao.json` 仅是**人工挑选的三段模拟位置**：第一章 Shot 1–2、第四章 Shot 1–2、第六章 Shot 8。其他所有区间保持原声且无配乐。它不代表正式音乐导演判断。
- Cue 以当前已合并成片对应任务的 Shot 顺序和媒体时长定位。若最终章节视频变更，`mix` 会拒绝旧快照并要求重新 `prepare`。当前六章 Shot 累加与成片的残差均小于 0.1 秒；这种近似只适用于本次实验，将来的产品实现应保存合并时的精确片段时间轴。
- 用户提供的 [ComfyUI 清单](/Volumes/win_f/Downloads/ComfyUI_BGM_inventory_20261025.md)确认 YuE2 权重和歌曲工作流存在；四份提供的 YuE2 JSON 没有一份证明可直接输出纯器乐 BGM。本实验另行验证“模型规划 ABC → Vocal 音符转入 Ins → 短段渲染”的路径；即便乐谱没有 Vocal 音符，也要听检生成音频是否有人声残留。

## 准备快照与模拟输出

在仓库根目录运行：

```bash
python3 backend/experiments/yue2_bgm/experiment.py prepare \
  --out /Volumes/Data/tmp/yue2_bgm_yao

python3 backend/experiments/yue2_bgm/experiment.py mock-generate \
  --manifest /Volumes/Data/tmp/yue2_bgm_yao/manifest.json \
  --out /Volumes/Data/tmp/yue2_bgm_yao/mock_audio

python3 backend/experiments/yue2_bgm/experiment.py mix \
  --manifest /Volumes/Data/tmp/yue2_bgm_yao/manifest.json \
  --audio-dir /Volumes/Data/tmp/yue2_bgm_yao/mock_audio \
  --out /Volumes/Data/tmp/yue2_bgm_yao/mixes \
  --chapters 1 --allow-mock
```

`manifest.json` 记录六章当前视频、Shot 边界、配乐和明确的无配乐区间；`yue2_requests.json` 是**模型无关的器乐请求**，供以后人工映射到确认可用的 YuE2 工作流。`mock-generate` 只产生正弦测试音，目录内有 `MOCK_AUDIO_ONLY.json` 标记。输出文件名也包含 `MOCK`，不能作为成品配乐。

## LLM 配乐区间草案

下面的命令才会调用产品配置的 LLM。它提交六章正文、Shot 描述和对白，要求按 Shot 边界提出少量器乐 Cue，并逐字引用章节正文作为依据。输出保留输入快照和原始响应，方便人工复核。模型没有听到实际成片或声轨，因此草案不能直接视为音乐导演定稿。

```bash
backend/venv/bin/python backend/experiments/yue2_bgm/llm_plan.py \
  --manifest /Volumes/Data/tmp/yue2_bgm_yao/manifest.json \
  --out /Volumes/Data/tmp/yue2_bgm_yao/llm_draft
```

审核 `/Volumes/Data/tmp/yue2_bgm_yao/llm_draft/cues_yao_llm.json` 的情节依据、对白/环境声优先级及无音乐区间后，可用它另建快照：

```bash
python3 backend/experiments/yue2_bgm/experiment.py prepare \
  --cue-spec /Volumes/Data/tmp/yue2_bgm_yao/llm_draft/cues_yao_llm.json \
  --out /Volumes/Data/tmp/yue2_bgm_yao_llm
```

上述第二步仍不调用 LLM 或 ComfyUI；它只把已审核的 Cue 映射到当前视频时间轴。若草案里有重叠、不存在的 Shot 或无效增益，`prepare` 会拒绝。

## 调用 ComfyUI 生成 YuE2 器乐候选

只在确认 ComfyUI 可用时显式运行。脚本读取产品数据库中的 ComfyUI 地址，先提交 `YuE2PlanSong` 让模型写谱，使用随实验附带的 [YuE2 官方 Apache 2.0 乐谱工具](/Volumes/Data/AI-NovelFlow-V2/backend/experiments/yue2_bgm/third_party/yue2_score/ORIGIN.txt)把 Vocal 音符转入 Ins，再从模型原谱截取覆盖 Cue 的完整小节，提交 `YuE2GenerateSong` 渲染。当前脚本的风格前缀与 `[instrumental]` 标记对齐 [T8 源码中的纯器乐条件](https://github.com/T8mars/Comfyui-YuE2-T8/blob/main/app/yue2_app/core_worker.py)；实测 ComfyUI 节点没有独立的 `instrumental` 输入，因此实验脚本直接传等价文本条件。保留原谱、转谱检查、请求、ComfyUI history、seed 和音频哈希。队列已有任务时拒绝插队；同名输出存在时拒绝覆盖。

```bash
backend/venv/bin/python backend/experiments/yue2_bgm/comfyui_yue2.py \
  --manifest /Volumes/Data/tmp/yue2_bgm_yao_llm/manifest.json \
  --cue-ids yao_llm_c1_1 yao_llm_c3_1 yao_llm_c4_1 yao_llm_c6_1 \
  --out /Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_jobs \
  --audio-dir /Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_audio_unreviewed
```

音频目录特意命名为 `unreviewed`：程序可以验证格式、时长与声部乐谱，却不能证明音频没有哼唱或叙事对白未受遮盖。模型也可能不遵守提示中的目标秒数；生成结果需足够长，混音时才按 Cue 长度截取。渲染时长超过截取乐谱标称时长的两倍会标记为异常。每个 Cue 会触发两次 ComfyUI 任务，先规划后渲染。实测结果与逐段听检入口见 [实验结果](/Volumes/Data/AI-NovelFlow-V2/backend/experiments/yue2_bgm/RESULTS.markdown)。

## 导入候选音频并混音

在独立目录里为每个 Cue 准备唯一的 `cue_id.wav`、`.flac`、`.mp3` 或 `.m4a`，例如 `yao_c1_predawn.flac`。可用时长至少覆盖 `manifest.json` 中该 Cue 的 `duration_seconds`。脚本会按 Cue 区间截取音频、淡入淡出、降低电平，保留章节视频画面和原声音轨；不会循环短音频、改动原片或写入产品数据库。

```bash
python3 backend/experiments/yue2_bgm/experiment.py mix \
  --manifest /Volumes/Data/tmp/yue2_bgm_yao/manifest.json \
  --audio-dir /Volumes/Data/tmp/yue2_bgm_yao/yue2_instrumental \
  --out /Volumes/Data/tmp/yue2_bgm_yao/mixes \
  --chapters 1 4 6
```

可先把未审核音频混成独立预览，供人工听检；正式采纳前必须确认没有歌声、哼唱或对白，没有把环境声误当音乐，也没有明显截断。脚本不会改写已有 ComfyUI 工作流或产品配置。

```bash
python3 backend/experiments/yue2_bgm/experiment.py mix \
  --manifest /Volumes/Data/tmp/yue2_bgm_yao_llm/manifest.json \
  --audio-dir /Volumes/Data/tmp/yue2_bgm_yao_llm/yue2_audio_unreviewed \
  --out /Volumes/Data/tmp/yue2_bgm_yao_llm/mixes_yue2_unreviewed
```

`mix` 保持原视频帧数，重新编码合成音轨。输入目录名带 `unreviewed` 时，输出文件名和记录明确标记 `UNREVIEWED`，不得当作正式可用音乐。混音增益和淡入淡出是保守实验值，不是最终响度标准。含旁白的第六章 Cue 尤其需要听检人声清晰度。没有 Cue 的章节在 `mix_summary.json` 中指向原片，不制作无意义的副本。
