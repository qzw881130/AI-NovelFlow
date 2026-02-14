import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { 
  ArrowLeft, 
  Loader2,
  CheckCircle,
  RefreshCw,
  Download,
  Users,
  Image as ImageIcon,
  Video,
  FileJson,
  MapPin,
  Fullscreen,
  Play,
  ChevronLeft,
  ChevronRight,
  X
} from 'lucide-react';
import type { Chapter } from '../types';

// 静态数据
const MOCK_DATA = {
  chapter: {
    id: '1',
    title: '第一章：妈妈的嘱托',
    content: '小马和他的妈妈住在绿草茵茵的十分美丽的小河边。除了妈妈过河给河对岸的村子送粮食的时候，他总是跟随在妈妈的身边寸步不离。他过的很快乐，时光飞快地过去了。',
    status: 'generating_shots',
    progress: 65
  },
  result: {
    chapter: "第一章：妈妈的嘱托",
    characters: ["小马", "马妈妈"],
    scenes: ["小河边", "村庄"],
    shots: [
      {
        id: 1,
        description: "[全景] 一片绿草茵茵的美丽河边，小马和妈妈在河边吃草",
        characters: ["小马", "马妈妈"],
        scene: "小河边",
        duration: 5
      },
      {
        id: 2,
        description: "[中景] 马妈妈温柔地看着小马，准备交代任务",
        characters: ["马妈妈", "小马"],
        scene: "小河边",
        duration: 8
      },
      {
        id: 3,
        description: "[特写] 马妈妈的表情，充满关爱和期待",
        characters: ["马妈妈"],
        scene: "小河边",
        duration: 4
      },
      {
        id: 4,
        description: "[中景] 小马认真地点头，接受妈妈的嘱托",
        characters: ["小马"],
        scene: "小河边",
        duration: 6
      },
      {
        id: 5,
        description: "[远景] 马妈妈背着粮食，走向河对岸的村庄",
        characters: ["马妈妈"],
        scene: "村庄",
        duration: 7
      }
    ]
  },
  characters: [
    { id: 1, name: '小马', image: null, status: 'completed' },
    { id: 2, name: '马妈妈', image: null, status: 'completed' }
  ],
  shots: [
    { id: 1, image: null, status: 'completed', color: 'bg-purple-500' },
    { id: 2, image: null, status: 'completed', color: 'bg-emerald-500' },
    { id: 3, image: null, status: 'completed', color: 'bg-orange-500' },
    { id: 4, image: null, status: 'completed', color: 'bg-pink-500' },
    { id: 5, image: null, status: 'generating', color: 'bg-blue-500' }
  ],
  videos: [
    { id: 1, status: 'completed', duration: '00:05' },
    { id: 2, status: 'completed', duration: '00:08' },
    { id: 3, status: 'completed', duration: '00:04' },
    { id: 4, status: 'generating', duration: '00:00' },
    { id: 5, status: 'pending', duration: '00:00' }
  ],
  logs: [
    { time: '10:23:45', message: '开始解析文本...', type: 'info' },
    { time: '10:23:52', message: '✓ 成功提取2个角色、2个场景', type: 'success' },
    { time: '10:24:10', message: '开始生成角色"小马"人设图...', type: 'info' },
    { time: '10:25:30', message: '✓ 人设图生成完成', type: 'success' },
    { time: '10:25:35', message: '开始生成分镜图片...', type: 'info' },
    { time: '10:28:15', message: '✓ 分镜图片生成完成 (4/5)', type: 'success' },
    { time: '10:28:20', message: '→ 开始生成分镜视频...', type: 'info' },
    { time: '10:30:05', message: '✓ 镜1视频生成完成', type: 'success' },
    { time: '10:31:20', message: '✓ 镜2视频生成完成', type: 'success' }
  ],
  systemStatus: {
    comfyUI: 'online',
    gpuUsage: 85,
    vramUsed: 12.5,
    vramTotal: 16,
    queueTasks: 3
  }
};

