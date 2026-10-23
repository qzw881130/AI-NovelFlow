# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI 驱动的小说转视频平台

## 项目概述

NovelFlow 将小说文本、角色与场景设定、分镜图片、音频和视频任务串成可编辑的制作流程。既可以逐步人工确认，也可以批量处理章节和分镜。

**制作流程：** 导入 TXT/EPUB 或示例小说 → AI 解析角色、场景、道具 → 生成参考图与音色 → 编辑章节并拆分分镜 → 生成及评审分镜图 → Video Director 规划和执行 Clip → 合并章节/小说视频 → 制作封面并按需上传 YouTube。

Video Director 支持多参考图生视频、视频续生成和带时间锚点的时序续生成。多 Clip 可串行执行；分镜、关键帧、提示词、任务及生成结果会保存，便于检查和重试。

## 界面预览

<img src="docs/index-cn.png" alt="界面预览" width="800">

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

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=qzw881130/AI-NovelFlow&type=Date)](https://star-history.com/#qzw881130/AI-NovelFlow&Date)

## 技术栈

- **前端**：React、TypeScript、Tailwind CSS、Vite、Zustand
- **后端**：FastAPI、SQLAlchemy、SQLite；后台任务和文件存储
- **AI 与媒体**：可配置的 LLM 服务、ComfyUI、FFmpeg；图片预设使用 Moss Image 和 Qwen Image 2.1，视频预设使用 MiniMax H3，音频预设包含 Qwen3-TTS
- **界面**：简体中文、繁体中文、英语、日语、韩语；可设置时区

## 主要功能

- **小说与章节**：新建、编辑、删除和导入 TXT/EPUB；章回解析、批量导入/拆分章节、内置示例小说。
- **素材库**：按小说或章节解析角色、场景、道具；生成与管理形象/参考图，维护角色音色与参考音频。
- **分镜与图片**：AI 拆分、人工编辑、批量生图、参考图绑定、关键帧和单图/多图编辑；图片质量 AI 评审及高清重绘。
- **Video Director**：规划分镜和 Clip，支持多参考图、续生成和时间锚点；保存提示词、LLM 日志、任务与生成结果。
- **Clip 执行检查**：按时间轴和帧查看生成证据、参考素材及观察记录，定位问题片段。
- **音频与后期**：可选的音色设计、语音生成；合并 Clip、章节和小说视频，生成首次出镜姓名牌预览与视频封面，并可上传 YouTube。
- **工作流与提示词**：管理 ComfyUI 系统预设和自定义工作流，配置节点映射、导入/导出工作流和提示词模板。
- **任务与通知**：后台队列、失败重试和状态恢复；业务事件、页面提示音及飞书/Telegram 通知。
- **多语言与时区**：五种界面语言，按用户选定时区显示时间。

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
│   ├── user_workflows/  # 用户自定义工作流
│   ├── user_story/      # 生成的图片/视频存储目录
│   └── run_server.py
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
├── debug/workflows/     # 调试用工作流样例，不作为系统默认加载
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

### 3. 更新升级

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

【系统配置】提供 DeepSeek、OpenAI、Gemini、Anthropic、Azure OpenAI、阿里云百炼、Ollama 和兼容 OpenAI API 的自定义服务预设。按所选服务填写 API 地址、模型和 API Key；Ollama 等本地服务可按实际配置使用。可在此设置代理，并通过【提示词配置】管理不同制作环节的模板。

### 2. ComfyUI 配置

- 默认地址：`http://localhost:8188`，在【系统配置】中可修改。
- 系统预设 JSON 位于 `backend/workflows/`，注册规则及节点映射位于 `backend/app/constants/workflow.py`；上传的工作流放在 `backend/user_workflows/`。可在界面中导入、导出、切换工作流，并为提示词、参考图、时长和输出节点配置映射。
- 当前图片预设涵盖 Moss Image T2I 角色四视图/场景/道具、Qwen Image 2.1 分镜/关键帧/单图与多图编辑；视频预设涵盖 MiniMax H3 多参考图、视频续生成、时序续生成以及第二遍采样与 3D latent 放大。音频工作流另含 Qwen3-TTS。
- 实际启用的工作流以数据库中的选择为准；`debug/workflows/` 是调试样例，不会自动注册为系统预设。

**模型与插件下载**：[夸克网盘](https://pan.quark.cn/s/2a630b7755ed)。安装时请核对当前工作流 JSON 所引用的模型文件和 `class_type`。按 2026-10-23 的盘点，图片流程主要使用 Moss Image、Qwen Image 2.1 及 Qwen PE 本地重写模型；三份 H3 视频流程使用各自的主模型/VAE/LoRA、3D latent 放大模型，以及 H3 Context、VideoHelperSuite 等节点插件。完整路径、插件仓库和启用状态见 [ComfyUI 工作流依赖清单](docs/COMFYUI_DEPENDENCIES.md)。

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

可在【提示词配置】查看系统模板，创建、复制、编辑和导出自定义模板，并按小说绑定。模板涵盖素材解析、分镜、视频规划、图片质量评审等环节；LLM 日志可用于追溯实际调用。

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

## 已实现的制作能力

- [x] 小说与章回管理、角色/场景/道具解析及素材库
- [x] 分镜拆分、批量生图、图片评审与高清重绘
- [x] Video Director、多参考图/续生成/时序续生成和 Clip 检查
- [x] 音频生成、章节/小说视频合并、姓名牌预览与封面
- [x] 工作流/提示词管理、任务恢复、事件通知及 YouTube 上传
- [x] 五语言界面与时区设置

## 使用说明

1. **准备环境**：启动后端与前端，在【系统配置】填写 LLM 和 ComfyUI 地址；按所选工作流安装模型和节点插件。
2. **导入小说**：新建小说，导入 TXT/EPUB 或选用示例；需要时批量导入或拆分章节。
3. **建立素材库**：解析角色、场景、道具，生成参考图；可为角色设计音色或上传参考音频。
4. **制作分镜**：编辑章节，AI 拆分分镜并校正结果；生成分镜图与关键帧，查看图片质量评审，必要时高清重绘。
5. **生成音视频**：按需生成音频；在 Video Director 选择工作流和参考图，规划 Clip 并执行视频生成或续生成。
6. **检查与合成**：在任务列表和 Clip 执行检查器查看状态、帧和证据；合并 Clip 与章节，按需使用姓名牌预览。
7. **交付**：合并小说视频、生成封面并下载；连接 YouTube 后可上传成片。

## 贡献指南

欢迎为项目做出贡献！请阅读 [贡献指南](docs/CONTRIBUTE_GUIDE.md) 了解如何参与开发。

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
