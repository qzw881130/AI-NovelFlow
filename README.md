# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI 驱动的小说转视频平台

## 项目概述

NovelFlow 是一个将小说自动转换为视频的 AI 平台。

**核心工作流程：**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│   小说   │ → │ AI解析角色 │ → │ AI解析场景 │ → │ 生成角色图 │ → │ 生成场景图 │
└─────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                            ↓
┌───────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  合并视频  │ ← │ 生成分镜转场  │ ← │ 生成分镜视频  │ ← │ 生成分镜图片  │
└───────────┘    └───────────────┘    └───────────────┘    └───────┬───────┘
                                                                    ↑
                              ┌───────────────┐    ┌───────────┐    │
                              │ 生成合并角色图 │ ← │ JSON结构  │ ← ┘
                              └───────────────┘    └───────────┘
                                                              ↑
                                              ┌───────────┐    │
                                              │ 编辑章节  │ ← ┘
                                              │ AI拆分分镜│
                                              └───────────┘
```

**详细步骤：**
1. **导入小说** - 新建或导入小说文本（支持TXT、EPUB格式）
2. **AI解析角色** - 自动提取角色信息（名称、描述、外貌特征）
3. **AI解析场景** - 自动提取场景信息（场景名称、环境描述）
4. **生成角色图** - 为每个角色生成 AI 人设图
5. **生成场景图** - 为每个场景生成参考图（可选）
6. **编辑章节 / AI拆分分镜** - 编辑章节内容，AI自动拆分为分镜；编辑时支持增量更新解析角色和场景
7. **JSON结构** - 生成分镜数据（角色、场景、镜头描述）
8. **生成合并角色图** - 将多角色合并为参考图（用于分镜生成）
9. **生成分镜图片** - 根据分镜描述生成场景图片
10. **生成分镜视频** - 将分镜图片转换为视频片段
11. **生成分镜转场视频** - 在分镜间生成过渡视频（可选）
12. **合并视频** - 将所有片段合成为完整视频

**主要特性：**
- 支持章回体小说解析
- 角色一致性保持（角色形象在多场景中保持一致）
- 场景一致性保持（场景环境在多镜头中保持一致）
- 自动分镜生成和视频合成

## 视频介绍

### Bilibili

📺 <a href="https://www.bilibili.com/video/BV1VdZbBDEXF" target="_blank">AI-NovelFlow 小说转视频平台介绍</a>

📺 <a href="https://www.bilibili.com/video/BV1rufEBKEjV" target="_blank">如何在我们开源项目里接入商用API</a>

📺 <a href="https://www.bilibili.com/video/BV1G9ZfBeEj6" target="_blank">Windows下如何安装我们的开源项目</a>

### YouTube

📺 <a href="https://www.youtube.com/watch?v=IlMbeDme2F8" target="_blank">AI-NovelFlow 小说转视频平台介绍</a>

📺 <a href="https://www.youtube.com/watch?v=whskvmdN6Qo" target="_blank">如何在我们开源项目里接入商用API</a>

📺 <a href="https://www.youtube.com/watch?v=DybveicQ9eQ" target="_blank">Windows下如何安装我们的开源项目</a>

## 社区交流

| Telegram 交流群 | QQ 群 |
|:---:|:---:|
| <a href="https://t.me/AI_NovelFlow" target="_blank">@AI_NovelFlow</a> | 1083469624 |
| <img src="docs/telegram_group.png" width="200" alt="Telegram群二维码"> | <img src="docs/qq_group.png" width="200" alt="QQ群二维码"> |

## 技术栈

- **前端**: React + TypeScript + Tailwind CSS + Vite
- **状态管理**: Zustand（全局状态 + 国际化/时区状态）
- **后端**: FastAPI + SQLAlchemy + SQLite
- **AI**: DeepSeek API / OpenAI API / Gemini API + ComfyUI
- **视频生成**: LTX-2 视频生成模型
- **国际化**: 自定义 i18n 实现（5 语言支持）

## 主要功能

- **小说管理**: 支持新建、编辑、删除小说，自动章回体解析
- **角色库**: AI 自动解析角色，支持角色形象生成和一致性保持
- **场景库**: AI 自动解析场景，支持场景参考图生成和环境设定
- **分镜生成**: AI 自动拆分章节为分镜，支持批量生成图片和视频
- **转场视频**: 支持生成镜头转场、光线转场、遮挡转场视频
- **视频合成**: 支持将分镜视频合并为完整章节视频，自动插入转场
- **工作流管理**: 支持自定义 ComfyUI 工作流，节点映射配置
- **任务队列**: 后台异步任务处理，支持任务状态实时监控
- **预设测试用例**: 内置《小马过河》《小红帽》《皇帝的新装》等测试用例
- **多语言支持**: 支持简体中文、繁体中文、英文、日文、韩文界面
- **时区支持**: 用户可自定义时区，所有时间显示按指定时区转换

## 项目结构

```
AI-NovelFlow/
├── backend/              # FastAPI 后端
│   ├── app/
│   │   ├── api/         # API 路由
│   │   ├── core/        # 核心配置
│   │   ├── models/      # 数据库模型
│   │   ├── repositories/ # 数据仓库层
│   │   ├── schemas/     # Pydantic 模型
│   │   ├── services/    # 业务逻辑（LLM、ComfyUI）
│   │   └── utils/       # 工具函数
│   ├── migrations/      # 数据库迁移脚本
│   ├── prompt_templates/ # 提示词模板文件
│   ├── workflows/       # ComfyUI 工作流配置
│   ├── user_story/      # 生成的图片/视频存储目录
│   ├── user_workflows/  # 用户自定义工作流
│   └── main.py
├── frontend/            # React 前端
│   └── my-app/
│       ├── src/
│       │   ├── components/  # 组件
│       │   ├── i18n/        # 国际化翻译文件
│       │   ├── pages/       # 页面
│       │   ├── stores/      # 状态管理
│       │   └── types/       # TypeScript 类型
│       └── package.json
├── windows_gpu_monitor/ # Windows GPU 监控服务（可选）
│   ├── gpu_monitor.py   # GPU 监控服务
│   ├── requirements.txt # 依赖
│   └── start.bat        # Windows 启动脚本
└── README.md
```

## 安装部署

### 环境要求

- **Python**: 3.10+
- **Node.js**: 18+
- **ComfyUI**: 已安装并运行（用于图像/视频生成）

### 1. macOS / Linux 安装

#### 后端部署

```bash
# 1. 进入后端目录
cd backend

