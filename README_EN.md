# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI-Powered Novel to Video Platform

## Project Overview

NovelFlow is an AI platform that automatically converts novels into videos.

**Core Workflow:**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  Novel  │ → │ AI Parse  │ → │ AI Parse  │ → │ AI Parse  │ → │ Generate  │
│         │    │ Characters│    │  Scenes   │    │   Props   │    │Character  │
│         │    │           │    │           │    │           │    │  Images   │
└─────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                                    ↓
┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  Generate │ ← │  Generate │ ← │ Gen Shot  │ ← │ AI Split  │ ← │ Generate  │
│   Video   │    │   Audio   │    │  Image    │    │   Shots   │    │  Scene    │
└───────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                        ↑
                              ┌───────────┐    ┌───────────┐
                              │   Edit    │ ← │ Generate  │
                              │  Chapter  │    │Prop Images│
                              └───────────┘    └───────────┘
```

**Detailed Steps:**
1. **Import Novel** - Create new or import novel text (TXT, EPUB supported)
2. **AI Parse Characters** - Automatically extract character info (name, description, appearance)
3. **AI Parse Scenes** - Automatically extract scene info (scene name, environment description)
4. **AI Parse Props** - Automatically extract prop info (prop name, appearance description)
5. **Generate Character Images** - Generate AI character portraits for each character
6. **Generate Scene Images** - Generate reference images for each scene
7. **Generate Prop Images** - Generate reference images for each prop
8. **Edit Chapter / AI Split Shots** - Edit chapter content, AI automatically splits into shots
9. **Generate Shot Images** - Generate scene images based on shot descriptions
10. **Generate Audio** - Generate voiceover/sound effects for shots (optional)
11. **Generate Video** - Generate shot videos, transition videos and merge into complete video

**Key Features:**
- Support for chapter-style novel parsing
- Character consistency (maintain character appearance across multiple scenes)
- Scene consistency (maintain scene environment across multiple shots)
- Automatic shot generation and video composition

## Interface Preview

<img src="docs/index-en.png" alt="Interface Preview" width="800">

## Video Introduction

📺 <a href="https://www.bilibili.com/video/BV1VdZbBDEXF" target="_blank">Bilibili: AI-NovelFlow Novel to Video Platform Introduction</a>

📺 <a href="https://www.youtube.com/watch?v=IlMbeDme2F8" target="_blank">YouTube: AI-NovelFlow Novel to Video Platform Introduction</a>

📺 <a href="https://www.youtube.com/watch?v=DybveicQ9eQ" target="_blank">YouTube: How to Install on Windows</a>

## Community

| Telegram Group | QQ Group |
|:---:|:---:|
| <a href="https://t.me/AI_NovelFlow" target="_blank">@AI_NovelFlow</a> | 1083469624 |
| <img src="docs/telegram_group.png" width="200" alt="Telegram Group QR Code"> | <img src="docs/qq_group.png" width="200" alt="QQ Group QR Code"> |

## Tech Stack

- **Frontend**: React + TypeScript + Tailwind CSS + Vite
- **State Management**: Zustand (global state + i18n/timezone state)
- **Backend**: FastAPI + SQLAlchemy + SQLite
- **AI**: DeepSeek API / OpenAI API / Gemini API + ComfyUI
- **Video Generation**: LTX-2 video generation model
- **i18n**: Custom i18n implementation (5 languages supported)

## Main Features

- **Novel Management**: Support creating, editing, deleting novels, automatic chapter parsing
- **Character Library**: AI auto-parse characters, support character image generation and consistency
- **Scene Library**: AI auto-parse scenes, support scene reference image generation and environment settings
- **Shot Generation**: AI auto-split chapters into shots, support batch image and video generation
- **Transition Videos**: Support camera transitions, lighting transitions, occlusion transitions
- **Video Composition**: Support merging shot videos into complete chapter videos, auto-insert transitions
- **Workflow Management**: Support custom ComfyUI workflows, node mapping configuration
- **Task Queue**: Background async task processing, real-time task status monitoring
- **Preset Test Cases**: Built-in test cases like "The Little Horse Crosses the River", "Little Red Riding Hood", "The Emperor's New Clothes"
- **Multi-language Support**: Support Simplified Chinese, Traditional Chinese, English, Japanese, Korean interfaces
- **Timezone Support**: Users can customize timezone, all time displays are converted to specified timezone

## Project Structure

```
AI-NovelFlow/
├── backend/              # FastAPI Backend
│   ├── app/
│   │   ├── api/         # API Routes
│   │   ├── core/        # Core Configuration
│   │   ├── models/      # Database Models
│   │   ├── repositories/ # Data Repository Layer
│   │   ├── schemas/     # Pydantic Models
│   │   ├── services/    # Business Logic (LLM, ComfyUI)
│   │   └── utils/       # Utility Functions
│   ├── migrations/      # Database Migration Scripts
│   ├── prompt_templates/ # Prompt Template Files
│   ├── workflows/       # ComfyUI Workflow Configs
│   ├── user_story/      # Generated images/videos storage
│   ├── user_workflows/  # User Custom Workflows
│   └── main.py
├── frontend/            # React Frontend
│   └── my-app/
│       ├── src/
│       │   ├── components/  # Components
│       │   ├── i18n/        # i18n translation files
│       │   ├── pages/       # Pages
│       │   ├── stores/      # State Management
│       │   └── types/       # TypeScript Types
│       └── package.json
├── windows_gpu_monitor/ # Windows GPU Monitor Service (Optional)
│   ├── gpu_monitor.py   # GPU Monitor Service
│   ├── requirements.txt # Dependencies
│   └── start.bat        # Windows Startup Script
└── README.md
```

## Quick Start

### Backend Startup

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend service will run at http://localhost:8000

### Frontend Startup

```bash
cd frontend/my-app
npm install
npm run dev
```

Frontend service will run at http://localhost:5173

## API Documentation

Visit after starting backend: http://localhost:8000/docs

## Configuration

### 1. LLM API Configuration

Support multiple LLM providers:
- **DeepSeek** (default): https://api.deepseek.com
- **OpenAI**: https://api.openai.com
- **Gemini**: https://generativelanguage.googleapis.com
- **Anthropic**: https://api.anthropic.com
- **Azure OpenAI**: Custom Azure endpoint

Set API Key and proxy (if needed) in the [System Settings] page.

### 2. ComfyUI Configuration

- **ComfyUI Address**: Default http://localhost:8188
- **Workflow Configuration**: Support uploading custom workflows, need node mapping
  - Character Generation: Prompt node + Image save node
  - Scene Generation: Prompt node + Image save node + Width/Height node
  - Shot Image: Prompt node + Image save node + Width/Height node
  - Shot Video: Prompt node + Video save node + Reference image node
  - Transition Video: First frame node + Last frame node + Video save node

#### 2.1 Model Files

Directory is based on `ComfyUI/models/...`; if you use ComfyUI-Manager, it generally scans these directories as well.

| Model Filename | Type | Main Purpose | Workflows Used | Recommended Directory |
|---------------|------|-------------|----------------|---------------------|
| `ltx-2-19b-dev-fp8.safetensors` | checkpoint / main model | LTX2 transition (occlusion/lighting/camera) video generation | LTX2 Occlusion Transition / Lighting Transition / Camera Transition | `models/checkpoints/` |
| `ltx-2-19b-distilled-fp8.safetensors` | checkpoint / main model | LTX2 video generation (direct/expanded) | LTX2 Video Generation - Direct / Expanded | `models/checkpoints/` |
| `gemma_3_12B_it_fp8_e4m3fn.safetensors` | text encoder (LTX text encoder) | LTX2 text encoding | All LTX2 workflows (transition/video generation) | `models/text_encoders/` |
| `ltx-2-19b-distilled-lora-384.safetensors` | LoRA | LTX2 distilled LoRA (enhance/match distillation process) | Mainly in transition workflows | `models/loras/` |
| `ltx-2-19b-lora-camera-control-dolly-left.safetensors` | LoRA | LTX2 camera control (dolly-left) | Mainly in transition workflows | `models/loras/` |
| `ltx-2-spatial-upscaler-x2-1.0.safetensors` | upscale model (latent upscaler) | LTX2 latent spatial upscale x2 | Mainly in transition workflows | `models/upscale_models/` |
| `ae.safetensors` | VAE / AE | Used as VAE/AE in Z-image-turbo and some default character workflows | Z-image-turbo Single Image / System Default - Character | `models/vae/` |
| `flux-2-klein-9b.safetensors` | UNet | Flux2-Klein shot image generation UNet | Flux2-Klein-9B Shot Image / System Default - Character | `models/unet/` |
| `flux2-vae.safetensors` | VAE | Flux2 VAE | Flux2-Klein-9B Shot Image / System Default - Character | `models/vae/` |
| `qwen_3_8b.safetensors` | text encoder | Flux2 text encoding | Flux2-Klein-9B Shot Image / System Default - Character | `models/clip/` |
| `z_image_turbo_bf16.safetensors` | UNet | Z-image-turbo single image generation UNet | Z-image-turbo Single Image / System Default - Character | `models/unet/` |
| `qwen_3_4b.safetensors` | text encoder | Z-image-turbo text encoding | Z-image-turbo Single Image / System Default - Character | `models/clip/` |

#### 2.2 Third-Party Node Packages

| Third-Party Node Package | GitHub Repository | Node class_type in Workflows |
|-------------------------|------------------|------------------------------|
| **LTXVideo / LTXV** | [Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) | `LTXAVTextEncoderLoader`, `LTXVScheduler`, `LTXV*`, `LTXAV*`, `Painter*` |
| **VideoHelperSuite / VHS** | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `VHS_VideoCombine` |
| **Easy-Use** | [yolain/ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | `easy int`, `easy cleanGpuUsed`, `easy showAnything` |
| **LayerStyle / LayerUtility** | [chflame163/ComfyUI_LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle) | `LayerUtility: ImageScaleByAspectRatio V2` |
| **Comfyroll** | [Suzie1/ComfyUI_Comfyroll_CustomNodes](https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes) | `CR Prompt Text`, `CR Text` |
| **FizzNodes / ConcatStringSingle** | [FizzleDorf/ComfyUI_FizzNodes](https://github.com/FizzleDorf/ComfyUI_FizzNodes) | `ConcatStringSingle` |
| **comfyui-various / JWInteger** | [jamesWalker55/comfyui-various](https://github.com/jamesWalker55/comfyui-various) | `JWInteger` |
| **ReservedVRAM** | [Windecay/ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | `ReservedVRAMSetter` |
| **Qwen3-VL-Instruct / Qwen3_VQA** | [luvenisSapiens/ComfyUI_Qwen3-VL-Instruct](https://github.com/IuvenisSapiens/ComfyUI_Qwen3-VL-Instruct) | `Qwen3_VQA` |
| **Comfyui-zhenzhen** | [T8mars/Comfyui-zhenzhen](https://github.com/T8mars/Comfyui-zhenzhen) | `Zhenzhen_nano_banana`, `Zhenzhen API Settings` |

### 3. Windows GPU Monitor (Optional)

If ComfyUI runs on a remote Windows server, you can deploy the `windows_gpu_monitor` service to get real-time GPU status.

**Features**:
- Real-time monitoring of GPU usage, temperature, VRAM
- Monitor memory usage
- Display queue task count

**Deployment Steps**:

```bash
cd windows_gpu_monitor

