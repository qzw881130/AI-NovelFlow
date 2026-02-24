# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI 驅動的小說轉視訊平台

## 專案概述

NovelFlow 是一個將小說自動轉換為視訊的 AI 平台。

**核心工作流程：**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│   小說   │ → │ AI解析角色 │ → │ 生成角色圖 │ → │ 原文內容   │
└─────────┘    └───────────┘    └───────────┘    └───────────┘
                                                         ↓
┌───────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  合併視訊  │ ← │ 生成分鏡轉場  │ ← │ 生成分鏡視訊  │ ← │ 生成分鏡圖片  │
└───────────┘    └───────────────┘    └───────────────┘    └───────┬───────┘
                                                                    ↑
                              ┌───────────────┐    ┌───────────┐    │
                              │ 生成合併角色圖 │ ← │ JSON結構  │ ← ┘
                              └───────────────┘    └───────────┘
```

**詳細步驟：**
1. **小說** - 新建或導入小說文本
2. **AI解析角色** - 自動提取角色資訊（名稱、描述、外貌特徵）
3. **生成角色圖** - 為每個角色生成 AI 人設圖
4. **原文內容** - 編輯小說章節內容
5. **AI拆分分鏡頭** - 將章節拆分為分鏡（場景、鏡頭、動作）
6. **JSON結構** - 生成分鏡資料（角色、場景、鏡頭描述）
7. **生成合併角色圖** - 將多角色合併為參考圖（用於分鏡生成）
8. **生成分鏡圖片** - 根據分鏡描述生成場景圖片
9. **生成分鏡視訊** - 將分鏡圖片轉換為視訊片段
10. **生成分鏡轉場視訊** - 在分鏡間生成過渡視訊（可選）
11. **合併視訊** - 將所有片段合成為完整視訊

**主要特性：**
- 支持章回體小說解析
- 角色一致性保持（角色形象在多場景中保持一致）
- 自動分鏡生成和視訊合成

## 影片介紹

📺 <a href="https://www.bilibili.com/video/BV1VdZbBDEXF" target="_blank">Bilibili: AI-NovelFlow 小說轉視訊平台介紹</a>

📺 <a href="https://www.youtube.com/watch?v=IlMbeDme2F8" target="_blank">YouTube: AI-NovelFlow 小說轉視訊平台介紹</a>

📺 <a href="https://www.youtube.com/watch?v=DybveicQ9eQ" target="_blank">YouTube: Windows下如何安裝我們的開源項目</a>

## 社群交流

| Telegram 交流群組 | QQ 群 |
|:---:|:---:|
| <a href="https://t.me/AI_NovelFlow" target="_blank">@AI_NovelFlow</a> | 1083469624 |
| <img src="docs/telegram_group.png" width="200" alt="Telegram群二维码"> | <img src="docs/qq_group.png" width="200" alt="QQ群二维码"> |

## 技術棧

- **前端**: React + TypeScript + Tailwind CSS + Vite
- **狀態管理**: Zustand（全局狀態 + 國際化/時區狀態）
- **後端**: FastAPI + SQLAlchemy + SQLite
- **AI**: DeepSeek API / OpenAI API / Gemini API + ComfyUI
- **視訊生成**: LTX-2 視訊生成模型
- **國際化**: 自定義 i18n 實現（5 語言支持）

## 主要功能

- **小說管理**: 支持新建、編輯、刪除小說，自動章回體解析
- **角色庫**: AI 自動解析角色，支持角色形象生成和一致性保持
- **分鏡生成**: AI 自動拆分章節為分鏡，支持批量生成圖片和視訊
- **轉場視訊**: 支持生成鏡頭轉場、光線轉場、遮擋轉場視訊
- **視訊合成**: 支持將分鏡視訊合併為完整章節視訊，自動插入轉場
- **工作流管理**: 支持自定義 ComfyUI 工作流，節點映射配置
- **任務隊列**: 後台異步任務處理，支持任務狀態實時監控
- **預設測試用例**: 內置《小馬過河》《小紅帽》《皇帝的新裝》等測試用例
- **多語言支持**: 支持簡體中文、繁體中文、英文、日文、韓文介面
- **時區支持**: 用戶可自定義時區，所有時間顯示按指定時區轉換

## 專案結構

```
AI-NovelFlow/
├── backend/              # FastAPI 後端
│   ├── app/
│   │   ├── api/         # API 路由
│   │   ├── core/        # 核心配置
│   │   ├── models/      # 數據庫模型
│   │   ├── schemas/     # Pydantic 模型
│   │   └── services/    # 業務邏輯（LLM、ComfyUI）
│   ├── user_story/      # 生成的圖片/視訊存儲目錄
│   └── main.py
├── frontend/            # React 前端
│   └── my-app/
│       ├── src/
│       │   ├── components/  # 組件
│       │   ├── i18n/        # 國際化翻譯檔案
│       │   ├── pages/       # 頁面
│       │   ├── stores/      # 狀態管理
│       │   └── types/       # TypeScript 類型
│       └── package.json
├── windows_gpu_monitor/ # Windows GPU 監控服務（可選）
│   ├── gpu_monitor.py   # GPU 監控服務
│   ├── requirements.txt # 依賴
│   └── start.bat        # Windows 啟動腳本
└── README.md
```

## 快速開始

### 後端啟動

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

後端服務將在 http://localhost:8000 運行

### 前端啟動

```bash
cd frontend/my-app
npm install
npm run dev
```

前端服務將在 http://localhost:5173 運行

## API 文件

啟動後端後訪問: http://localhost:8000/docs

## 配置說明

### 1. LLM API 配置

支持多種 LLM 提供商：
- **DeepSeek**（預設）: https://api.deepseek.com
- **OpenAI**: https://api.openai.com
- **Gemini**: https://generativelanguage.googleapis.com
- **Anthropic**: https://api.anthropic.com
- **Azure OpenAI**: 自定義 Azure 端點

在【系統配置】頁面設置 API Key 和代理（如需）。

### 2. ComfyUI 配置

- **ComfyUI 地址**: 預設 http://localhost:8188
- **工作流配置**: 支持上傳自定義工作流，需配置節點映射
  - 人設生成: 提示詞節點 + 圖片保存節點
  - 分鏡生圖: 提示詞節點 + 圖片保存節點 + 寬高節點
  - 分鏡生視訊: 提示詞節點 + 視訊保存節點 + 參考圖節點
  - 轉場視訊: 首幀圖節點 + 尾幀圖節點 + 視訊保存節點

#### 2.1 模型文件

目錄以 `ComfyUI/models/...` 為基準；如果你用的是 ComfyUI-Manager，一般也按這些目錄掃描。

| 模型文件名 | 類型 | 主要用途 | 出現的工作流 | 建議目錄 |
|-----------|------|---------|-------------|---------|
| `ltx-2-19b-dev-fp8.safetensors` | checkpoint / 主模型 | LTX2 轉場（遮擋/光線/鏡頭）視訊生成 | LTX2 遮擋轉場視訊 / 光線轉場視訊 / 鏡頭轉場視訊 | `models/checkpoints/` |
| `ltx-2-19b-distilled-fp8.safetensors` | checkpoint / 主模型 | LTX2 視訊生成（直接版/擴寫版） | LTX2 視訊生成-直接版 / 擴寫版 | `models/checkpoints/` |
| `gemma_3_12B_it_fp8_e4m3fn.safetensors` | text encoder (LTX 文本編碼器) | LTX2 文本編碼 | 所有 LTX2 類工作流都會用（轉場/視訊生成） | `models/text_encoders/` |
| `ltx-2-19b-distilled-lora-384.safetensors` | LoRA | LTX2 蒸餾 LoRA（提升/匹配蒸餾流程） | 主要在轉場類工作流出現 | `models/loras/` |
| `ltx-2-19b-lora-camera-control-dolly-left.safetensors` | LoRA | LTX2 鏡頭控制 (dolly-left) | 主要在轉場類工作流出現 | `models/loras/` |
| `ltx-2-spatial-upscaler-x2-1.0.safetensors` | upscale model (latent upscaler) | LTX2 latent 空間放大 x2 | 主要在轉場類工作流出現 | `models/upscale_models/` |
| `ae.safetensors` | VAE / AE | 在 Z-image-turbo 及部分預設人設流程裡作為 VAE/AE | Z-image-turbo 單圖生成 / 系統預設-人設生成 | `models/vae/` |
| `flux-2-klein-9b.safetensors` | UNet | Flux2-Klein 分鏡生圖 UNet | Flux2-Klein-9B 分鏡生圖 / 系統預設-人設生成 | `models/unet/` |
| `flux2-vae.safetensors` | VAE | Flux2 的 VAE | Flux2-Klein-9B 分鏡生圖 / 系統預設-人設生成 | `models/vae/` |
| `qwen_3_8b.safetensors` | text encoder | Flux2 文本編碼 | Flux2-Klein-9B 分鏡生圖 / 系統預設-人設生成 | `models/clip/` |
| `z_image_turbo_bf16.safetensors` | UNet | Z-image-turbo 單圖生成 UNet | Z-image-turbo 單圖生成 / 系統預設-人設生成 | `models/unet/` |
| `qwen_3_4b.safetensors` | text encoder | Z-image-turbo 文本編碼 | Z-image-turbo 單圖生成 / 系統預設-人設生成 | `models/clip/` |

#### 2.2 第三方節點包

| 第三方節點包 | GitHub 倉庫 | 工作流中命中的節點 class_type |
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

### 3. Windows GPU 監控（可選）

如果 ComfyUI 運行在遠程 Windows 服務器上，可以部署 `windows_gpu_monitor` 服務來獲取實時 GPU 狀態。

**功能**：
- 實時監控 GPU 使用率、溫度、顯存佔用
- 監控內存使用情況
- 顯示隊列任務數量

**部署步驟**：

```bash
cd windows_gpu_monitor