# 2. 创建虚拟环境
python3 -m venv venv

# 3. 激活虚拟环境
source venv/bin/activate

# 4. 安装依赖
pip install -r requirements.txt

# 5. 启动后端服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端服务将在 http://localhost:8000 运行

#### 前端部署

```bash
# 1. 进入前端目录
cd frontend/my-app

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
```

前端服务将在 http://localhost:5173 运行

---

### 2. Windows 安装

#### 后端部署

**使用 CMD (命令提示符):**

```cmd
:: 1. 进入后端目录
cd backend

:: 2. 创建虚拟环境
python -m venv venv

:: 3. 激活虚拟环境
venv\Scripts\activate.bat

:: 4. 安装依赖
pip install -r requirements.txt

:: 5. 启动后端服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**使用 PowerShell:**

```powershell
# 1. 进入后端目录
cd backend

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活虚拟环境（如果提示执行策略错误，请先运行：Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser）
venv\Scripts\Activate.ps1

# 4. 安装依赖
pip install -r requirements.txt

# 5. 启动后端服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**使用 Git Bash:**

```bash
# 1. 进入后端目录
cd backend

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活虚拟环境
source venv/Scripts/activate

# 4. 安装依赖
pip install -r requirements.txt

# 5. 启动后端服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端服务将在 http://localhost:8000 运行

#### 前端部署

```bash
# 1. 进入前端目录
cd frontend/my-app

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
```

前端服务将在 http://localhost:5173 运行

> **Windows 防火墙提示**
> 
> 如果其他设备无法访问前端服务（如局域网内其他电脑无法打开页面），需要放行 5173 端口：
> 
> **CMD (管理员身份):**
> ```cmd
> netsh advfirewall firewall add rule name="AI-NovelFlow Frontend" dir=in action=allow protocol=tcp localport=5173
> ```
> 
> **PowerShell (管理员身份):**
> ```powershell
> New-NetFirewallRule -DisplayName "AI-NovelFlow Frontend" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow
> ```

---

### 3. Docker 部署（可选）

```bash
# 构建镜像
docker build -t ai-novelflow .

# 运行容器
docker run -p 8000:8000 -p 5173:5173 ai-novelflow
```

---

### 4. 更新升级

#### 后端更新

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate

# 拉取最新代码
git pull

# 更新依赖
pip install -r requirements.txt

# 重启服务
```

#### 前端更新