// 步骤定义
const STEPS = [
  { key: 'parse', label: '解析文本', icon: FileJson },
  { key: 'character', label: '生成人设', icon: Users },
  { key: 'shots', label: '生成分镜图', icon: ImageIcon },
  { key: 'videos', label: '生成视频', icon: Video },
  { key: 'compose', label: '合成视频', icon: CheckCircle }
];

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function ChapterGenerate() {
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const [activeTab, setActiveTab] = useState<'json' | 'characters' | 'scenes' | 'script'>('json');
  const [currentShot, setCurrentShot] = useState(1);
  const [currentVideo, setCurrentVideo] = useState(1);
  const [isGenerating, setIsGenerating] = useState(false);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [loading, setLoading] = useState(true);
  const [showFullTextModal, setShowFullTextModal] = useState(false);

  // 获取真实章节数据
  useEffect(() => {
    if (cid) {
      fetchChapter();
    }
  }, [cid]);

  const fetchChapter = async () => {
    setLoading(true);
    try {
      // 使用正确的 API 路径：/api/novels/{novel_id}/chapters/{chapter_id}
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}`);
      const data = await res.json();
      if (data.success) {
        setChapter(data.data);
      }
    } catch (error) {
      console.error('获取章节数据失败:', error);
    } finally {
      setLoading(false);
    }
  };

  // 获取当前步骤索引
  const currentStepIndex = 3; // 模拟当前在"生成视频"步骤

  const handleRegenerate = () => {
    setIsGenerating(true);
    // 模拟生成过程
    setTimeout(() => setIsGenerating(false), 3000);
  };

  const renderStepIndicator = () => (
    <div className="card mb-6">
      <div className="flex items-center justify-between">
        {STEPS.map((step, index) => {
          const isCompleted = index < currentStepIndex;
          const isCurrent = index === currentStepIndex;
          const StepIcon = step.icon;
          
          return (
            <div key={step.key} className="flex items-center">
              <div className="flex flex-col items-center">
                <div className={`
                  w-10 h-10 rounded-full flex items-center justify-center mb-2
                  ${isCompleted ? 'bg-green-500 text-white' : ''}
                  ${isCurrent ? 'bg-purple-600 text-white ring-4 ring-purple-100' : ''}
                  ${!isCompleted && !isCurrent ? 'bg-gray-100 text-gray-400' : ''}
                `}>
                  {isCompleted ? (
                    <CheckCircle className="h-5 w-5" />
                  ) : (
                    <StepIcon className="h-5 w-5" />
                  )}
                </div>
                <span className={`text-xs font-medium ${isCurrent ? 'text-purple-600' : isCompleted ? 'text-green-600' : 'text-gray-400'}`}>
                  {step.label}
                </span>
              </div>
              {index < STEPS.length - 1 && (
                <div className={`w-16 h-0.5 mx-2 ${index < currentStepIndex ? 'bg-green-500' : 'bg-gray-200'}`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );

  const renderTabs = () => (
    <div className="flex gap-4 mb-4 border-b border-gray-200">
      {[
        { key: 'json', label: 'JSON' },
        { key: 'characters', label: '角色列表' },
        { key: 'scenes', label: '场景列表' },
        { key: 'script', label: '分镜脚本' }
      ].map(tab => (
        <button
          key={tab.key}
          onClick={() => setActiveTab(tab.key as any)}
          className={`pb-2 px-1 text-sm font-medium transition-colors ${
            activeTab === tab.key 
              ? 'text-blue-600 border-b-2 border-blue-600' 
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );

  const renderTabContent = () => {
    switch (activeTab) {
      case 'json':
        return (
          <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg text-xs overflow-x-auto">
            {JSON.stringify(MOCK_DATA.result, null, 2)}
          </pre>
        );
      case 'characters':
        return (
          <div className="space-y-2">
            {MOCK_DATA.result.characters.map((name, idx) => (
              <div key={idx} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                <Users className="h-5 w-5 text-blue-500" />
                <span className="font-medium">{name}</span>
              </div>
            ))}
          </div>
        );
      case 'scenes':
        return (
          <div className="space-y-2">
            {MOCK_DATA.result.scenes.map((name, idx) => (
              <div key={idx} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                <MapPin className="h-5 w-5 text-green-500" />
                <span className="font-medium">{name}</span>
              </div>
            ))}
          </div>
        );
      case 'script':
        return (
          <div className="space-y-3">
            {MOCK_DATA.result.shots.map((shot) => (
              <div key={shot.id} className="p-3 bg-gray-50 rounded-lg border-l-4 border-purple-500">
                <div className="flex justify-between items-start mb-1">
                  <span className="font-medium text-sm">镜{shot.id}</span>
                  <span className="text-xs text-gray-500">{shot.duration}秒</span>
                </div>
                <p className="text-sm text-gray-700">{shot.description}</p>
                <div className="flex gap-2 mt-2">
                  {shot.characters.map(c => (
                    <span key={c} className="text-xs px-2 py-1 bg-blue-100 text-blue-600 rounded">{c}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link 
            to={`/novels/${id}`}
            className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              {loading ? '加载中...' : chapter?.title || '未命名章节'}
            </h1>
            <p className="text-sm text-gray-500">AI动画生成中...</p>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleRegenerate}
            disabled={isGenerating}
            className="btn-secondary"
          >
            {isGenerating ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            重新生成
          </button>
          <button className="btn-primary bg-gradient-to-r from-purple-600 to-blue-600">
            <Download className="h-4 w-4 mr-2" />
            下载视频
          </button>
        </div>
      </div>

      {/* 步骤指示器 */}
      {renderStepIndicator()}

      <div className="grid grid-cols-12 gap-6">
        {/* 左侧内容区 */}
        <div className="col-span-8 space-y-6">
          {/* 原文内容 */}
          <div className="card">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-gray-900">原文内容</h3>
              <button 
                onClick={() => setShowFullTextModal(true)}
                className="text-sm text-blue-600 hover:underline"
              >
                展开全文
              </button>
            </div>
            <p className="text-gray-600 text-sm leading-relaxed line-clamp-3">
              {loading ? '加载中...' : chapter?.content || '暂无内容'}
            </p>
          </div>

          {/* JSON/角色/场景/脚本 标签页 */}
          <div className="card">
            {renderTabs()}
            <div className="mt-4 max-h-64 overflow-y-auto">
              {renderTabContent()}
            </div>
          </div>

          {/* 人设图片 */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">人设图片</h3>
            <div className="flex gap-4">
              {MOCK_DATA.characters.map((char) => (
                <div key={char.id} className="text-center">
                  <div className="w-24 h-24 rounded-xl bg-gradient-to-br from-blue-400 to-purple-500 flex items-center justify-center mb-2">
                    <Users className="h-10 w-10 text-white" />
                  </div>
                  <p className="text-sm font-medium">{char.name}</p>
                  <button className="text-xs text-blue-600 hover:underline mt-1">
                    重新生成
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* 分镜图片 */}
          <div className="card">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-gray-900">分镜图片 (5张)</h3>
              <div className="flex items-center gap-2">
                <button 
                  onClick={() => setCurrentShot(Math.max(1, currentShot - 1))}
                  className="p-1 rounded hover:bg-gray-100"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm text-gray-500">{currentShot}/5</span>
                <button 
                  onClick={() => setCurrentShot(Math.min(5, currentShot + 1))}
                  className="p-1 rounded hover:bg-gray-100"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-2">
              {MOCK_DATA.shots.map((shot) => (
                <div 
                  key={shot.id}
                  onClick={() => setCurrentShot(shot.id)}
                  className={`flex-shrink-0 w-32 h-24 rounded-lg ${shot.color} flex items-center justify-center cursor-pointer transition-transform hover:scale-105 ${
                    currentShot === shot.id ? 'ring-2 ring-offset-2 ring-gray-400' : ''
                  }`}
                >
                  <ImageIcon className="h-8 w-8 text-white/70" />
                  <span className="absolute bottom-1 left-2 text-xs text-white/90">镜{shot.id}</span>
                  {shot.status === 'generating' && (
                    <Loader2 className="absolute top-1 right-1 h-3 w-3 text-white animate-spin" />
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-3 mt-4">
              <button className="btn-secondary text-sm py-1.5">
                <Fullscreen className="h-3 w-3 mr-1" />
                全屏查看
              </button>
              <button className="btn-secondary text-sm py-1.5">
                <RefreshCw className="h-3 w-3 mr-1" />
                重新生成
              </button>
            </div>
          </div>

          {/* 分镜视频 */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">分镜视频</h3>
            <div className="aspect-video bg-gray-900 rounded-lg flex items-center justify-center mb-4">
              <div className="text-center">
                <Play className="h-16 w-16 text-white/50 mx-auto mb-2" />
                <p className="text-white/50 text-sm">预览播放器</p>
              </div>
            </div>
            <div className="flex gap-2 flex-wrap">
              {MOCK_DATA.videos.map((video) => (
                <button
                  key={video.id}
                  onClick={() => setCurrentVideo(video.id)}
                  className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                    currentVideo === video.id 
                      ? 'bg-purple-100 text-purple-600' 
                      : video.status === 'completed'
                        ? 'bg-gray-100 text-gray-700'
                        : video.status === 'generating'
                          ? 'bg-pink-50 text-pink-600'
                          : 'bg-gray-50 text-gray-400'
                  }`}
                >
                  {video.status === 'generating' && <Loader2 className="h-3 w-3 inline mr-1 animate-spin" />}
                  镜{video.id}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 右侧边栏 */}
        <div className="col-span-4 space-y-6">
          {/* 生成日志 */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">生成日志</h3>
            <div className="space-y-3 max-h-64 overflow-y-auto">
              {MOCK_DATA.logs.map((log, idx) => (
                <div key={idx} className="flex gap-3 text-sm">
                  <span className="text-gray-400 flex-shrink-0">{log.time}</span>
                  <span className={
                    log.type === 'success' ? 'text-green-600' : 
                    log.type === 'error' ? 'text-red-600' : 
                    'text-blue-600'
                  }>
                    {log.message}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* 系统状态 */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">系统状态</h3>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">ComfyUI</span>
                <span className="flex items-center text-sm text-green-600">
                  <span className="w-2 h-2 bg-green-500 rounded-full mr-1" />
                  在线
                </span>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">GPU使用率</span>
                  <span className="font-medium">{MOCK_DATA.systemStatus.gpuUsage}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div 
                    className="bg-green-500 h-2 rounded-full"
                    style={{ width: `${MOCK_DATA.systemStatus.gpuUsage}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">显存占用</span>
                  <span className="font-medium">{MOCK_DATA.systemStatus.vramUsed} / {MOCK_DATA.systemStatus.vramTotal} GB</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div 
                    className="bg-blue-500 h-2 rounded-full"
                    style={{ width: `${(MOCK_DATA.systemStatus.vramUsed / MOCK_DATA.systemStatus.vramTotal) * 100}%` }}
                  />
                </div>
              </div>
              <div className="flex justify-between items-center pt-2 border-t">
                <span className="text-sm text-gray-600">队列任务</span>
                <span className="font-medium">{MOCK_DATA.systemStatus.queueTasks}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 展开全文弹层 */}
      {showFullTextModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-6 border-b">
              <h3 className="text-lg font-semibold text-gray-900">原文内容</h3>
              <button
                onClick={() => setShowFullTextModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto flex-1">
              <h2 className="text-xl font-bold text-gray-900 mb-4">
                {chapter?.title || '未命名章节'}
              </h2>
              <div className="prose prose-gray max-w-none">
                <p className="text-gray-700 leading-loose whitespace-pre-wrap text-base">
                  {chapter?.content || '暂无内容'}
                </p>
              </div>
            </div>
            <div className="p-6 border-t bg-gray-50 flex justify-end">
              <button
                onClick={() => setShowFullTextModal(false)}
                className="btn-secondary"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
