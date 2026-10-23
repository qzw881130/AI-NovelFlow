# ComfyUI 工作流依赖

本清单依据 2026-10-23 的工作流、ComfyUI 节点注册信息和本机模型盘点整理，适用于盘点中的 38 份图片工作流及 3 份 MiniMax H3 视频工作流。它是环境快照，不能代替所选工作流的实际节点与模型检查；仓库里的其他旧版、音频及放大工作流可能有额外依赖。

模型和插件路径均相对于 ComfyUI 根目录。按要启用的工作流安装对应依赖，无需下载表中所有备用或未启用模板的模型。模型与节点资源：[夸克网盘](https://pan.quark.cn/s/2a630b7755ed)。

## 工作流与模型家族

- **角色、场景、道具**：Moss Image T2I；角色预设支持四视图。
- **分镜、关键帧和图片编辑**：Qwen Image 2.1；包含 Turbo、PE 提示词重写、单图与多图编辑工作流。PE 编辑分支使用本地 GGUF 与视觉投影模型。
- **视频**：MiniMax H3 多参考图生视频、视频续生成和时序续生成；盘点的三份视频图包含第二遍采样与 3D latent 放大。

系统预设文件位于 `backend/workflows/`；具体默认注册和节点映射见 `backend/app/constants/workflow.py`。用户可以在系统设置中上传、导入/导出和切换自定义工作流。同一类型可有多个预设，当前启用项取决于数据库配置。

## 盘点环境中的启用工作流

以下为 2026-10-23 的数据库选择，其他部署可切换同类型工作流。

| 编号 | 用途 | 项目工作流名称 |
| --- | --- | --- |
| I01 | character | moss_image_t2i【四视图】API V20261020 |
| I02 | keyframe_image | Qwen Image 2.1 Turbo 关键帧生图 V20261018 |
| I03 | multi_image_edit | Qwen image 2.1图片编辑 (任意数量参考图) API V20260926.json |
| I04 | prop | image_moss_image_t2i（道具）API V20261020 |
| I05 | scene | image_moss_image_t2i（场景）API V20261020 |
| I06 | shot | Qwen image 2.1图片编辑 (角色+场景+道具) PE API V20260922 |
| I07 | shot_character_scene | Qwen image 2.1图片编辑 (角色+场景) PE API V20260922 |
| I08 | shot_scene | Qwen image 2.1图片编辑 (场景) PE API V20290922 |
| I09 | shot_scene_prop | Qwen image 2.1图片编辑 (场景+道具) PE API V20260922 |
| I10 | single_image_edit | Qwen image 2.1图片编辑 (单图编辑) PE API V20260922 |
| V01 | TEMPORAL_EXTEND | NovelFlow_H3_AV_Extend_TemporalAnchor_Test_2Pass_3D_Upscaler_V1 API V20261021 |
| V02 | VIDEO_CONTINUATION | NovelFlow_H3_AV_Extend_Minimal_2Pass_3D_Upscaler_V1 API V20261021 |
| V03 | multi_reference_video | NovelFlow_H3_Ref2VA_2Pass_3D_Upscaler_V1 API V20261021 |

## 模型文件

盘点共 22 个模型文件，包括启用分支引用、仅旧/未启用模板引用及备用字段。下表的状态与引用来自盘点时的工作流配置，不表示每次运行都加载该文件。

| 类别 | 用途 | ComfyUI 根目录相对路径 | 盘点时的使用状态 |
| --- | --- | --- | --- |
| 生图专用 | 提示词优化 GGUF（编辑） | `models/LLM/qwenimage-pe/Qwen-Image-2.1-PE-I2I.Q4_K_M.gguf` | 当前模板引用 |
| 生图专用 | 提示词优化视觉投影模型 | `models/LLM/qwenimage-pe/Qwen-Image-2.1-PE-I2I.mmproj-bf16.gguf` | 当前模板引用 |
| 生图专用 | 提示词优化 GGUF（文生图） | `models/LLM/qwenimage-pe/Qwen-Image-2.1-PE-T2I.Q4_K_M.gguf` | 仅未启用模板引用 |
| 生图专用 | VAE | `models/vae/flux2-vae.safetensors` | 当前模板引用 |
| 生视频专用 | VAE | `models/vae/minimax_h3_audio_vae_fp32.safetensors` | 当前模板引用 |
| 生视频专用 | LoRA | `models/loras/minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors` | 当前模板引用 |
| 生视频专用 | LoRA | `models/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | 当前模板引用 |
| 生视频专用 | 3D Latent Upscaler | `models/latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16.safetensors` | 当前模板引用 |
| 生视频专用 | 扩散主模型 | `models/diffusion_models/minimax_h3_ref2va_int8_convrot.safetensors` | 当前模板引用 |
| 生视频专用 | 扩散主模型 | `models/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 当前模板引用 |
| 生视频专用 | VAE | `models/vae/minimax_h3_video_vae_fp16.safetensors` | 当前模板引用 |
| 生视频专用 | VAE | `models/vae/minimax_h3_video_vae_int8_convrot.safetensors` | 当前模板引用 |
| 生图专用 | 扩散主模型 | `models/diffusion_models/moss_image_sft_int8_convrot.safetensors` | 当前模板引用 |
| 生图专用 | 提示词优化 GGUF（文生图） | `models/LLM/qwenimage-pe/pe_t2i_heretic-Q4_K_M.gguf` | 当前模板仅备用字段 |
| 生图专用 | 文本/视觉编码器 | `models/text_encoders/qwen3.5_9b_int8_convrot.safetensors` | 当前模板引用 |
| 生图专用 | 文本/视觉编码器 | `models/clip/qwen3.5_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | 仅未启用模板引用 |
| 生图专用 | 文本/视觉编码器 | `models/clip/qwen3.5_qwen_image_2.1_pe_t2i.int8_convrot.safetensors` | 仅未启用模板引用 |
| 生视频专用 | 文本/视觉编码器 | `models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | 当前模板引用 |
| 生图专用 | 文本/视觉编码器 | `models/text_encoders/qwen3vl_8b_int8_convrot.safetensors` | 当前模板引用 |
| 生图专用 | 扩散主模型 | `models/diffusion_models/qwen_image_2.1_int8_convrot.safetensors` | 当前模板引用 |
| 生图专用 | LoRA | `models/loras/qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors` | 当前模板引用 |
| 生图专用 | VAE | `models/vae/qwen_image_2.1_vae_bf16.safetensors` | 当前模板引用 |

## 插件与节点来源

盘点识别出 ComfyUI 核心及 12 个自定义节点仓库。插件目录名和版本以各工作流实际环境为准。

| 类别 | 插件/核心 | 根目录相对位置 | 代表节点 |
| --- | --- | --- | --- |
| 生视频专用 | [ComfyLiterals](https://github.com/M1kep/ComfyLiterals) | `custom_nodes/ComfyLiterals` | `Int` |
| 公共 | [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | `.` | `BasicGuider`, `BasicScheduler` 等 |
| 生视频专用 | [ComfyUI-FeiHou-Toolbox](https://github.com/FX-FeiHou/ComfyUI-FeiHou-Toolbox) | `custom_nodes/ComfyUI-FeiHou-Toolbox` | `VideoCombineV2` |
| 生视频专用 | [ComfyUI-H3-Motion-Context-MultiRef](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef) | `custom_nodes/ComfyUI-H3-Motion-Context-MultiRef` | `MiniMaxH3AVSourceAudioModeParam`, `MiniMaxH3AVStartModeParam` 等 |
| 生视频专用 | [ComfyUI-MiniMaxH3-Context-Loop](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Context-Loop) | `custom_nodes/ComfyUI-MiniMaxH3-Context-Loop` | `MiniMaxH3ChainPass2Prepare` |
| 生视频专用 | [ComfyUI-MiniMaxH3_LatentUpscaler](https://github.com/Tr1dae/ComfyUI-MiniMaxH3_LatentUpscaler) | `custom_nodes/ComfyUI-MiniMaxH3_LatentUpscaler` | `MiniMaxH3Pass2StaggeredScheduler` |
| 生图专用 | [ComfyUI-utils-nodes](https://github.com/zhangp365/ComfyUI-utils-nodes) | `custom_nodes/ComfyUI-utils-nodes` | `ConcatTextOfUtils` |
| 公共 | [ComfyUI_Comfyroll_CustomNodes](https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes) | `custom_nodes/ComfyUI_Comfyroll_CustomNodes` | `CR Prompt Text` |
| 生图专用 | [Comfyui-Qwen-Image-Prompt-Rewrite-T8](https://github.com/T8mars/Comfyui-Qwen-Image-Prompt-Rewrite-T8) | `custom_nodes/Comfyui-Qwen-Image-Prompt-Rewrite-T8` | `QwenPERewriteT8` |
| 生视频专用 | [Comfyui_Minimax_h3_latent_Upscaler](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler) | `custom_nodes/Comfyui_Minimax_h3_latent_Upscaler` | `MinimaxH3LatentUpscaler3D` |
| 公共 | [comfyui-easy-use](https://github.com/yolain/ComfyUI-Easy-Use) | `custom_nodes/comfyui-easy-use` | `easy float`, `easy int` 等 |
| 生视频专用 | [comfyui-kjnodes](https://github.com/kijai/ComfyUI-KJNodes) | `custom_nodes/comfyui-kjnodes` | `MiniMaxH3MemoryEfficientSageAttentionPatch`, `ModelPreviewOverrideKJ` 等 |
| 生视频专用 | [comfyui-videohelpersuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `custom_nodes/comfyui-videohelpersuite` | `VHS_LoadVideoFFmpeg` |

## 部署时需要核对

- Qwen PE 编辑图的 `vision_model=Auto` 会配套加载 `Qwen-Image-2.1-PE-I2I.mmproj-bf16.gguf`；仅看到 GGUF 主文件并不足够。
- 三份 H3 视频图使用 `MiniMaxH3Pass2StaggeredScheduler` 和 `MinimaxH3LatentUpscaler3D`，分别来自两个不同插件，均需保留。
- H3 续生成图的节点会间接调用 VideoHelperSuite 的视频合并能力，因此即使 API 图里没有直接出现 `VHS_VideoCombine`，仍需安装该插件。
- 视频读取和编码还需要 FFmpeg/ffprobe。ConvRot 权重需要能读取该格式的 ComfyUI 运行环境；盘点只记录了当时本机可用的环境，不保证任意版本兼容。
- Qwen PE 本地提示词重写需要可用的 llama.cpp 运行时；运行时的安装方式由部署环境决定。

本表由用户提供的 `NovelFlow_Workflow_Dependencies` 盘点资料整理。请以实际启用工作流中的模型文件名、节点类型和当前插件版本为最终依据。
