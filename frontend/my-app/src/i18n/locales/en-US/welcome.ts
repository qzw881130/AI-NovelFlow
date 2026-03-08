// Welcome page translations
export default {
  // Welcome page
  welcome: {
    title: 'Welcome to NovelFlow',
    subtitle: 'AI-powered Novel to Animation/Video Workflow',
    features: {
      novelManagement: {
        title: '📚 Novel Management',
        desc: 'Upload and manage novel texts, support TXT and EPUB formats, auto-parse chapter structure',
      },
      characterLibrary: {
        title: '👥 Character Library',
        desc: 'AI automatically extracts character info and generates character portraits and reference images',
      },
      storyboard: {
        title: '🎬 Smart Storyboard',
        desc: 'Automatically split chapters into shots and generate AI drawing prompts',
      },
      comfyUI: {
        title: '🎨 ComfyUI Integration',
        desc: 'One-click send to ComfyUI to generate images and videos',
      },
      workflow: {
        title: '⚡ Workflow Automation',
        desc: 'Support batch generation and task queue management',
      },
    },
    getStarted: 'Get Started',
    quickActions: 'Quick Actions',
    recentNovels: 'Recent Novels',
    systemStatus: 'System Status',
    pleaseConfigure: 'Please complete system configuration before using NovelFlow.',

    // Workflow nodes
    workflow: {
      importNovel: 'Import Novel',
      parseCharacters: 'AI Parse Characters',
      parseScenes: 'AI Parse Scenes',
      parseProps: 'AI Parse Props',
      generateCharacters: 'Generate Character Images',
      generateScenes: 'Generate Scene Images',
      generateProps: 'Generate Prop Images',
      editChapter: 'Edit Chapter',
      splitShots: 'AI Split Shots',
      generateShotImages: 'Generate Shot Images',
      generateAudio: 'Generate Audio',
      generateVideo: 'Generate Video',
    },
  },
};