# Install dependencies
pip install -r requirements.txt

# Start service
start.bat
```

Service runs at http://localhost:5000 by default

**Access Test**:
- Home: http://localhost:5000/
- GPU Status: http://localhost:5000/gpu-stats

### 4. Prompt Template Configuration

Support customization:
- AI parse characters system prompt
- Character generation prompt templates
- Chapter split prompt templates

### 5. Internationalization and Timezone Settings

**Language Settings**:
- Simplified Chinese (zh-CN)
- Traditional Chinese (zh-TW)
- English (en-US)
- 日本語 (ja-JP)
- 한국어 (ko-KR)

**Timezone Settings**:
- Support major global timezones
- All time displays (task list, LLM logs, etc.) converted to specified timezone
- Backend stores UTC time uniformly, frontend dynamically converts based on user settings

Configure in [System Settings] → [Language & Timezone] page.

## Development Roadmap

- [x] Project Initialization
- [x] Basic Pages (Welcome, Config, Novel List)
- [x] Backend API Framework
- [x] DeepSeek API Integration (Text Parsing)
- [x] ComfyUI API Integration (Image/Video Generation)
- [x] Task Queue System
- [x] Character Library Management
- [x] Workflow Management System
- [x] JSON Parse Logs
- [x] Preset Test Cases
- [x] Multi-language Support (CN/EN/JP/KR/TW)
- [x] Timezone Support
- [x] Video Composition (support shot video merging, transition insertion)

## Usage Instructions

### 1. Create Novel
- Click [Create Novel] to create a novel
- Or select preset test cases for quick experience

### 2. AI Parse Characters, Scenes and Props
- Click [AI Parse Characters] on novel detail page to extract character info
- Click [AI Parse Scenes] to extract scene info
- Click [AI Parse Props] to extract prop info
- Support chapter range selection and incremental update

### 3. Generate Character, Scene and Prop Images
- Enter [Character Library] page, click [AI Generate All Character Images]
- Enter [Scene Library] page, click [Generate All Scene Images]
- Enter [Props Library] page, click [Generate All Prop Images]

### 4. Edit Chapter and AI Split Shots
- Enter [Chapter Generation] page, click [AI Split Shots] to automatically split into shots
- Enter [Chapter Edit] page to edit chapter content, supports incremental parsing of characters, scenes and props during editing

### 5. Generate Shot Images
- Click [Generate All Shot Images]

### 6. Generate Audio (Optional)
- Click [Generate All Audio] to generate voiceover/sound effects for shots

### 7. Generate Video
- Click [Generate All Shot Videos] to generate shot videos
- Click [Generate All Transition Videos] to generate transition videos (optional)
- Click [Merge Video] to combine all clips into complete video

## Contributing

Contributions are welcome! Please read the [Contributing Guide](docs/CONTRIBUTE_GUIDE_EN.md) to learn how to participate in development.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