```bash
cd frontend/my-app

# 拉取最新代码
git pull

# 更新依赖
npm install

# 重新启动
npm run dev
```

## API 文档

启动后端后访问: http://localhost:8000/docs

## 配置说明

### 1. LLM API 配置

支持多种 LLM 提供商：
- **DeepSeek**（默认）: https://api.deepseek.com
- **OpenAI**: https://api.openai.com
- **Gemini**: https://generativelanguage.googleapis.com
- **Anthropic**: https://api.anthropic.com
- **Azure OpenAI**: 自定义 Azure 端点

在【系统配置】页面设置 API Key 和代理（如需）。

### 2. ComfyUI 配置

- **ComfyUI 地址**: 默认 http://localhost:8188
- **工作流配置**: 支持上传自定义工作流，需配置节点映射
  - 人设生成: 提示词节点 + 图片保存节点
  - 场景生成: 提示词节点 + 图片保存节点 + 宽高节点
  - 分镜生图: 提示词节点 + 图片保存节点 + 宽高节点
  - 分镜生视频: 提示词节点 + 视频保存节点 + 参考图节点
  - 转场视频: 首帧图节点 + 尾帧图节点 + 视频保存节点

#### 2.1 模型文件

目录以 `ComfyUI/models/...` 为基准；如果你用的是 ComfyUI-Manager，一般也按这些目录扫描。

| 模型文件名 | 类型 | 主要用途 | 出现的工作流 | 建议目录 |
|-----------|------|---------|-------------|---------|
| `ltx-2-19b-dev-fp8.safetensors` | checkpoint / 主模型 | LTX2 转场（遮挡/光线/镜头）视频生成 | LTX2 遮挡转场视频 / 光线转场视频 / 镜头转场视频 | `models/checkpoints/` |
| `ltx-2-19b-distilled-fp8.safetensors` | checkpoint / 主模型 | LTX2 视频生成（直接版/扩写版） | LTX2 视频生成-直接版 / 扩写版 | `models/checkpoints/` |
| `gemma_3_12B_it_fp8_e4m3fn.safetensors` | text encoder (LTX 文本编码器) | LTX2 文本编码 | 所有 LTX2 类工作流都会用（转场/视频生成） | `models/text_encoders/` |
| `ltx-2-19b-distilled-lora-384.safetensors` | LoRA | LTX2 蒸馏 LoRA（提升/匹配蒸馏流程） | 主要在转场类工作流出现 | `models/loras/` |
| `ltx-2-19b-lora-camera-control-dolly-left.safetensors` | LoRA | LTX2 镜头控制 (dolly-left) | 主要在转场类工作流出现 | `models/loras/` |
| `ltx-2-spatial-upscaler-x2-1.0.safetensors` | upscale model (latent upscaler) | LTX2 latent 空间放大 x2 | 主要在转场类工作流出现 | `models/upscale_models/` |
| `ae.safetensors` | VAE / AE | 在 Z-image-turbo 及部分默认人设流程里作为 VAE/AE | Z-image-turbo 单图生成 / 系统默认-人设生成 | `models/vae/` |
| `flux-2-klein-9b.safetensors` | UNet | Flux2-Klein 分镜生图 UNet | Flux2-Klein-9B 分镜生图 / 系统默认-人设生成 | `models/unet/` |
| `flux2-vae.safetensors` | VAE | Flux2 的 VAE | Flux2-Klein-9B 分镜生图 / 系统默认-人设生成 | `models/vae/` |
| `qwen_3_8b.safetensors` | text encoder | Flux2 文本编码 | Flux2-Klein-9B 分镜生图 / 系统默认-人设生成 | `models/clip/` |
| `z_image_turbo_bf16.safetensors` | UNet | Z-image-turbo 单图生成 UNet | Z-image-turbo 单图生成 / 系统默认-人设生成 | `models/unet/` |
| `qwen_3_4b.safetensors` | text encoder | Z-image-turbo 文本编码 | Z-image-turbo 单图生成 / 系统默认-人设生成 | `models/clip/` |

#### 2.2 第三方节点包

