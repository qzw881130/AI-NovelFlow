// 繁体中文欢迎页翻译 - 继承自简体中文
import zhCN from '../zh-CN/welcome';

export default {
  welcome: {
    ...zhCN,
    title: '歡迎使用 NovelFlow',
    subtitle: 'AI 驅動的小說到動畫/影片工作流程',
    getStarted: '開始使用',
    quickActions: '快速操作',
    recentNovels: '最近的小說',
    systemStatus: '系統狀態',
    pleaseConfigure: '請先完成系統配置，才能開始使用 NovelFlow。',

    workflow: {
      importNovel: '匯入小說',
      parseCharacters: 'AI解析角色',
      parseScenes: 'AI解析場景',
      parseProps: 'AI解析道具',
      generateCharacters: '生成角色圖',
      generateScenes: '生成場景圖',
      generateProps: '生成道具圖',
      editChapter: '編輯章節',
      splitShots: 'AI拆分分鏡',
      generateShotImages: '生成分鏡圖',
      generateAudio: '生成音訊',
      generateVideo: '生成影片',
    },

    features: {
      novelManagement: {
        title: '📚 小說管理',
        desc: '上傳和管理小說文字，支援 TXT、EPUB 格式，自動解析章節結構',
      },
      characterLibrary: {
        title: '👥 角色庫',
        desc: 'AI 自動提取角色資訊，生成角色人設圖和參考圖',
      },
      storyboard: {
        title: '🎬 智慧分鏡',
        desc: '自動將章節拆分為分鏡，生成 AI 繪圖提示詞',
      },
      comfyUI: {
        title: '🎨 ComfyUI 整合',
        desc: '一鍵傳送到 ComfyUI 生成圖片和影片',
      },
      workflow: {
        title: '⚡ 工作流程自動化',
        desc: '支援批次生成、任務佇列管理',
      },
    },
  },
};