# 安裝依賴
pip install -r requirements.txt

# 啟動服務
start.bat
```

服務預設運行在 http://localhost:5000

**訪問測試**：
- 主頁: http://localhost:5000/
- GPU 狀態: http://localhost:5000/gpu-stats

### 4. 提示詞模板配置

支持自定義：
- AI 解析角色系統提示詞
- 角色生成提示詞模板
- 章節拆分提示詞模板

### 5. 國際化與時區設置

**語言設置**：
- 簡體中文 (zh-CN)
- 繁體中文 (zh-TW)
- English (en-US)
- 日本語 (ja-JP)
- 한국어 (ko-KR)

**時區設置**：
- 支持全球主要時區
- 所有時間顯示（任務列表、LLM日誌等）按指定時區轉換
- 後端統一存儲 UTC 時間，前端根據用戶設置動態轉換

在【系統配置】→【語言與時區】頁面進行設置。

## 開發路線圖

- [x] 專案初始化
- [x] 基礎頁面（歡迎、配置、小說列表）
- [x] 後端 API 框架
- [x] DeepSeek API 集成（文本解析）
- [x] ComfyUI API 集成（生圖/生視訊）
- [x] 任務隊列系統
- [x] 角色庫管理
- [x] 工作流管理系統
- [x] JSON 解析日誌
- [x] 預設測試用例
- [x] 多語言支持（中/英/日/韓/繁中）
- [x] 時區支持
- [x] 視訊合成功能（支持分鏡視訊合併、轉場視訊插入）

## 使用說明

### 1. 新建小說
- 點擊【新建小說】創建小說
- 或選擇預設測試用例快速體驗

### 2. AI 解析
- 在章節頁面點擊【AI 拆分章節】
- 系統自動解析角色、場景和分鏡

### 3. 生成角色形象
- 進入【角色庫】頁面
- 點擊【AI 生成所有角色形象】

### 4. 生成分鏡圖片
- 進入【章節生成】頁面
- 點擊【生成全部分鏡圖】

### 5. 生成分鏡視訊
- 分鏡圖片生成完成後
- 點擊【生成全部分鏡視訊】

### 6. 生成轉場視訊（可選）
- 在分鏡之間生成轉場過渡視訊

## License

MIT
