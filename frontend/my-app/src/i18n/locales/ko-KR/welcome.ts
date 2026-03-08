import enUS from '../en-US/welcome';

// Welcome page translations - Korean
export default {
  welcome: {
    ...enUS.welcome,
    title: 'NovelFlow에 오신 것을 환영합니다',
    subtitle: 'AI 기반 소설에서 애니메이션/비디오로의 워크플로우',
    getStarted: '시작하기',
    quickActions: '빠른 작업',
    recentNovels: '최근 소설',
    systemStatus: '시스템 상태',
    pleaseConfigure: 'NovelFlow를 사용하기 전에 시스템 설정을 완료해 주세요.',

    workflow: {
      importNovel: '소설 가져오기',
      parseCharacters: 'AI 캐릭터 분석',
      parseScenes: 'AI 장면 분석',
      parseProps: 'AI 소품 분석',
      generateCharacters: '캐릭터 이미지 생성',
      generateScenes: '장면 이미지 생성',
      generateProps: '소품 이미지 생성',
      editChapter: '장 편집',
      splitShots: 'AI 샷 분할',
      generateShotImages: '샷 이미지 생성',
      generateAudio: '오디오 생성',
      generateVideo: '비디오 생성',
    },

    features: {
      novelManagement: {
        title: '📚 소설 관리',
        desc: '소설 텍스트 업로드 및 관리, TXT·EPUB 형식 지원, 장 구조 자동 분석',
      },
      characterLibrary: {
        title: '👥 캐릭터 라이브러리',
        desc: 'AI를 통한 캐릭터 정보 자동 추출, 캐릭터 이미지 및 참조 이미지 생성',
      },
      storyboard: {
        title: '🎬 스마트 스토리보드',
        desc: '장을 자동으로 샷으로 분할하고 AI 드로잉 프롬프트 생성',
      },
      comfyUI: {
        title: '🎨 ComfyUI 통합',
        desc: '원클릭으로 ComfyUI에 전송하여 이미지와 비디오 생성',
      },
      workflow: {
        title: '⚡ 워크플로우 자동화',
        desc: '배치 생성 및 작업 큐 관리 지원',
      },
    },
  },
};