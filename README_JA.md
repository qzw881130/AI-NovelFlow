# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI駆動の小説動画変換プラットフォーム

## プロジェクト概要

NovelFlow は小説の本文、登場人物やシーンの設定、ショット画像、音声、動画のタスクを一つの編集可能な制作フローにまとめます。各工程を確認しながら進めることも、章やショットを一括処理することもできます。

**制作フロー：** TXT/EPUB またはサンプル小説を取り込む → AI で人物・シーン・小道具を抽出 → 参照画像と声を準備 → 章を編集してショットに分割 → ショット画像を生成・評価 → Video Director で Clip を計画・生成 → 章/小説の動画を結合 → カバーを作成し、必要に応じて YouTube にアップロード。

Video Director は複数参照画像からの生成、動画の続きの生成、時間アンカー付きの延長に対応します。プロンプト、タスク、キーフレーム、生成結果を保存し、確認や再試行に利用できます。

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

- **フロントエンド**：React、TypeScript、Tailwind CSS、Vite、Zustand
- **バックエンド**：FastAPI、SQLAlchemy、SQLite、バックグラウンドタスク、ファイル保存
- **AI とメディア**：設定可能な LLM、ComfyUI、FFmpeg。画像プリセットに Moss Image と Qwen Image 2.1、動画に MiniMax H3、音声に Qwen3-TTS を使用
- **画面**：簡体字中国語、繁体字中国語、英語、日本語、韓国語とタイムゾーン設定

## 主な機能

- **小説と章**：TXT/EPUB の作成・編集・削除・取り込み、章の解析と一括取り込み/分割、サンプル小説。
- **素材ライブラリ**：人物、シーン、小道具の抽出と参照画像の生成・管理。人物の声や参照音声も管理。
- **ショットと画像**：AI による分割、手動編集、一括画像生成、参照画像の割り当て、キーフレーム、単一/複数画像の編集、AI 品質評価、高解像度再描画。
- **Video Director**：複数参照画像、続きの生成、時間アンカーに対応するショットと Clip の計画。プロンプト、LLM ログ、タスク、出力を保存。
- **Clip 実行検査**：タイムラインとフレームから生成の根拠、参照素材、観察記録を確認。
- **音声と納品**：任意の声設計・音声生成、Clip/章/小説動画の結合、初登場の名前表示プレビュー、カバー作成、YouTube アップロード。
- **ワークフローとプロンプト**：ComfyUI のシステム/カスタムワークフロー、ノードマッピング、インポート/エクスポート、プロンプトテンプレート。
- **タスクと通知**：バックグラウンド処理、再試行・復旧、イベント、ページ音、Feishu/Telegram 通知。
- **多言語と時刻**：5 言語の画面とユーザー指定タイムゾーン。

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
│   └── run_server.py
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

システム設定には DeepSeek、OpenAI、Gemini、Anthropic、Azure OpenAI、Alibaba Cloud Bailian、Ollama、および OpenAI API 互換サービスのプリセットがあります。利用するサービスの URL、モデル、API キーを設定します。必要に応じてプロキシを設定し、プロンプト設定で制作工程ごとのテンプレートを管理できます。

### 2. ComfyUI 設定

- 既定のアドレスは `http://localhost:8188` です。システム設定から変更できます。
- システムプリセットの JSON は `backend/workflows/`、登録規則とノードマッピングは `backend/app/constants/workflow.py` にあります。アップロードしたワークフローは `backend/user_workflows/` に保存されます。画面からインポート、エクスポート、選択、ノードマッピングができます。
- 画像プリセットには Moss Image T2I の人物四面図/シーン/小道具、Qwen Image 2.1 のショット/キーフレーム/単一・複数画像編集があります。動画プリセットには MiniMax H3 の複数参照、続きの生成、時間軸延長、2 回目のサンプリング、3D latent 拡大があります。音声ワークフローには Qwen3-TTS も含まれます。
- 実際の有効ワークフローはデータベースの選択によります。`debug/workflows/` はデバッグ用で、システムプリセットとして自動登録されません。

**モデルとノードの入手先**：[Quark ダウンロード](https://pan.quark.cn/s/2a630b7755ed)。選択したワークフロー JSON が参照するものをインストールしてください。2026-10-23 の棚卸しには Moss Image、Qwen Image 2.1、ローカル Qwen PE 書き換えモデル、H3 の本体/VAE/LoRA/拡大モデルとプラグインが含まれます。正確なパス、プラグインのリポジトリ、有効状態は [ComfyUI 依存関係一覧](docs/COMFYUI_DEPENDENCIES.md) を参照してください。

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

プロンプト設定ではシステムテンプレートの閲覧、独自テンプレートの作成・複製・編集・エクスポート、小説への割り当てができます。素材抽出、ショット、動画計画、画像品質評価などを対象とし、LLM ログから実際の呼び出しを追跡できます。

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

## 実装済みの制作機能

- [x] 小説・章の管理、人物/シーン/小道具の抽出と素材ライブラリ
- [x] ショット分割、一括画像生成、画像評価と高解像度再描画
- [x] Video Director、複数参照/続きの生成/時間軸延長、Clip 検査
- [x] 音声生成、章/小説動画の結合、名前表示プレビューとカバー
- [x] ワークフロー/プロンプト管理、タスク復旧、イベント通知、YouTube アップロード
- [x] 5 言語の画面とタイムゾーン設定

## 使い方

1. **環境を準備**：バックエンドとフロントエンドを起動し、システム設定で LLM と ComfyUI を設定します。選択したワークフローのモデルとノードを導入します。
2. **小説を取り込む**：TXT/EPUB を読み込むかサンプルを選び、必要に応じて章を一括取り込み・分割します。
3. **素材を準備**：人物、シーン、小道具を抽出して参照画像を生成します。人物の声の設計や参照音声の登録もできます。
4. **ショットを作る**：章を編集し、AI 分割結果を修正してショット画像とキーフレームを生成します。画像品質を確認し、必要なら高解像度で再描画します。
5. **音声・動画を生成**：必要なら音声を生成します。Video Director でワークフローと参照画像を選び、Clip を計画して動画を生成・延長します。
6. **確認して結合**：タスクと Clip 実行検査画面で状態、フレーム、根拠を確認し、Clip と章を結合します。名前表示プレビューも選べます。
7. **納品**：小説動画を結合し、カバーを作成・ダウンロードします。YouTube 接続後はアップロードできます。

## コントリビューション

プロジェクトへの貢献を歓迎します！[コントリビューションガイド](docs/CONTRIBUTE_GUIDE_EN.md)をお読みいただき、開発への参加方法をご確認ください。

## License

このプロジェクトは GNU General Public License v3.0 の下でライセンスされています - 詳細は [LICENSE](LICENSE) ファイルをご覧ください。