| 第三方节点包 | GitHub 仓库 | 工作流中命中的节点 class_type |
|-------------|------------|------------------------------|
| **LTXVideo / LTXV** | [Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) | `LTXAVTextEncoderLoader`, `LTXVScheduler`, `LTXV*`, `LTXAV*`, `Painter*` |
| **VideoHelperSuite / VHS** | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `VHS_VideoCombine` |
| **Easy-Use** | [yolain/ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | `easy int`, `easy cleanGpuUsed`, `easy showAnything` |
| **LayerStyle / LayerUtility** | [chflame163/ComfyUI_LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle) | `LayerUtility: ImageScaleByAspectRatio V2` |
| **Comfyroll** | [Suzie1/ComfyUI_Comfyroll_CustomNodes](https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes) | `CR Prompt Text`, `CR Text` |
| **FizzNodes / ConcatStringSingle** | [FizzleDorf/ComfyUI_FizzNodes](https://github.com/FizzleDorf/ComfyUI_FizzNodes) | `ConcatStringSingle` |
| **comfyui-various / JWInteger** | [jamesWalker55/comfyui-various](https://github.com/jamesWalker55/comfyui-various) | `JWInteger` |
| **ReservedVRAM** | [Windecay/ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | `ReservedVRAMSetter` |
| **Qwen3-VL-Instruct / Qwen3_VQA** | [luvenisSapiens/ComfyUI_Qwen3-VL-Instruct](https://github.com/luvenisSapiens/ComfyUI_Qwen3-VL-Instruct) | `Qwen3_VQA` |
| **Comfyui-zhenzhen** | [T8mars/Comfyui-zhenzhen](https://github.com/T8mars/Comfyui-zhenzhen) | `Zhenzhen_nano_banana`, `Zhenzhen API Settings` |

### 3. Windows GPU 监控（可选）

如果 ComfyUI 运行在远程 Windows 服务器上，可以部署 `windows_gpu_monitor` 服务来获取实时 GPU 状态。

**功能**：
- 实时监控 GPU 使用率、温度、显存占用
- 监控内存使用情况
- 显示队列任务数量

**部署步骤**：

```bash
cd windows_gpu_monitor

# 安装依赖
pip install -r requirements.txt

# 启动服务
start.bat
```

服务默认运行在 http://localhost:5000

**访问测试**：
- 主页: http://localhost:5000/
- GPU 状态: http://localhost:5000/gpu-stats

### 4. 提示词模板配置

支持自定义：
- AI 解析角色系统提示词
- 角色生成提示词模板
- 章节拆分提示词模板

### 5. 国际化与时区设置

**语言设置**：
- 简体中文 (zh-CN)
- 繁体中文 (zh-TW)
- English (en-US)
- 日本語 (ja-JP)
- 한국어 (ko-KR)

**时区设置**：
- 支持全球主要时区
- 所有时间显示（任务列表、LLM日志等）按指定时区转换
- 后端统一存储 UTC 时间，前端根据用户设置动态转换

在【系统配置】→【语言与时区】页面进行设置。

## 开发路线图

- [x] 项目初始化
- [x] 基础页面（欢迎、配置、小说列表）
- [x] 后端 API 框架
- [x] DeepSeek API 集成（文本解析）
- [x] ComfyUI API 集成（生图/生视频）
- [x] 任务队列系统
- [x] 角色库管理
- [x] 工作流管理系统
- [x] JSON 解析日志
- [x] 预设测试用例
- [x] 多语言支持（中/英/日/韩/繁中）
- [x] 时区支持
- [x] 视频合成功能（支持分镜视频合并、转场视频插入）

## 使用说明

### 1. 新建小说
- 点击【新建小说】创建小说
- 或选择预设测试用例快速体验

### 2. AI 解析角色和场景
- 在小说详情页点击【AI解析角色】提取角色信息
- 点击【AI解析场景】提取场景信息
- 支持指定章节范围解析，支持增量更新

### 3. 生成角色和场景形象
- 进入【角色库】页面，点击【AI 生成所有角色形象】
- 进入【场景库】页面，点击【生成所有场景图】（可选）

### 4. 编辑章节与 AI 拆分分镜
- 进入【章节生成】页面，点击【AI 拆分分镜】自动拆分为分镜
- 进入【章节编辑】页面编辑章节内容，且编辑时支持增量更新解析角色和场景

### 5. 生成分镜图片
- 点击【生成全部分镜图】

### 6. 生成分镜视频
- 分镜图片生成完成后
- 点击【生成全部分镜视频】

### 7. 生成转场视频（可选）
- 在分镜之间生成转场过渡视频

### 8. 合并视频
- 点击【合并视频】将所有片段合成为完整视频

## 贡献指南

欢迎为项目做出贡献！请阅读 [贡献指南](docs/CONTRIBUTE_GUIDE.md) 了解如何参与开发。

## License

MIT
