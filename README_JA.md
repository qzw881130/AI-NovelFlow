# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI駆動の小説動画変換プラットフォーム

## プロジェクト概要

NovelFlowは、小説を自動的に動画に変換するAIプラットフォームです。

**コアワークフロー：**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  小説   │ → │AIキャラ   │ → │ AIシーン  │ → │ AI小道具  │ → │ キャラ    │
│         │    │  解析     │    │  解析     │    │  解析     │    │ 画像生成  │
└─────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                                    ↓
┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  動画     │ ← │  音声     │ ← │  ショット  │ ← │ AIショット│ ← │ シーン    │
│  生成     │    │  生成     │    │  画像生成  │    │  分割     │    │ 画像生成  │
└───────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                        ↑
                              ┌───────────┐    ┌───────────┐
                              │  章       │ ← │ 小道具    │
                              │  編集     │    │ 画像生成  │
                              └───────────┘    └───────────┘
```

**詳細手順：**
1. **小説インポート** - 新規作成または小説テキストのインポート（TXT、EPUB対応）
2. **AIキャラクター解析** - キャラクター情報を自動抽出（名前、説明、外見）
3. **AIシーン解析** - シーン情報を自動抽出（シーン名、環境説明）
4. **AI小道具解析** - 小道具情報を自動抽出（小道具名、外見説明）
5. **キャラクター画像生成** - 各キャラクターのAI画像を生成
6. **シーン画像生成** - 各シーンの参照画像を生成
7. **小道具画像生成** - 各小道具の参照画像を生成
8. **章編集 / AIショット分割** - 章内容を編集、AIが自動的にショットに分割
9. **ショット画像生成** - ショット説明に基づいてシーン画像を生成
10. **音声生成** - ショットのナレーション/効果音を生成（オプション）
11. **動画生成** - Video Director で単一フレーム、始端/終端フレーム、またはマルチキーフレームのショット動画を生成し、完全な動画に統合

**主な特徴：**
- 章回体小説の解析をサポート
- キャラクター一貫性（複数シーンでキャラクター外見を保持）
- シーン一貫性（複数ショットでシーン環境を保持）
- 自動ショット生成と動画合成

## インターフェースプレビュー

<img src="docs/index-en.png" alt="インターフェースプレビュー" width="800">

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
- **動画生成**: MiniMax H3 画像-to-動画、始端/終端フレーム動画、マルチキーフレーム動画
- **国際化**: カスタム i18n 実装（5言語対応）

## 主な機能

- **小説管理**: 新規作成、編集、削除をサポート、自動章回体解析
- **キャラクター図鑑**: AI自動キャラクター解析、キャラクター画像生成と一貫性保持
- **シーン図鑑**: AI自動シーン解析、シーン参照画像生成と環境設定をサポート
- **ショット生成**: AI自動章分割、一括画像生成、構造化編集、状態復旧をサポート
- **Video Director**: 単一フレーム、始端/終端フレーム、3キーフレーム、4キーフレームの動画計画に対応し、AI呼び出し結果と最終Promptを保持
- **動画合成**: ショット動画とマルチClip出力を完全な章動画に統合
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
│   ├── user_workflows/  # ユーザーカスタムワークフロー
│   ├── user_story/      # 生成画像/動画保存ディレクトリ
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
├── debug/workflows/     # デバッグ用ワークフロー例、システム既定としては読み込まない
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
  - 単一フレーム動画: プロンプトノード + 動画保存ノード + 参照画像ノード + 長さノード
  - 始端/終端フレーム動画: プロンプトノード + 先頭画像ノード + 末尾画像ノード + 動画保存ノード + 長さノード
  - 3/4キーフレーム動画: プロンプトノード + 開始参照ノード + キーフレームノード + 動画保存ノード + 長さノード
  - キーフレーム画像: プロンプトノード + 画像保存ノード + 参照画像ノード

システムワークフローは `backend/workflows/` に保存され、`backend/app/constants/workflow.py` によって登録および既定選択されます。ユーザーアップロードのワークフローは `backend/user_workflows/` に保存されます。`debug/workflows/MiniMax H3/` はデバッグとワークフロー比較専用で、システム既定としては読み込まれません。

#### 2.1 モデルファイル

ディレクトリは `ComfyUI/models/...` を基準とします；ComfyUI-Manager を使用している場合も、一般的にこれらのディレクトリをスキャンします。

| モデルファイル名 | タイプ | 主な用途 | 使用されるワークフロー | 推奨ディレクトリ |
|----------------|--------|---------|---------------------|----------------|
| `minimax_h3_ref2va_bf16.safetensors` | diffusion model | MiniMax H3 参照画像-to-動画メインモデル | 単一フレーム、始端/終端フレーム、3キーフレーム、4キーフレーム動画ワークフロー | `models/diffusion_models/` |
| `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | text encoder | MiniMax H3 テキスト/ビジョンエンコード | MiniMax H3 動画ワークフロー | `models/text_encoders/` |
| `minimax_h3_video_vae_fp16.safetensors` | video VAE | MiniMax H3 動画 VAE | MiniMax H3 動画ワークフロー | `models/vae/` |
| `minimax_h3_audio_vae_fp32.safetensors` | audio VAE | MiniMax H3 音声 VAE | MiniMax H3 動画ワークフロー | `models/vae/` |
| `minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors` | LoRA | MiniMax H3 高速化 LoRA | MiniMax H3 高速ワークフロー | `models/loras/` |
| `ae.safetensors` | VAE / AE | Z-image-turbo および一部のデフォルトキャラクターワークフローで VAE/AE として使用 | Z-image-turbo 単体生成 / システム既定-キャラ生成 | `models/vae/` |
| `flux-2-klein-9b.safetensors` | UNet | Flux2-Klein 画像編集/ショット画像生成 | ショット画像、キーフレーム画像、既定キャラクターワークフロー | `models/unet/` |
| `flux2-vae.safetensors` | VAE | Flux2 VAE | Flux2-Klein 画像編集/ショット画像ワークフロー | `models/vae/` |
| `qwen_3_8b.safetensors` / `qwen_3_8b_fp8mixed.safetensors` | text encoder | Flux2 テキストエンコード | Flux2-Klein 画像編集/ショット画像ワークフロー | `models/clip/` |
| `qwen_image_edit_2511_fp8mixed.safetensors` | diffusion model | Qwen-Edit-2511 画像編集 | Qwen-Edit-2511 ショット参照ワークフロー | `models/diffusion_models/` |
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors` | LoRA | Qwen-Edit-2511 4ステップ高速化 | Qwen-Edit-2511 ショット参照ワークフロー | `models/loras/` |
| `qwen_image_vae.safetensors` | VAE | Qwen Image VAE | Qwen-Edit-2511 ショット参照ワークフロー | `models/vae/` |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | text encoder | Qwen-Edit-2511 テキスト/ビジョンエンコード | Qwen-Edit-2511 ショット参照ワークフロー | `models/clip/` |
| `z_image_turbo_bf16.safetensors` | UNet | Z-image-turbo 単体生成 UNet | Z-image-turbo 単体生成 / システム既定-キャラ生成 | `models/unet/` |
| `qwen_3_4b.safetensors` | text encoder | Z-image-turbo テキストエンコーディング | Z-image-turbo 単体生成 / システム既定-キャラ生成 | `models/clip/` |
| `Qwen3.8-27B-Q4_K_M.gguf` / `mmproj-F16.gguf` | LLM / projector | デバッグワークフローでのローカル LLM Prompt 拡張 | `debug/workflows/MiniMax H3/` LLM デバッグワークフロー | `models/LLM/` |

#### 2.2 サードパーティノードパッケージ

| サードパーティノードパッケージ | GitHub リポジトリ | ワークフロー内のノード class_type |
|---------------------------|------------------|--------------------------------|
| **MiniMax H3** | ComfyUI MiniMax H3 ノード | `MiniMaxH3ReferenceToVideo`, `MiniMaxH3SigmaShift`, `MiniMaxH3MemoryEfficientSageAttentionPatch`, `MiniMaxH3PromptEnhancerT8` |
| **Flux2 / Qwen Image Edit** | Flux2、Qwen-Edit 対応 ComfyUI ノード | `Flux2Scheduler`, `EmptyFlux2LatentImage`, `TextEncodeQwenImageEditPlusAdvance_lrzjason` |
| **VideoHelperSuite / VHS** | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `VHS_VideoCombine` |
| **Easy-Use** | [yolain/ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | `easy int`, `easy cleanGpuUsed`, `easy showAnything` |
| **LayerStyle / LayerUtility** | [chflame163/ComfyUI_LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle) | `LayerUtility: ImageScaleByAspectRatio V2` |
| **Comfyroll** | [Suzie1/ComfyUI_Comfyroll_CustomNodes](https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes) | `CR Prompt Text`, `CR Text` |
| **FizzNodes / ConcatStringSingle** | [FizzleDorf/ComfyUI_FizzNodes](https://github.com/FizzleDorf/ComfyUI_FizzNodes) | `ConcatStringSingle` |
| **comfyui-various / JWInteger** | [jamesWalker55/comfyui-various](https://github.com/jamesWalker55/comfyui-various) | `JWInteger` |
| **ReservedVRAM** | [Windecay/ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | `ReservedVRAMSetter` |
| **Qwen3-VL-Instruct / Qwen3_VQA** | [luvenisSapiens/ComfyUI_Qwen3-VL-Instruct](https://github.com/IuvenisSapiens/ComfyUI_Qwen3-VL-Instruct) | `Qwen3_VQA` |
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
- [x] Video Director（単一フレーム、始端/終端フレーム、3/4キーフレーム、マルチClip逐次生成）
- [x] 永続化されたショット画像一括キュー（サービス再起動復旧と一括キャンセル対応）
- [x] 動画合成功能（ショット動画、マルチClip統合をサポート）

## 使用説明

### 1. 小説を新規作成
- 【小説を作成】をクリックして小説を作成
- またはプリセットテストケースを選択してクイック体験

### 2. AI キャラクター、シーン、小道具解析
- 小説詳細ページで【AIキャラクター解析】をクリックしてキャラクター情報を抽出
- 【AIシーン解析】をクリックしてシーン情報を抽出
- 【AI小道具解析】をクリックして小道具情報を抽出
- 章範囲指定と増分更新をサポート

### 3. キャラクター、シーン、小道具画像を生成
- 【キャラクター】ページに入り、【AIですべてのキャラクター画像を生成】をクリック
- 【シーン】ページに入り、【すべてのシーン画像を生成】をクリック
- 【小道具】ページに入り、【すべての小道具画像を生成】をクリック

### 4. 章編集とAIショット分割
- 【章生成】ページに入り、【AIショット分割】をクリックして自動的にショットに分割
- 【章編集】ページに入り、章内容を編集；編集中にキャラクター、シーン、小道具の増分解析をサポート

### 5. ショット画像を生成
- 【すべてのショット画像を生成】をクリックして永続化一括タスクを作成
- 未生成ショットのみを選択、または既存AI Promptを再利用してLLM呼び出しをスキップ可能

### 6. 音声を生成（オプション）
- 【すべての音声を生成】をクリックしてショットのナレーション/効果音を生成

### 7. 動画を生成
- 【動画生成】で Video Director を使って動画モードを計画
- 単一フレームモードはメインストーリーボード画像を再利用
- 始端/終端フレームモードはメインストーリーボードを START として再利用し、先に END キーフレーム画像を生成
- マルチキーフレームモードは最大Clip長で execution windows を分割し、各Clipは3または4枚のキーフレームで逐次生成
- 【動画統合】をクリックしてすべてのクリップを完全な動画に合成

## コントリビューション

プロジェクトへの貢献を歓迎します！[コントリビューションガイド](docs/CONTRIBUTE_GUIDE_EN.md)をお読みいただき、開発への参加方法をご確認ください。

## License

このプロジェクトは GNU General Public License v3.0 の下でライセンスされています - 詳細は [LICENSE](LICENSE) ファイルをご覧ください。
