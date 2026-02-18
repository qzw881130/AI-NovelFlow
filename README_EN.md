# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI-Powered Novel to Video Platform

## Project Overview

NovelFlow is an AI platform that automatically converts novels into videos.

**Core Workflow:**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  Novel  │ → │ AI Parse  │ → │ Generate  │ → │ Original  │
│         │    │ Characters│    │Character  │    │  Content  │
└─────────┘    └───────────┘    └───────────┘    └───────────┘
                                                         ↓
┌───────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Merge   │ ← │ Gen Transition│ ← │  Gen Shot     │ ← │   Gen Shot    │
│   Video   │    │    Video      │    │    Video      │    │     Image     │
└───────────┘    └───────────────┘    └───────────────┘    └───────┬───────┘
                                                                    ↑
                              ┌───────────────┐    ┌───────────┐    │
                              │ Merge Char    │ ← │  JSON     │ ← ┘
                              │    Image      │    │ Structure │
                              └───────────────┘    └───────────┘
```

**Detailed Steps:**
1. **Novel** - Create new or import novel text
2. **AI Parse Characters** - Automatically extract character info (name, description, appearance)
3. **Generate Character Image** - Generate AI character portraits for each character
4. **Original Content** - Edit novel chapter content
5. **AI Split Shots** - Split chapters into shots (scene, camera, action)
6. **JSON Structure** - Generate shot data (characters, scenes, shot descriptions)
7. **Generate Merged Character Image** - Merge multiple characters into reference image (for shot generation)
8. **Generate Shot Images** - Generate scene images based on shot descriptions
9. **Generate Shot Videos** - Convert shot images into video clips
10. **Generate Transition Videos** - Generate transition videos between shots (optional)
11. **Merge Videos** - Combine all clips into a complete video

**Key Features:**
- Support for chapter-style novel parsing
- Character consistency (maintain character appearance across multiple scenes)
- Automatic shot generation and video composition

## Video Introduction

📺 [Bilibili: AI-NovelFlow Novel to Video Platform Introduction](https://www.bilibili.com/video/BV1VdZbBDEXF)

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
│   │   ├── schemas/     # Pydantic Models
│   │   └── services/    # Business Logic (LLM, ComfyUI)
│   ├── user_story/      # Generated images/videos storage
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
  - Shot Image: Prompt node + Image save node + Width/Height node
  - Shot Video: Prompt node + Video save node + Reference image node
  - Transition Video: First frame node + Last frame node + Video save node

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

### 2. AI Parse
- Click [AI Split Chapter] on the chapter page
- System automatically parses characters, scenes and shots

### 3. Generate Character Portraits
- Enter [Character Library] page
- Click [AI Generate All Character Images]

### 4. Generate Shot Images
- Enter [Chapter Generation] page
- Click [Generate All Shots]

### 5. Generate Shot Videos
- After shot images are generated
- Click [Generate All Shot Videos]

### 6. Generate Transition Videos (Optional)
- Generate transition videos between shots

## License

MIT
