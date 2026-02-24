# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI駆動の小説動画変換プラットフォーム

## プロジェクト概要

NovelFlowは、小説を自動的に動画に変換するAIプラットフォームです。

**コアワークフロー：**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  小説   │ → │AIキャラ   │ → │ AIシーン  │ → │ キャラ    │ → │ シーン    │
│         │    │  解析     │    │  解析     │    │ 画像生成  │    │ 画像生成  │
└─────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                            ↓
┌───────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  動画     │ ← │  トランジション│ ← │  ショット     │ ← │  ショット     │
│  統合     │    │  動画生成     │    │  動画生成     │    │  画像生成     │
└───────────┘    └───────────────┘    └───────────────┘    └───────┬───────┘
                                                                    ↑
                              ┌───────────────┐    ┌───────────┐    │
                              │ 統合キャラ    │ ← │  JSON     │ ← ┘
                              │ 画像生成      │    │ 構造      │
                              └───────────────┘    └───────────┘
                                                              ↑
                                              ┌───────────┐    │
                                              │  章       │ ← ┘
                                              │  編集     │
                                              │AIショット │
                                              │  分割     │
                                              └───────────┘
```

**詳細手順：**
1. **小説インポート** - 新規作成または小説テキストのインポート（TXT、EPUB対応）
2. **AIキャラクター解析** - キャラクター情報を自動抽出（名前、説明、外見）
3. **AIシーン解析** - シーン情報を自動抽出（シーン名、環境説明）
4. **キャラクター画像生成** - 各キャラクターのAI画像を生成
5. **シーン画像生成** - 各シーンの参照画像を生成（オプション）
6. **章編集 / AIショット分割** - 章内容を編集、AIが自動的にショットに分割；編集中にキャラクターとシーンの増分解析をサポート
7. **JSON構造** - ショットデータを生成（キャラクター、シーン、ショット説明）
8. **統合キャラクター画像生成** - 複数キャラクターを参照画像に統合
9. **ショット画像生成** - ショット説明に基づいてシーン画像を生成
10. **ショット動画生成** - ショット画像を動画クリップに変換
11. **トランジション動画生成** - ショット間にトランジション動画を生成（オプション）
12. **動画統合** - すべてのクリップを完全な動画に合成

**主な特徴：**
- 章回体小説の解析をサポート
- キャラクター一貫性（複数シーンでキャラクター外見を保持）
- シーン一貫性（複数ショットでシーン環境を保持）
- 自動ショット生成と動画合成

## 動画紹介

📺 <a href="https://www.bilibili.com/video/BV1VdZbBDEXF" target="_blank">Bilibili: AI-NovelFlow 小説動画変換プラットフォーム紹介</a>

📺 <a href="https://www.youtube.com/watch?v=IlMbeDme2F8" target="_blank">YouTube: AI-NovelFlow 小説動画変換プラットフォーム紹介</a>

📺 <a href="https://www.youtube.com/watch?v=DybveicQ9eQ" target="_blank">YouTube: Windowsでオープンソースプロジェクトをインストールする方法</a>

## コミュニティ

| Telegramグループ | QQグループ |
|:---:|:---:|
| <a href="https://t.me/AI_NovelFlow" target="_blank">@AI_NovelFlow</a> | 1083469624 |
| <img src="docs/telegram_group.png" width="200" alt="TelegramグループQRコード"> | <img src="docs/qq_group.png" width="200" alt="QQグループQRコード"> |

## 技術スタック

- **フロントエンド**: React + TypeScript + Tailwind CSS + Vite
- **状態管理**: Zustand（グローバル状態 + 国際化/タイムゾーン状態）
- **バックエンド**: FastAPI + SQLAlchemy + SQLite
- **AI**: DeepSeek API / OpenAI API / Gemini API + ComfyUI
- **動画生成**: LTX-2 動画生成モデル
- **国際化**: カスタム i18n 実装（5言語対応）

## 主な機能

- **小説管理**: 新規作成、編集、削除をサポート、自動章回体解析
- **キャラクター図鑑**: AI自動キャラクター解析、キャラクター画像生成と一貫性保持
- **シーン図鑑**: AI自動シーン解析、シーン参照画像生成と環境設定をサポート
- **ショット生成**: AI自動章分割、一括画像・動画生成をサポート
- **トランジション動画**: カメラトランジション、ライティングトランジション、オクルージョントランジションをサポート
- **動画合成**: ショット動画を章動画に統合、自動トランジション挿入
- **ワークフロー管理**: カスタムComfyUIワークフロー、ノードマッピング設定
- **タスクキュー**: バックグラウンド非同期タスク処理、リアルタイムタスク監視
- **プリセットテストケース**: 「子馬の川渡り」「赤ずきん」「裸の王様」などのテストケースを内蔵
- **多言語サポート**: 簡体字中国語、繁体字中国語、英語、日本語、韓国語インターフェース
- **タイムゾーンサポート**: ユーザーがタイムゾーンをカスタマイズ可能、全時刻表示を指定タイムゾーンに変換

## プロジェクト構造

```
AI-NovelFlow/
├── backend/              # FastAPI バックエンド
│   ├── app/
│   │   ├── api/         # API ルート
│   │   ├── core/        # コア設定
│   │   ├── models/      # データベースモデル
│   │   ├── repositories/ # データリポジトリ層
│   │   ├── schemas/     # Pydantic モデル
│   │   ├── services/    # ビジネスロジック（LLM、ComfyUI）
│   │   └── utils/       # ユーティリティ関数
│   ├── migrations/      # データベース移行スクリプト
│   ├── prompt_templates/ # プロンプトテンプレートファイル
│   ├── workflows/       # ComfyUI ワークフロー設定
│   ├── user_story/      # 生成画像/動画保存ディレクトリ
│   ├── user_workflows/  # ユーザーカスタムワークフロー
│   └── main.py
├── frontend/            # React フロントエンド
│   └── my-app/
│       ├── src/
│       │   ├── components/  # コンポーネント
│       │   ├── i18n/        # 国際化翻訳ファイル
│       │   ├── pages/       # ページ
│       │   ├── stores/      # 状態管理
│       │   └── types/       # TypeScript 型
│       └── package.json
├── windows_gpu_monitor/ # Windows GPU監視サービス（オプション）
│   ├── gpu_monitor.py   # GPU監視サービス
│   ├── requirements.txt # 依存関係
│   └── start.bat        # Windows 起動スクリプト
└── README.md
```

## クイックスタート

### バックエンド起動

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

バックエンドサービスは http://localhost:8000 で実行

### フロントエンド起動

```bash
cd frontend/my-app
npm install
npm run dev
```

フロントエンドサービスは http://localhost:5173 で実行

## API ドキュメント

バックエンド起動後にアクセス: http://localhost:8000/docs

## 設定説明

### 1. LLM API 設定

複数のLLMプロバイダーをサポート：
- **DeepSeek**（デフォルト）: https://api.deepseek.com
- **OpenAI**: https://api.openai.com
- **Gemini**: https://generativelanguage.googleapis.com
- **Anthropic**: https://api.anthropic.com
- **Azure OpenAI**: カスタムAzureエンドポイント

【システム設定】ページでAPI Keyとプロキシを設定（必要に応じて）。

### 2. ComfyUI 設定

- **ComfyUI アドレス**: デフォルト http://localhost:8188
- **ワークフロー設定**: カスタムワークフローのアップロードをサポート、ノードマッピングが必要
  - キャラクター生成: プロンプトノード + 画像保存ノード
  - シーン生成: プロンプトノード + 画像保存ノード + 幅/高さノード
  - ショット画像: プロンプトノード + 画像保存ノード + 幅/高さノード
  - ショット動画: プロンプトノード + 動画保存ノード + 参照画像ノード
  - トランジション動画: 先頭フレームノード + 末尾フレームノード + 動画保存ノード

#### 2.1 モデルファイル

ディレクトリは `ComfyUI/models/...` を基準とします；ComfyUI-Manager を使用している場合も、一般的にこれらのディレクトリをスキャンします。

| モデルファイル名 | タイプ | 主な用途 | 使用されるワークフロー | 推奨ディレクトリ |
|----------------|--------|---------|---------------------|----------------|
| `ltx-2-19b-dev-fp8.safetensors` | checkpoint / メインモデル | LTX2 トランジション（オクルージョン/ライティング/カメラ）動画生成 | LTX2 オクルージョントランジション / ライティングトランジション / カメラトランジション | `models/checkpoints/` |
| `ltx-2-19b-distilled-fp8.safetensors` | checkpoint / メインモデル | LTX2 動画生成（ダイレクト/拡張版） | LTX2 動画生成-ダイレクト / 拡張版 | `models/checkpoints/` |
| `gemma_3_12B_it_fp8_e4m3fn.safetensors` | text encoder (LTX テキストエンコーダー) | LTX2 テキストエンコーディング | すべての LTX2 ワークフロー（トランジション/動画生成） | `models/text_encoders/` |
| `ltx-2-19b-distilled-lora-384.safetensors` | LoRA | LTX2 蒸留 LoRA（強化/蒸留プロセスのマッチング） | 主にトランジションワークフロー | `models/loras/` |
| `ltx-2-19b-lora-camera-control-dolly-left.safetensors` | LoRA | LTX2 カメラ制御 (dolly-left) | 主にトランジションワークフロー | `models/loras/` |
| `ltx-2-spatial-upscaler-x2-1.0.safetensors` | upscale model (latent upscaler) | LTX2 latent 空間アップスケール x2 | 主にトランジションワークフロー | `models/upscale_models/` |
| `ae.safetensors` | VAE / AE | Z-image-turbo および一部のデフォルトキャラクターワークフローで VAE/AE として使用 | Z-image-turbo 単体生成 / システム既定-キャラ生成 | `models/vae/` |
| `flux-2-klein-9b.safetensors` | UNet | Flux2-Klein ショット画像生成 UNet | Flux2-Klein-9B ショット画像 / システム既定-キャラ生成 | `models/unet/` |
| `flux2-vae.safetensors` | VAE | Flux2 の VAE | Flux2-Klein-9B ショット画像 / システム既定-キャラ生成 | `models/vae/` |
| `qwen_3_8b.safetensors` | text encoder | Flux2 テキストエンコーディング | Flux2-Klein-9B ショット画像 / システム既定-キャラ生成 | `models/clip/` |
| `z_image_turbo_bf16.safetensors` | UNet | Z-image-turbo 単体生成 UNet | Z-image-turbo 単体生成 / システム既定-キャラ生成 | `models/unet/` |
| `qwen_3_4b.safetensors` | text encoder | Z-image-turbo テキストエンコーディング | Z-image-turbo 単体生成 / システム既定-キャラ生成 | `models/clip/` |

#### 2.2 サードパーティノードパッケージ

| サードパーティノードパッケージ | GitHub リポジトリ | ワークフロー内のノード class_type |
|---------------------------|------------------|--------------------------------|
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

### 3. Windows GPU 監視（オプション）

ComfyUIがリモートWindowsサーバーで実行されている場合、`windows_gpu_monitor`サービスをデプロイしてリアルタイムGPU状態を取得可能。

**機能**：
- リアルタイムGPU使用率、温度、VRAM監視
- メモリ使用状況の監視
- キュータスク数の表示

**デプロイ手順**：

```bash
cd windows_gpu_monitor

