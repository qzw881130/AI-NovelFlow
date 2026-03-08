// 日语欢迎页翻译 - 继承自英语
import enUS from '../en-US/welcome';

export default {
  welcome: {
    ...enUS,
    title: 'NovelFlow へようこそ',
    subtitle: 'AI駆動の小説からアニメーション/動画へのワークフロー',
    getStarted: '始める',
    quickActions: 'クイックアクション',
    recentNovels: '最近の小説',
    systemStatus: 'システム状態',
    pleaseConfigure: 'NovelFlowを使用する前にシステム設定を完了してください。',

    workflow: {
      importNovel: '小説インポート',
      parseCharacters: 'AIキャラ解析',
      parseScenes: 'AIシーン解析',
      parseProps: 'AI小道具解析',
      generateCharacters: 'キャラ画像生成',
      generateScenes: 'シーン画像生成',
      generateProps: '小道具画像生成',
      editChapter: '章編集',
      splitShots: 'AIショット分割',
      generateShotImages: 'ショット画像生成',
      generateAudio: '音声生成',
      generateVideo: '動画生成',
    },

    features: {
      novelManagement: {
        title: '📚 小説管理',
        desc: '小説テキストのアップロードと管理、TXT・EPUB形式対応、章構造の自動解析',
      },
      characterLibrary: {
        title: '👥 キャラクターライブラリ',
        desc: 'AIによるキャラクター情報の自動抽出、キャラクター画像と参照画像の生成',
      },
      storyboard: {
        title: '🎬 スマートストーリーボード',
        desc: '章を自動的にショットに分割し、AI描画プロンプトを生成',
      },
      comfyUI: {
        title: '🎨 ComfyUI連携',
        desc: 'ワンクリックでComfyUIに送信して画像と動画を生成',
      },
      workflow: {
        title: '⚡ ワークフロー自動化',
        desc: 'バッチ生成とタスクキュー管理に対応',
      },
    },
  },
};