# 依存関係をインストール
pip install -r requirements.txt

# サービスを起動
start.bat
```

サービスはデフォルトで http://localhost:5000 で実行

**アクセステスト**：
- ホーム: http://localhost:5000/
- GPU状態: http://localhost:5000/gpu-stats

### 4. プロンプトテンプレート設定

カスタマイズをサポート：
- AIキャラクター解析システムプロンプト
- キャラクター生成プロンプトテンプレート
- 章分割プロンプトテンプレート

### 5. 国際化とタイムゾーン設定

**言語設定**：
- 簡体字中国語 (zh-CN)
- 繁体字中国語 (zh-TW)
- English (en-US)
- 日本語 (ja-JP)
- 한국어 (ko-KR)

**タイムゾーン設定**：
- 世界主要タイムゾーンをサポート
- 全時刻表示（タスクリスト、LLMログなど）を指定タイムゾーンに変換
- バックエンドはUTC時間を統一保存、フロントエンドはユーザー設定に基づいて動的変換

【システム設定】→【言語とタイムゾーン】ページで設定。

## 開発ロードマップ

- [x] プロジェクト初期化
- [x] 基本ページ（ウェルカム、設定、小説リスト）
- [x] バックエンド API フレームワーク
- [x] DeepSeek API 統合（テキスト解析）
- [x] ComfyUI API 統合（画像/動画生成）
- [x] タスクキューシステム
- [x] キャラクター図鑑管理
- [x] ワークフロー管理システム
- [x] JSON 解析ログ
- [x] プリセットテストケース
- [x] 多言語サポート（中/英/日/韓/繁中）
- [x] タイムゾーンサポート
- [x] 動画合成功能（ショット動画統合、トランジション挿入をサポート）

## 使用説明

### 1. 小説を新規作成
- 【小説を作成】をクリックして小説を作成
- またはプリセットテストケースを選択してクイック体験

### 2. AI キャラクターとシーン解析
- 小説詳細ページで【AIキャラクター解析】をクリックしてキャラクター情報を抽出
- 【AIシーン解析】をクリックしてシーン情報を抽出
- 章範囲指定と増分更新をサポート

### 3. キャラクターとシーン画像を生成
- 【キャラクター】ページに入り、【AIですべてのキャラクター画像を生成】をクリック
- 【シーン】ページに入り、【すべてのシーン画像を生成】をクリック（オプション）

### 4. 章編集とAIショット分割
- 【章生成】ページに入り、【AIショット分割】をクリックして自動的にショットに分割
- 【章編集】ページに入り、章内容を編集；編集中にキャラクターとシーンの増分解析をサポート

### 5. ショット画像を生成
- 【すべてのショット画像を生成】をクリック

### 6. ショット動画を生成
- ショット画像の生成が完了した後
- 【すべてのショット動画を生成】をクリック

### 7. トランジション動画を生成（オプション）
- ショット間にトランジション動画を生成

### 8. 動画統合
- 【動画統合】をクリックしてすべてのクリップを完全な動画に合成

## License

MIT
