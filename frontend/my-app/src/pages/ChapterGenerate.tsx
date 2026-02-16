import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
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
  X,
  Sparkles,
  Save,
  Grid3x3,
  Clock,
  Film,
  Settings,
  Package,
  Code,
  Plus,
  Trash2,
  AlertCircle,
  FileText
} from 'lucide-react';
import type { Chapter, Novel } from '../types';
import { toast } from '../stores/toastStore';
import ComfyUIStatus from '../components/ComfyUIStatus';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 章节素材下载组件
function DownloadMaterialsCard({ 
  novelId, 
  chapterId, 
  chapterTitle 
}: { 
  novelId: string; 
  chapterId: string; 
  chapterTitle: string;
}) {
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownload = async () => {
    if (!novelId || !chapterId) {
      toast('章节信息不完整', 'error');
      return;
    }

    setIsDownloading(true);
    try {
      const response = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/download-materials/`
      );

      if (!response.ok) {
        if (response.status === 404) {
          toast('章节素材不存在', 'error');
        } else {
          toast('下载失败', 'error');
        }
        return;
      }

      // 获取文件名
      const contentDisposition = response.headers.get('content-disposition');
      let filename = `${chapterTitle}_materials.zip`;
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?(.+?)"?$/);
        if (match) {
          filename = match[1];
        }
      }

      // 下载文件
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      toast('素材包下载成功', 'success');
    } catch (error) {
      console.error('Download error:', error);
      toast('下载失败', 'error');
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="p-4 border-b border-gray-100 bg-gradient-to-r from-blue-50 to-purple-50">
        <div className="flex items-center gap-2">
          <Package className="h-5 w-5 text-blue-600" />
          <h3 className="font-semibold text-gray-900">章节素材</h3>
        </div>
      </div>
      <div className="p-4">
        <p className="text-sm text-gray-500 mb-4">
          打包下载当前章节的所有素材，包括：
        </p>
        <ul className="text-sm text-gray-600 space-y-1 mb-4">
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            合并角色图
          </li>
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
            分镜图片
          </li>
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-purple-400" />
            分镜视频
          </li>
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-orange-400" />
            转场视频
          </li>
        </ul>
        <button
          onClick={handleDownload}
          disabled={isDownloading}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isDownloading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              打包中...
            </>
          ) : (
            <>
              <Download className="h-4 w-4" />
              下载素材包
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// JSON表格编辑器组件
interface JsonTableEditorProps {
  value: string;
  onChange: (value: string) => void;
}

function JsonTableEditor({ value, onChange }: JsonTableEditorProps) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string>('');
  const [activeSection, setActiveSection] = useState<'characters' | 'scenes' | 'shots'>('shots');

  // 解析JSON
  useEffect(() => {
    try {
      if (value.trim()) {
        const parsed = JSON.parse(value);
        setData(parsed);
        setError('');
      } else {
        setData(null);
      }
    } catch (e) {
      setError('JSON格式错误，请检查文本模式');
    }
  }, [value]);

  // 更新JSON
  const updateJson = (newData: any) => {
    setData(newData);
    onChange(JSON.stringify(newData, null, 2));
  };

  // 更新角色
  const updateCharacter = (index: number, value: string) => {
    if (!data) return;
    const newCharacters = [...(data.characters || [])];
    newCharacters[index] = value;
    updateJson({ ...data, characters: newCharacters });
  };

  // 添加角色
  const addCharacter = () => {
    if (!data) return;
    const newCharacters = [...(data.characters || []), '新角色'];
    updateJson({ ...data, characters: newCharacters });
  };

  // 删除角色
  const removeCharacter = (index: number) => {
    if (!data) return;
    const newCharacters = (data.characters || []).filter((_: any, i: number) => i !== index);
    updateJson({ ...data, characters: newCharacters });
  };

  // 更新场景
  const updateScene = (index: number, value: string) => {
    if (!data) return;
    const newScenes = [...(data.scenes || [])];
    newScenes[index] = value;
    updateJson({ ...data, scenes: newScenes });
  };

  // 添加场景
  const addScene = () => {
    if (!data) return;
    const newScenes = [...(data.scenes || []), '新场景'];
    updateJson({ ...data, scenes: newScenes });
  };

  // 删除场景
  const removeScene = (index: number) => {
    if (!data) return;
    const newScenes = (data.scenes || []).filter((_: any, i: number) => i !== index);
    updateJson({ ...data, scenes: newScenes });
  };

  // 更新分镜
  const updateShot = (index: number, field: string, value: any) => {
    if (!data) return;
    const newShots = [...(data.shots || [])];
    newShots[index] = { ...newShots[index], [field]: value };
    updateJson({ ...data, shots: newShots });
  };

  // 添加分镜
  const addShot = () => {
    if (!data) return;
    const newShot = {
      id: (data.shots?.length || 0) + 1,
      description: '新分镜描述',
      characters: [],
      scene: '',
      duration: 4
    };
    updateJson({ ...data, shots: [...(data.shots || []), newShot] });
  };

  // 删除分镜
  const removeShot = (index: number) => {
    if (!data) return;
    const newShots = (data.shots || []).filter((_: any, i: number) => i !== index);
    // 重新编号
    newShots.forEach((shot: any, i: number) => { shot.id = i + 1; });
    updateJson({ ...data, shots: newShots });
  };

  if (error) {
    return (
      <div className="h-64 flex items-center justify-center bg-red-50 rounded-lg border border-red-200">
        <div className="text-center">
          <AlertCircle className="h-8 w-8 text-red-400 mx-auto mb-2" />
          <p className="text-red-600 text-sm">{error}</p>
          <p className="text-gray-500 text-xs mt-1">请切换到JSON文本模式检查</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="h-64 flex items-center justify-center bg-gray-50 rounded-lg border border-gray-200">
        <p className="text-gray-400 text-sm">暂无数据，请先进行AI拆分</p>
      </div>
    );
  }

  return (
    <div className="h-96 flex flex-col bg-white rounded-lg border border-gray-200 overflow-hidden">
      {/* 标签切换 */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveSection('shots')}
          className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
            activeSection === 'shots' 
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' 
              : 'text-gray-600 hover:bg-gray-50'
          }`}
        >
          分镜 ({data.shots?.length || 0})
        </button>
        <button
          onClick={() => setActiveSection('characters')}
          className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
            activeSection === 'characters' 
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' 
              : 'text-gray-600 hover:bg-gray-50'
          }`}
        >
          角色 ({data.characters?.length || 0})
        </button>
        <button
          onClick={() => setActiveSection('scenes')}
          className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
            activeSection === 'scenes' 
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' 
              : 'text-gray-600 hover:bg-gray-50'
          }`}
        >
          场景 ({data.scenes?.length || 0})
        </button>
      </div>

      {/* 内容区域 */}
      <div className="flex-1 overflow-auto p-4">
        {activeSection === 'characters' && (
          <div className="space-y-2">
            {data.characters?.map((char: string, idx: number) => (
              <div key={idx} className="flex items-center gap-2">
                <Users className="h-4 w-4 text-blue-500 flex-shrink-0" />
                <input
                  type="text"
                  value={char}
                  onChange={(e) => updateCharacter(idx, e.target.value)}
                  className="flex-1 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
                <button
                  onClick={() => removeCharacter(idx)}
                  className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-md"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            <button
              onClick={addCharacter}
              className="w-full py-2 border border-dashed border-gray-300 rounded-md text-gray-500 hover:border-blue-400 hover:text-blue-600 text-sm flex items-center justify-center gap-1"
            >
              <Plus className="h-4 w-4" />
              添加角色
            </button>
          </div>
        )}

        {activeSection === 'scenes' && (
          <div className="space-y-2">
            {data.scenes?.map((scene: string, idx: number) => (
              <div key={idx} className="flex items-center gap-2">
                <MapPin className="h-4 w-4 text-green-500 flex-shrink-0" />
                <input
                  type="text"
                  value={scene}
                  onChange={(e) => updateScene(idx, e.target.value)}
                  className="flex-1 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
                <button
                  onClick={() => removeScene(idx)}
                  className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-md"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            <button
              onClick={addScene}
              className="w-full py-2 border border-dashed border-gray-300 rounded-md text-gray-500 hover:border-blue-400 hover:text-blue-600 text-sm flex items-center justify-center gap-1"
            >
              <Plus className="h-4 w-4" />
              添加场景
            </button>
          </div>
        )}

        {activeSection === 'shots' && (
          <div className="space-y-3">
            {data.shots?.map((shot: any, idx: number) => (
              <div key={idx} className="border border-gray-200 rounded-lg p-3 bg-gray-50">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm">镜{shot.id}</span>
                  <button
                    onClick={() => removeShot(idx)}
                    className="p-1 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <div className="space-y-2">
                  <textarea
                    value={shot.description}
                    onChange={(e) => updateShot(idx, 'description', e.target.value)}
                    placeholder="分镜描述"
                    className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none resize-none"
                    rows={2}
                  />
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={shot.scene}
                      onChange={(e) => updateShot(idx, 'scene', e.target.value)}
                      placeholder="场景"
                      className="flex-1 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    />
                    <input
                      type="number"
                      value={shot.duration}
                      onChange={(e) => updateShot(idx, 'duration', parseInt(e.target.value) || 4)}
                      placeholder="时长(秒)"
                      className="w-24 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    />
                  </div>
                  <input
                    type="text"
                    value={shot.characters?.join(', ')}
                    onChange={(e) => updateShot(idx, 'characters', e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean))}
                    placeholder="角色（用逗号分隔）"
                    className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                  />
                </div>
              </div>
            ))}
            <button
              onClick={addShot}
              className="w-full py-2 border border-dashed border-gray-300 rounded-md text-gray-500 hover:border-blue-400 hover:text-blue-600 text-sm flex items-center justify-center gap-1"
            >
              <Plus className="h-4 w-4" />
              添加分镜
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// 合并视频组件
function MergeVideosCard({
  novelId,
  chapterId,
  shotVideos,
  transitionVideos,
  chapter
}: {
  novelId: string;
  chapterId: string;
  shotVideos: Record<number, string>;
  transitionVideos: Record<string, string>;
  chapter: Chapter | null;
}) {
  const [isMerging, setIsMerging] = useState(false);
  const [mergedVideoUrl, setMergedVideoUrl] = useState<string | null>(null);
  const [includeTransitions, setIncludeTransitions] = useState(true);

  const videoList = Object.values(shotVideos).filter(Boolean);
  const hasVideos = videoList.length > 0;
  const hasTransitions = Object.keys(transitionVideos).length > 0;

  const handleMerge = async () => {
    if (!novelId || !chapterId || videoList.length === 0) {
      toast('没有可合并的视频', 'error');
      return;
    }

    setIsMerging(true);
    try {
      const response = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/merge-videos/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ include_transitions: includeTransitions })
        }
      );

      const data = await response.json();
      
      if (data.success) {
        setMergedVideoUrl(data.video_url);
        toast('视频合并成功', 'success');
      } else {
        toast(data.message || '合并失败', 'error');
      }
    } catch (error) {
      console.error('Merge error:', error);
      toast('合并失败', 'error');
    } finally {
      setIsMerging(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="p-4 border-b border-gray-100 bg-gradient-to-r from-purple-50 to-pink-50">
        <div className="flex items-center gap-2">
          <Film className="h-5 w-5 text-purple-600" />
          <h3 className="font-semibold text-gray-900">合并视频</h3>
        </div>
      </div>
      <div className="p-4">
        {!hasVideos ? (
          <p className="text-sm text-gray-500">暂无分镜视频</p>
        ) : (
          <>
            <p className="text-sm text-gray-500 mb-3">
              已生成 {videoList.length} 个分镜视频
              {hasTransitions && `，${Object.keys(transitionVideos).length} 个转场视频`}
            </p>
            
            {/* 选项 */}
            <div className="space-y-2 mb-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={!includeTransitions}
                  onChange={() => setIncludeTransitions(false)}
                  className="w-4 h-4 text-purple-600"
                />
                <span className="text-sm text-gray-700">仅合并分镜视频</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={includeTransitions}
                  onChange={() => setIncludeTransitions(true)}
                  disabled={!hasTransitions}
                  className="w-4 h-4 text-purple-600 disabled:opacity-50"
                />
                <span className={`text-sm ${hasTransitions ? 'text-gray-700' : 'text-gray-400'}`}>
                  合并分镜+转场视频
                </span>
              </label>
            </div>

            {/* 合并按钮 */}
            <button
              onClick={handleMerge}
              disabled={isMerging}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isMerging ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  合并中...
                </>
              ) : (
                <>
                  <Film className="h-4 w-4" />
                  {includeTransitions ? '合并分镜+转场' : '仅合并分镜'}
                </>
              )}
            </button>

            {/* 合并后的视频播放器 */}
            {mergedVideoUrl && (
              <div className="mt-4 pt-4 border-t border-gray-100">
                <p className="text-sm font-medium text-gray-700 mb-2">合并结果</p>
                <video
                  src={mergedVideoUrl}
                  controls
                  className="w-full rounded-lg bg-gray-900"
                  style={{ aspectRatio: chapter?.novel?.aspectRatio === '9:16' ? '9/16' : '16/9' }}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// 步骤定义 - 每个步骤有独特的颜色主题
const STEPS = [
  { key: 'content', label: '原文内容', icon: FileText, color: 'from-blue-500 to-cyan-500' },
  { key: 'ai-parse', label: 'AI拆分分镜头', icon: Sparkles, color: 'from-purple-500 to-pink-500' },
  { key: 'json', label: 'JSON结构', icon: FileJson, color: 'from-emerald-500 to-teal-500' },
  { key: 'character', label: '生成合并角色图', icon: Users, color: 'from-orange-500 to-amber-500' },
  { key: 'shots', label: '生成分镜图片', icon: ImageIcon, color: 'from-rose-500 to-pink-500' },
  { key: 'videos', label: '生成分镜视频', icon: Video, color: 'from-indigo-500 to-violet-500' },
  { key: 'transitions', label: '生成分镜转场视频', icon: Film, color: 'from-cyan-500 to-blue-500' },
  { key: 'compose', label: '合并视频', icon: CheckCircle, color: 'from-green-500 to-emerald-500' }
];

interface Character {
  id: string;
  name: string;
  imageUrl: string | null;
  novelId: string;
}

// 转场视频项组件
interface TransitionVideoItemProps {
  fromIndex: number;
  toIndex: number;
  fromVideo?: string;
  toVideo?: string;
  fromImage?: string;
  toImage?: string;
  transitionVideo?: string;
  isGenerating: boolean;
  onGenerate: () => void;
  onRegenerate?: () => void;
  onClick: () => void;
  isActive: boolean;
}

function TransitionVideoItem({
  fromIndex,
  toIndex,
  fromVideo,
  toVideo,
  fromImage,
  toImage,
  transitionVideo,
  isGenerating,
  onGenerate,
  onRegenerate,
  onClick,
  isActive
}: TransitionVideoItemProps) {
  const hasVideos = !!fromVideo && !!toVideo;
  const hasTransition = !!transitionVideo;
  
  return (
    <div 
      className={`relative flex-shrink-0 flex flex-col items-center gap-1 ${isActive ? 'opacity-100' : 'opacity-80 hover:opacity-100'}`}
    >
      {/* 转场缩略图 */}
      <div
        onClick={hasTransition ? onClick : undefined}
        className={`relative w-16 h-16 rounded-lg overflow-hidden cursor-pointer transition-all ${
          isActive ? 'ring-2 ring-offset-2 ring-orange-500' : ''
        } ${!hasTransition ? 'grayscale' : ''}`}
      >
        {/* 两张图片拼接 */}
        <div className="flex h-full">
          <div className="w-1/2 relative">
            {fromImage ? (
              <img src={fromImage} alt={`镜${fromIndex}`} className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full bg-gray-200" />
            )}
            <div className="absolute bottom-0 left-0 bg-black/60 text-white text-[8px] px-1">
              {fromIndex}
            </div>
          </div>
          <div className="w-1/2 relative">
            {toImage ? (
              <img src={toImage} alt={`镜${toIndex}`} className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full bg-gray-200" />
            )}
            <div className="absolute bottom-0 right-0 bg-black/60 text-white text-[8px] px-1">
              {toIndex}
            </div>
          </div>
        </div>
        
        {/* 箭头覆盖层 */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className={`rounded-full p-1 ${hasTransition ? 'bg-orange-500' : 'bg-gray-400'}`}>
            <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </div>
        </div>
        
        {/* 生成中状态 */}
        {isGenerating && (
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
            <Loader2 className="h-5 w-5 text-white animate-spin" />
          </div>
        )}
      </div>
      
      {/* 状态标签 */}
      <div className="flex flex-col items-center gap-0.5">
        {hasTransition ? (
          <div className="flex flex-col items-center gap-0.5">
            <span className="text-[9px] text-green-600 font-medium">已生成</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRegenerate?.();
              }}
              disabled={isGenerating}
              className="text-[9px] bg-orange-500 text-white px-2 py-0.5 rounded hover:bg-orange-600 disabled:opacity-50 transition-colors"
              title="重新生成转场视频"
            >
              重新生成
            </button>
          </div>
        ) : isGenerating ? (
          <span className="text-[9px] text-orange-600">生成中...</span>
        ) : (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onGenerate();
            }}
            disabled={!hasVideos || isGenerating}
            className="text-[9px] bg-orange-500 text-white px-2 py-0.5 rounded hover:bg-orange-600 disabled:opacity-50 disabled:bg-gray-300 transition-colors"
            title={!hasVideos ? '请先生成视频' : '生成转场视频'}
          >
            生成
          </button>
        )}
      </div>
    </div>
  );
}

export default function ChapterGenerate() {
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<'json' | 'characters' | 'scenes' | 'script'>('json');
  const [currentShot, setCurrentShot] = useState(1);
  const [currentVideo, setCurrentVideo] = useState(1);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSplitting, setIsSplitting] = useState(false);
  const [isSavingJson, setIsSavingJson] = useState(false);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [loading, setLoading] = useState(true);
  const [showFullTextModal, setShowFullTextModal] = useState(false);
  
  // 解析后的数据
  const [parsedData, setParsedData] = useState<any>(null);
  // 可编辑的JSON文本
  const [editableJson, setEditableJson] = useState<string>('');
  // JSON编辑模式：文本或表格
  const [jsonEditMode, setJsonEditMode] = useState<'text' | 'table'>('text');
  // 角色列表（从角色库获取）
  const [characters, setCharacters] = useState<Character[]>([]);

  // 小说数据
  const [novel, setNovel] = useState<Novel | null>(null);

  // 合并角色图相关
  const [mergedImage, setMergedImage] = useState<string | null>(null);
  const [isMerging, setIsMerging] = useState(false);
  const [showMergedImageModal, setShowMergedImageModal] = useState(false);
  const [showImagePreview, setShowImagePreview] = useState(false);
  const [previewImageUrl, setPreviewImageUrl] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // 分镜图片生成相关
  const [generatingShots, setGeneratingShots] = useState<Set<number>>(new Set());
  const [pendingShots, setPendingShots] = useState<Set<number>>(new Set());  // 已提交到队列的任务
  const [isGeneratingAll, setIsGeneratingAll] = useState(false);  // 批量生成中
  const [shotImages, setShotImages] = useState<Record<number, string>>({});

  // 分镜视频生成相关
  const [generatingVideos, setGeneratingVideos] = useState<Set<number>>(new Set());
  const [pendingVideos, setPendingVideos] = useState<Set<number>>(new Set());
  const [shotVideos, setShotVideos] = useState<Record<number, string>>({});  // 分镜视频URL映射

  // 转场视频生成相关
  const [transitionVideos, setTransitionVideos] = useState<Record<string, string>>({});  // {"1-2": url}
  const [generatingTransitions, setGeneratingTransitions] = useState<Set<string>>(new Set());  // {"1-2"}
  const [currentTransition, setCurrentTransition] = useState<string>("");  // 当前选中的转场，如 "1-2"
  
  // 转场配置
  const [transitionWorkflows, setTransitionWorkflows] = useState<any[]>([]);  // 转场工作流列表
  const [selectedTransitionWorkflow, setSelectedTransitionWorkflow] = useState<string>("");  // 选中的工作流ID
  const [transitionDuration, setTransitionDuration] = useState<number>(2);  // 转场时长（秒）默认2秒
  const [showTransitionConfig, setShowTransitionConfig] = useState<boolean>(false);  // 是否显示配置面板

  // 生成分镜图片
  const handleGenerateShotImage = async (shotIndex: number) => {
    setGeneratingShots(prev => new Set(prev).add(shotIndex));
    
    try {
      const res = await fetch(
        `${API_BASE}/novels/${id}/chapters/${cid}/shots/${shotIndex}/generate/`,
        { method: 'POST' }
      );
      const data = await res.json();
      
      if (data.success) {
        // 任务已创建，添加到 pending 状态
        setPendingShots(prev => new Set(prev).add(shotIndex));
        toast.success(data.message || '分镜图生成任务已创建');
      } else if (data.message?.includes('已有进行中的生成任务')) {
        toast.info(data.message);
      } else {
        toast.error(data.message || '生成失败');
      }
    } catch (error) {
      console.error('生成分镜图片失败:', error);
      toast.error('生成失败，请检查网络连接');
    } finally {
      setGeneratingShots(prev => {
        const next = new Set(prev);
        next.delete(shotIndex);
        return next;
      });
    }
  };

  // 批量生成所有分镜图片
  const handleGenerateAllShots = async () => {
    if (!parsedData?.shots || parsedData.shots.length === 0) {
      toast.warning('没有可分镜生成的图片');
      return;
    }
    
    const totalShots = parsedData.shots.length;
    
    // 检查是否已有进行中的任务
    if (pendingShots.size > 0) {
      toast.info(`已有 ${pendingShots.size} 个分镜在队列中，请等待完成后再试`);
      return;
    }
    
    setIsGeneratingAll(true);
    toast.info(`开始批量生成 ${totalShots} 个分镜图片...`);
    
    let successCount = 0;
    let skipCount = 0;
    let failCount = 0;
    
    // 串行提交所有分镜生成任务
    for (let i = 0; i < totalShots; i++) {
      const shotIndex = i + 1;
      
      try {
        setGeneratingShots(prev => new Set(prev).add(shotIndex));
        
        const res = await fetch(
          `${API_BASE}/novels/${id}/chapters/${cid}/shots/${shotIndex}/generate/`,
          { method: 'POST' }
        );
        const data = await res.json();
        
        if (data.success) {
          setPendingShots(prev => new Set(prev).add(shotIndex));
          successCount++;
        } else if (data.message?.includes('已有进行中的生成任务')) {
          skipCount++;
        } else {
          failCount++;
          console.error(`分镜 ${shotIndex} 生成失败:`, data.message);
        }
      } catch (error) {
        failCount++;
        console.error(`分镜 ${shotIndex} 生成请求失败:`, error);
      } finally {
        setGeneratingShots(prev => {
          const next = new Set(prev);
          next.delete(shotIndex);
          return next;
        });
      }
      
      // 小延迟避免请求过快
      if (i < totalShots - 1) {
        await new Promise(resolve => setTimeout(resolve, 200));
      }
    }
    
    setIsGeneratingAll(false);
    
    // 显示汇总结果
    if (successCount > 0) {
      toast.success(`成功提交 ${successCount} 个分镜生成任务`);
    }
    if (skipCount > 0) {
      toast.info(`${skipCount} 个分镜已在队列中`);
    }
    if (failCount > 0) {
      toast.error(`${failCount} 个分镜提交失败`);
    }
  };

  // 批量生成所有分镜视频
  const handleGenerateAllVideos = async () => {
    if (!parsedData?.shots || parsedData.shots.length === 0) {
      toast.warning('没有可分镜的视频');
      return;
    }
    
    // 找出所有已有分镜图片的分镜
    const shotsWithImages: number[] = [];
    parsedData.shots.forEach((_: any, index: number) => {
      const shotNum = index + 1;
      const hasImage = shotImages[shotNum] || parsedData.shots[index]?.image_url;
      const isPending = pendingVideos.has(shotNum);
      const isGenerating = generatingVideos.has(shotNum);
      if (hasImage && !isPending && !isGenerating) {
        shotsWithImages.push(shotNum);
      }
    });
    
    if (shotsWithImages.length === 0) {
      toast.warning('没有可生成视频的分镜（请确保分镜图片已生成）');
      return;
    }
    
    toast.info(`开始批量生成 ${shotsWithImages.length} 个分镜视频...`);
    
    let successCount = 0;
    let skipCount = 0;
    let failCount = 0;
    
    // 串行提交所有视频生成任务
    for (let i = 0; i < shotsWithImages.length; i++) {
      const shotIndex = shotsWithImages[i];
      
      try {
        setGeneratingVideos(prev => new Set(prev).add(shotIndex));
        
        const res = await fetch(
          `${API_BASE}/novels/${id}/chapters/${cid}/shots/${shotIndex}/generate-video/`,
          { method: 'POST' }
        );
        const data = await res.json();
        
        if (data.success) {
          setPendingVideos(prev => new Set(prev).add(shotIndex));
          successCount++;
        } else if (data.message?.includes('已有进行中的')) {
          skipCount++;
        } else {
          failCount++;
          console.error(`分镜 ${shotIndex} 视频生成失败:`, data.message);
        }
      } catch (error) {
        failCount++;
        console.error(`分镜 ${shotIndex} 视频生成请求失败:`, error);
      } finally {
        setGeneratingVideos(prev => {
          const next = new Set(prev);
          next.delete(shotIndex);
          return next;
        });
      }
      
      // 小延迟避免请求过快
      if (i < shotsWithImages.length - 1) {
        await new Promise(resolve => setTimeout(resolve, 200));
      }
    }
    
    // 显示汇总结果
    if (successCount > 0) {
      toast.success(`成功提交 ${successCount} 个视频生成任务`);
    }
    if (skipCount > 0) {
      toast.info(`${skipCount} 个分镜已在队列中`);
    }
    if (failCount > 0) {
      toast.error(`${failCount} 个分镜提交失败`);
    }
  };

  // 生成分镜视频
  const handleGenerateShotVideo = async (shotIndex: number) => {
    console.log('[ChapterGenerate] Generating video for shot', shotIndex);
    setGeneratingVideos(prev => new Set(prev).add(shotIndex));
    
    try {
      const res = await fetch(
        `${API_BASE}/novels/${id}/chapters/${cid}/shots/${shotIndex}/generate-video/`,
        { method: 'POST' }
      );
      const data = await res.json();
      
      console.log('[ChapterGenerate] Video generation response:', data);
      
      if (data.success) {
        setPendingVideos(prev => {
          const next = new Set(prev);
          next.add(shotIndex);
          console.log('[ChapterGenerate] Added to pending videos:', shotIndex, 'pending:', [...next]);
          return next;
        });
        toast.success(data.message || '视频生成任务已创建');
      } else if (data.message?.includes('已有进行中的')) {
        toast.info(data.message);
      } else {
        toast.error(data.message || '创建视频生成任务失败');
      }
    } catch (error) {
      console.error('创建视频生成任务失败:', error);
      toast.error('创建视频生成任务失败，请检查网络连接');
    } finally {
      setGeneratingVideos(prev => {
        const next = new Set(prev);
        next.delete(shotIndex);
        return next;
      });
    }
  };

  // 获取真实章节数据和角色列表
  useEffect(() => {
    if (cid && id) {
      fetchNovel();
      fetchCharacters();
      // fetchChapter 会在内部调用 fetchShotTasks
      fetchChapter();
      // 加载转场工作流列表
      fetchTransitionWorkflows();
    }
  }, [cid, id]);

  // 切换分镜时更新合并角色图
  useEffect(() => {
    if (parsedData?.shots && parsedData.shots.length >= currentShot) {
      const shot = parsedData.shots[currentShot - 1];
      if (shot?.merged_character_image) {
        setMergedImage(shot.merged_character_image);
      } else {
        setMergedImage(null);
      }
    }
  }, [currentShot, parsedData]);

  // 键盘左右方向键切换分镜
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 只有在有分镜数据且没有在输入框中输入时才响应
      if (!parsedData?.shots || parsedData.shots.length === 0) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      
      if (e.key === 'ArrowLeft') {
        // 左方向键 - 切换到上一个分镜
        setCurrentShot(prev => Math.max(1, prev - 1));
      } else if (e.key === 'ArrowRight') {
        // 右方向键 - 切换到下一个分镜
        setCurrentShot(prev => Math.min(parsedData.shots.length, prev + 1));
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [parsedData?.shots?.length]);

  // 轮询任务状态
  useEffect(() => {
    if (!cid || !id) return;
    
    let isRunning = false;
    let timeoutId: NodeJS.Timeout | null = null;
    
    // 递归轮询，确保上一个请求完成后再等待 3 秒
    const poll = async () => {
      if (pendingShots.size === 0 && pendingVideos.size === 0 && generatingTransitions.size === 0) {
        // 没有 pending 任务，继续等待
        timeoutId = setTimeout(poll, 3000);
        return;
      }
      
      if (isRunning) {
        // 上一个请求还在执行，等待下一次
        timeoutId = setTimeout(poll, 3000);
        return;
      }
      
      isRunning = true;
      try {
        await checkShotTaskStatus();
      } finally {
        isRunning = false;
        // 无论成功失败，3 秒后继续下一次
        timeoutId = setTimeout(poll, 3000);
      }
    };
    
    // 启动轮询
    timeoutId = setTimeout(poll, 3000);
    
    return () => {
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [cid, id, pendingShots.size, pendingVideos.size, generatingTransitions.size]);

  // 检查分镜任务状态并更新
  const checkShotTaskStatus = async () => {
    if (pendingShots.size === 0 && pendingVideos.size === 0 && generatingTransitions.size === 0) return;
    
    try {
      // 同时检查图片、视频和转场视频任务
      const [imageRes, videoRes, transitionRes] = await Promise.all([
        fetch(`${API_BASE}/tasks/?type=shot_image&limit=50`),
        fetch(`${API_BASE}/tasks/?type=shot_video&limit=50`),
        fetch(`${API_BASE}/tasks/?type=transition_video&limit=50`)
      ]);
      const [imageData, videoData, transitionData] = await Promise.all([
        imageRes.json(),
        videoRes.json(),
        transitionRes.json()
      ]);
      
      // 处理图片任务
      if (imageData.success && pendingShots.size > 0) {
        const chapterImageTasks = imageData.data.filter((task: any) => 
          task.chapterId === cid
        );
        
        let hasCompleted = false;
        const stillPending = new Set<number>();
        
        chapterImageTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)/);
          if (!match) return;
          const shotNum = parseInt(match[1]);
          
          if (task.status === 'completed') {
            if (task.resultUrl) {
              setShotImages(prev => ({ ...prev, [shotNum]: task.resultUrl }));
              hasCompleted = true;
            }
          } else if (task.status === 'pending' || task.status === 'running') {
            stillPending.add(shotNum);
          } else if (task.status === 'failed') {
            hasCompleted = true;
          }
        });
        
        if (hasCompleted || stillPending.size !== pendingShots.size) {
          setPendingShots(stillPending);
        }
        
        // 如果有图片任务完成，刷新章节数据以获取合并角色图
        if (hasCompleted) {
          fetchChapter();
        }
      }
      
      // 处理视频任务
      if (videoData.success && pendingVideos.size > 0) {
        const chapterVideoTasks = videoData.data.filter((task: any) => 
          task.chapterId === cid
        );
        
        console.log('[ChapterGenerate] Checking video tasks:', chapterVideoTasks.length, 'pending:', pendingVideos.size);
        
        let hasCompletedVideo = false;
        const stillPendingVideos = new Set<number>();
        
        chapterVideoTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)/);
          if (!match) return;
          const shotNum = parseInt(match[1]);
          
          console.log('[ChapterGenerate] Video task:', task.name, 'status:', task.status, 'shotNum:', shotNum);
          
          if (task.status === 'completed') {
            if (task.resultUrl) {
              console.log('[ChapterGenerate] Video completed, setting URL for shot', shotNum);
              setShotVideos(prev => ({ ...prev, [shotNum]: task.resultUrl }));
              hasCompletedVideo = true;
            }
          } else if (task.status === 'pending' || task.status === 'running') {
            stillPendingVideos.add(shotNum);
          } else if (task.status === 'failed') {
            hasCompletedVideo = true;
          }
        });
        
        console.log('[ChapterGenerate] Video check result - hasCompleted:', hasCompletedVideo, 'stillPending:', [...stillPendingVideos]);
        
        if (hasCompletedVideo || stillPendingVideos.size !== pendingVideos.size) {
          setPendingVideos(stillPendingVideos);
        }
        
        // 如果有视频任务完成，刷新章节数据
        if (hasCompletedVideo) {
          console.log('[ChapterGenerate] Fetching chapter data after video completion');
          fetchChapter();
        }
      }
      
      // 处理转场视频任务
      if (transitionData.success && generatingTransitions.size > 0) {
        const chapterTransitionTasks = transitionData.data.filter((task: any) => 
          task.chapterId === cid
        );
        
        console.log('[ChapterGenerate] Checking transition tasks:', chapterTransitionTasks.length, 'generating:', generatingTransitions.size);
        
        let hasCompletedTransition = false;
        const stillGeneratingTransitions = new Set<string>();
        
        chapterTransitionTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)→镜(\d+)/);
          if (!match) return;
          const transitionKey = `${match[1]}-${match[2]}`;
          
          console.log('[ChapterGenerate] Transition task:', task.name, 'status:', task.status, 'key:', transitionKey);
          
          if (task.status === 'completed') {
            if (task.resultUrl) {
              console.log('[ChapterGenerate] Transition completed, setting URL for', transitionKey);
              setTransitionVideos(prev => ({ ...prev, [transitionKey]: task.resultUrl }));
              hasCompletedTransition = true;
            }
          } else if (task.status === 'pending' || task.status === 'running') {
            stillGeneratingTransitions.add(transitionKey);
          } else if (task.status === 'failed') {
            hasCompletedTransition = true;
          }
        });
        
        console.log('[ChapterGenerate] Transition check result - hasCompleted:', hasCompletedTransition, 'stillGenerating:', [...stillGeneratingTransitions]);
        
        if (hasCompletedTransition || stillGeneratingTransitions.size !== generatingTransitions.size) {
          setGeneratingTransitions(stillGeneratingTransitions);
        }
        
        // 如果有转场视频任务完成，刷新章节数据
        if (hasCompletedTransition) {
          console.log('[ChapterGenerate] Fetching chapter data after transition completion');
          fetchChapter();
        }
      }
    } catch (error) {
      console.error('检查任务状态失败:', error);
    }
  };

  // 获取分镜生成任务状态
  const fetchShotTasks = async () => {
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=shot_image&limit=50`);
      const data = await res.json();
      if (data.success) {
        // 过滤出当前章节的 pending/running 任务
        const activeTasks = data.data.filter((task: any) => 
          task.chapterId === cid && 
          (task.status === 'pending' || task.status === 'running')
        );
        
        // 从任务名称提取分镜索引 (格式: "生成分镜图: 镜X")
        const pendingShotIndices = new Set<number>();
        activeTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)/);
          if (match) {
            pendingShotIndices.add(parseInt(match[1]));
          }
        });
        
        if (pendingShotIndices.size > 0) {
          console.log('[ChapterGenerate] Restored pending shots from tasks:', [...pendingShotIndices]);
          setPendingShots(pendingShotIndices);
        }
      }
    } catch (error) {
      console.error('获取分镜任务状态失败:', error);
    }
  };

  // 获取视频生成任务状态
  const fetchVideoTasks = async () => {
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=shot_video&limit=50`);
      const data = await res.json();
      if (data.success) {
        // 过滤出当前章节的 pending/running 任务
        const activeTasks = data.data.filter((task: any) => 
          task.chapterId === cid && 
          (task.status === 'pending' || task.status === 'running')
        );
        
        // 从任务名称提取分镜索引 (格式: "生成视频: 镜X")
        const pendingVideoIndices = new Set<number>();
        activeTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)/);
          if (match) {
            pendingVideoIndices.add(parseInt(match[1]));
          }
        });
        
        console.log('[ChapterGenerate] fetchVideoTasks found active:', [...pendingVideoIndices]);
        
        if (pendingVideoIndices.size > 0) {
          console.log('[ChapterGenerate] Restored pending videos from tasks:', [...pendingVideoIndices]);
          setPendingVideos(pendingVideoIndices);
        }
      }
    } catch (error) {
      console.error('获取视频任务状态失败:', error);
    }
  };

  // 获取转场视频生成任务状态
  const fetchTransitionTasks = async () => {
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=transition_video&limit=50`);
      const data = await res.json();
      if (data.success) {
        // 过滤出当前章节的 pending/running 任务
        const activeTasks = data.data.filter((task: any) => 
          task.chapterId === cid && 
          (task.status === 'pending' || task.status === 'running')
        );
        
        // 从任务名称提取转场索引 (格式: "生成转场视频: 镜X→镜Y")
        const pendingTransitionKeys = new Set<string>();
        activeTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)→镜(\d+)/);
          if (match) {
            pendingTransitionKeys.add(`${match[1]}-${match[2]}`);
          }
        });
        
        console.log('[ChapterGenerate] fetchTransitionTasks found active:', [...pendingTransitionKeys]);
        
        if (pendingTransitionKeys.size > 0) {
          setGeneratingTransitions(pendingTransitionKeys);
        }
      }
    } catch (error) {
      console.error('获取转场任务状态失败:', error);
    }
  };

  // 获取转场工作流列表
  const fetchTransitionWorkflows = async () => {
    try {
      const res = await fetch(`${API_BASE}/workflows/?type=transition`);
      const data = await res.json();
      if (data.success) {
        setTransitionWorkflows(data.data || []);
        // 默认选中第一个激活的工作流
        const activeWorkflow = data.data.find((w: any) => w.isActive);
        if (activeWorkflow) {
          setSelectedTransitionWorkflow(activeWorkflow.id);
        } else if (data.data.length > 0) {
          setSelectedTransitionWorkflow(data.data[0].id);
        }
      }
    } catch (error) {
      console.error('获取转场工作流失败:', error);
    }
  };

  // 生成单个转场视频
  const handleGenerateTransition = async (fromIndex: number, toIndex: number, useCustomConfig: boolean = false) => {
    const transitionKey = `${fromIndex}-${toIndex}`;
    setGeneratingTransitions(prev => new Set(prev).add(transitionKey));
    
    try {
      // 构建请求体
      const body: any = { 
        from_index: fromIndex, 
        to_index: toIndex
      };
      
      // 如果使用自定义配置，添加工作流ID和帧数
      if (useCustomConfig) {
        if (selectedTransitionWorkflow) {
          body.workflow_id = selectedTransitionWorkflow;
        }
        // 根据时长计算帧数 (25fps)，确保是 8 的倍数 + 1
        const frameCount = Math.max(9, Math.round(transitionDuration * 25 / 8) * 8 + 1);
        body.frame_count = frameCount;
        console.log(`[GenerateTransition] Using custom config: duration=${transitionDuration}s, frames=${frameCount}`);
      }
      
      const res = await fetch(
        `${API_BASE}/novels/${id}/chapters/${cid}/transitions/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        }
      );
      const data = await res.json();
      
      if (data.success) {
        toast.success(`转场视频 镜${fromIndex}→镜${toIndex} 已开始生成`);
      } else {
        toast.error(data.message || '生成失败');
        setGeneratingTransitions(prev => {
          const next = new Set(prev);
          next.delete(transitionKey);
          return next;
        });
      }
    } catch (error) {
      console.error('生成转场视频失败:', error);
      toast.error('生成失败');
      setGeneratingTransitions(prev => {
        const next = new Set(prev);
        next.delete(transitionKey);
        return next;
      });
    }
  };

  // 一键生成所有转场视频
  const handleGenerateAllTransitions = async () => {
    if (!parsedData?.shots || parsedData.shots.length < 2) {
      toast.warning('分镜数量不足，无法生成转场');
      return;
    }
    
    try {
      // 构建请求体
      const body: any = {};
      
      // 如果配置了自定义选项，添加它们
      if (selectedTransitionWorkflow) {
        body.workflow_id = selectedTransitionWorkflow;
      }
      // 根据时长计算帧数 (25fps)，确保是 8 的倍数 + 1
      const frameCount = Math.max(9, Math.round(transitionDuration * 25 / 8) * 8 + 1);
      body.frame_count = frameCount;
      console.log(`[GenerateAllTransitions] Using config: duration=${transitionDuration}s, frames=${frameCount}, workflow=${selectedTransitionWorkflow || 'default'}`);
      
      const res = await fetch(
        `${API_BASE}/novels/${id}/chapters/${cid}/transitions/batch/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        }
      );
      const data = await res.json();
      
      if (data.success) {
        toast.success(`已创建 ${data.task_count} 个转场视频生成任务`);
        // 添加所有转场到生成中状态
        const allTransitions = new Set<string>();
        for (let i = 1; i < parsedData.shots.length; i++) {
          allTransitions.add(`${i}-${i + 1}`);
        }
        setGeneratingTransitions(allTransitions);
      } else {
        toast.error(data.message || '生成失败');
      }
    } catch (error) {
      console.error('批量生成转场视频失败:', error);
      toast.error('生成失败');
    }
  };

  // 获取小说数据
  const fetchNovel = async () => {
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/`);
      const data = await res.json();
      if (data.success) {
        setNovel(data.data);
      }
    } catch (error) {
      console.error('获取小说数据失败:', error);
    }
  };

  const fetchChapter = async () => {
    setLoading(true);
    try {
      // 使用正确的 API 路径：/api/novels/{novel_id}/chapters/{chapter_id}
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/`);
      const data = await res.json();
      if (data.success) {
        setChapter(data.data);
        // 如果章节有解析数据，加载它
        if (data.data.parsedData) {
          try {
            const parsed = typeof data.data.parsedData === 'string' 
              ? JSON.parse(data.data.parsedData) 
              : data.data.parsedData;
            setParsedData(parsed);
            setEditableJson(JSON.stringify(parsed, null, 2));
            
            // 检查已生成的分镜，更新图片并移除 pending
            if (parsed.shots && parsed.shots.length > 0) {
              const newShotImages: Record<number, string> = {};
              const newMergedImages: Record<number, string> = {};
              setPendingShots(prev => {
                const next = new Set(prev);
                parsed.shots.forEach((shot: any, index: number) => {
                  const shotNum = index + 1;
                  if (shot.image_url) {
                    newShotImages[shotNum] = shot.image_url;
                    next.delete(shotNum);
                  }
                  // 加载合并角色图
                  if (shot.merged_character_image) {
                    newMergedImages[shotNum] = shot.merged_character_image;
                  }
                });
                return next;
              });
              // 更新 shotImages
              if (Object.keys(newShotImages).length > 0) {
                setShotImages(prev => ({ ...prev, ...newShotImages }));
              }
              // 更新当前分镜的合并角色图
              if (newMergedImages[currentShot]) {
                setMergedImage(newMergedImages[currentShot]);
              }
            }
          } catch (e) {
            console.error('解析数据格式错误:', e);
          }
        }
        // 加载分镜视频
        if (data.data.shotVideos && data.data.shotVideos.length > 0) {
          const newShotVideos: Record<number, string> = {};
          data.data.shotVideos.forEach((url: string, index: number) => {
            if (url) {
              newShotVideos[index + 1] = url;
            }
          });
          console.log('[ChapterGenerate] Loaded shot videos from chapter:', newShotVideos);
          setShotVideos(newShotVideos);
        } else {
          console.log('[ChapterGenerate] No shot videos in chapter data');
        }
        
        // 加载转场视频
        if (data.data.transitionVideos) {
          console.log('[ChapterGenerate] Loaded transition videos:', data.data.transitionVideos);
          setTransitionVideos(data.data.transitionVideos);
        }
      }
    } catch (error) {
      console.error('获取章节数据失败:', error);
    } finally {
      setLoading(false);
      // 章节数据加载完成后，获取任务状态以恢复 pending 状态
      fetchShotTasks();
      fetchVideoTasks();
      fetchTransitionTasks();
    }
  };

  // 获取角色列表
  const fetchCharacters = async () => {
    try {
      const res = await fetch(`${API_BASE}/characters/?novel_id=${id}`);
      const data = await res.json();
      if (data.success) {
        setCharacters(data.data);
      }
    } catch (error) {
      console.error('获取角色列表失败:', error);
    }
  };

  // 根据角色名获取角色图片
  const getCharacterImage = (name: string): string | null => {
    const character = characters.find(c => c.name === name);
    return character?.imageUrl || null;
  };

  // 合并角色图
  const handleMergeCharacterImages = async () => {
    const currentShotData = parsedData?.shots?.[currentShot - 1];
    const shotCharacters = currentShotData?.characters || [];
    
    if (shotCharacters.length === 0) {
      toast.warning('当前分镜没有角色');
      return;
    }

    setIsMerging(true);
    try {
      // 获取角色图片URL
      const imageUrls = shotCharacters.map((name: string) => getCharacterImage(name)).filter(Boolean) as string[];
      
      if (imageUrls.length === 0) {
        toast.warning('角色图片未生成');
        return;
      }

      // 计算布局
      const count = imageUrls.length;
      let cols = 1;
      let rows = 1;
      
      if (count === 1) {
        cols = 1; rows = 1;
      } else if (count <= 3) {
        cols = 1; rows = count;
      } else if (count === 4) {
        cols = 2; rows = 2;
      } else if (count <= 6) {
        cols = 3; rows = 2;
      } else {
        cols = 3; rows = Math.ceil(count / 3);
      }

      // 加载图片
      const images = await Promise.all(
        imageUrls.map(url => new Promise<HTMLImageElement>((resolve, reject) => {
          const img = new Image();
          img.crossOrigin = 'anonymous';
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = url;
        }))
      );

      // 创建canvas
      const canvas = document.createElement('canvas');
      const cellWidth = 200;
      const cellHeight = 200;
      const nameHeight = 30;
      const padding = 10;
      
      canvas.width = cols * (cellWidth + padding) + padding;
      canvas.height = rows * (cellHeight + nameHeight + padding) + padding;
      
      const ctx = canvas.getContext('2d')!;
      
      // 白色背景
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      
      // 绘制每个角色图片和名称
      images.forEach((img, index) => {
        const col = index % cols;
        const row = Math.floor(index / cols);
        const x = padding + col * (cellWidth + padding);
        const y = padding + row * (cellHeight + nameHeight + padding);
        
        // 绘制图片（保持比例）
        const scale = Math.min(cellWidth / img.width, cellHeight / img.height);
        const drawWidth = img.width * scale;
        const drawHeight = img.height * scale;
        const drawX = x + (cellWidth - drawWidth) / 2;
        const drawY = y + (cellHeight - drawHeight) / 2;
        
        ctx.drawImage(img, drawX, drawY, drawWidth, drawHeight);
        
        // 绘制角色名称
        ctx.fillStyle = '#333333';
        ctx.font = 'bold 14px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(shotCharacters[index], x + cellWidth / 2, y + cellHeight + 20);
      });
      
      // 生成图片URL
      const mergedUrl = canvas.toDataURL('image/png');
      setMergedImage(mergedUrl);
    } catch (error) {
      console.error('合并角色图失败:', error);
      toast.error('合并失败，请重试');
    } finally {
      setIsMerging(false);
    }
  };

  // 根据画面比例计算图片容器尺寸
  const getAspectRatioStyle = (): React.CSSProperties => {
    const aspectRatio = novel?.aspectRatio || '16:9';
    const baseSize = 120; // 基础宽度
    
    switch (aspectRatio) {
      case '16:9':
        return { width: baseSize, height: Math.round(baseSize * 9 / 16) };
      case '9:16':
        return { width: Math.round(baseSize * 9 / 16), height: baseSize };
      case '4:3':
        return { width: baseSize, height: Math.round(baseSize * 3 / 4) };
      case '3:4':
        return { width: Math.round(baseSize * 3 / 4), height: baseSize };
      case '1:1':
        return { width: baseSize, height: baseSize };
      case '21:9':
        return { width: baseSize, height: Math.round(baseSize * 9 / 21) };
      case '2.35:1':
        return { width: baseSize, height: Math.round(baseSize / 2.35) };
      default:
        return { width: baseSize, height: Math.round(baseSize * 9 / 16) };
    }
  };

  // 跳转到角色库页面
  const handleRegenerateCharacter = (characterName: string) => {
    // 查找角色ID
    const character = characters.find(c => c.name === characterName);
    if (character) {
      navigate(`/characters?novel_id=${id}&highlight=${character.id}`);
    } else {
      navigate(`/characters?novel_id=${id}`);
    }
  };

  // 获取当前步骤索引
  const currentStepIndex = 3; // 模拟当前在"生成视频"步骤

  const handleRegenerate = () => {
    setIsGenerating(true);
    // 模拟生成过程
    setTimeout(() => setIsGenerating(false), 3000);
  };

  const handleSplitChapter = async () => {
    if (!id || !cid) return;
    
    setIsSplitting(true);
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/split/`, {
        method: 'POST'
      });
      const data = await res.json();
      
      if (data.success) {
        setParsedData(data.data);
        setEditableJson(JSON.stringify(data.data, null, 2));
        // 自动切换到 JSON 标签页查看结果
        setActiveTab('json');
        toast.success('拆分成功');
      } else {
        toast.error(data.message || '拆分失败');
      }
    } catch (error) {
      console.error('拆分章节失败:', error);
      toast.error('拆分失败，请检查网络连接');
    } finally {
      setIsSplitting(false);
    }
  };

  // 保存JSON修改
  const handleSaveJson = async () => {
    if (!id || !cid || !editableJson.trim()) return;
    
    // 验证JSON格式
    let parsedJson;
    try {
      parsedJson = JSON.parse(editableJson);
    } catch (e) {
      toast.error('JSON格式错误，请检查后再保存');
      return;
    }
    
    setIsSavingJson(true);
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parsedData: editableJson
        })
      });
      const data = await res.json();
      
      if (data.success) {
        setParsedData(parsedJson);
        toast.success('保存成功');
      } else {
        toast.error(data.message || '保存失败');
      }
    } catch (error) {
      console.error('保存JSON失败:', error);
      toast.error('保存失败，请检查网络连接');
    } finally {
      setIsSavingJson(false);
    }
  };

  const renderStepIndicator = () => (
    <div className="card mb-6">
      <div className="flex items-center justify-between">
        {STEPS.map((step, index) => {
          const StepIcon = step.icon;
          
          return (
            <div key={step.key} className="flex items-center flex-1">
              <div className="flex flex-col items-center">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center mb-2 bg-gradient-to-br ${step.color} text-white shadow-md`}>
                  <StepIcon className="h-5 w-5" />
                </div>
                <span className="text-xs font-medium text-gray-700 text-center whitespace-nowrap">
                  {step.label}
                </span>
              </div>
              {index < STEPS.length - 1 && (
                <div className="flex items-center flex-1 justify-center mb-6">
                  <ChevronRight className="h-5 w-5 text-gray-300" />
                </div>
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
          <div className="space-y-3">
            {/* 编辑模式切换 */}
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
                <button
                  onClick={() => setJsonEditMode('text')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    jsonEditMode === 'text' 
                      ? 'bg-white text-gray-900 shadow-sm' 
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  <Code className="h-4 w-4" />
                  JSON文本
                </button>
                <button
                  onClick={() => setJsonEditMode('table')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    jsonEditMode === 'table' 
                      ? 'bg-white text-gray-900 shadow-sm' 
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  <Grid3x3 className="h-4 w-4" />
                  表格编辑
                </button>
              </div>
              <button
                onClick={handleSaveJson}
                disabled={isSavingJson || !editableJson.trim()}
                className="btn-primary text-sm py-2 px-4 disabled:opacity-50"
              >
                {isSavingJson ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" />保存中...</>
                ) : (
                  <><Save className="h-4 w-4 mr-2" />保存修改</>
                )}
              </button>
            </div>
            
            {jsonEditMode === 'text' ? (
              /* JSON文本编辑模式 */
              <textarea
                className="w-full h-64 bg-gray-900 text-gray-100 p-4 rounded-lg font-mono text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:outline-none"
                value={editableJson}
                onChange={(e) => setEditableJson(e.target.value)}
                placeholder="点击 AI拆分分镜头 按钮生成数据，或直接输入JSON..."
                spellCheck={false}
              />
            ) : (
              /* 表格编辑模式 */
              <JsonTableEditor 
                value={editableJson}
                onChange={setEditableJson}
              />
            )}
          </div>
        );
      case 'characters':
        return (
          <div className="space-y-2">
            {parsedData?.characters?.map((name: string, idx: number) => (
              <div key={idx} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                <Users className="h-5 w-5 text-blue-500" />
                <span className="font-medium">{name}</span>
              </div>
            )) || <p className="text-gray-500 text-sm py-4">暂无角色数据，请先进行AI拆分</p>}
          </div>
        );
      case 'scenes':
        return (
          <div className="space-y-2">
            {parsedData?.scenes?.map((name: string, idx: number) => (
              <div key={idx} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                <MapPin className="h-5 w-5 text-green-500" />
                <span className="font-medium">{name}</span>
              </div>
            )) || <p className="text-gray-500 text-sm py-4">暂无场景数据，请先进行AI拆分</p>}
          </div>
        );
      case 'script':
        return (
          <div className="space-y-3">
            {parsedData?.shots?.map((shot: any) => (
              <div key={shot.id} className="p-3 bg-gray-50 rounded-lg border-l-4 border-purple-500">
                <div className="flex justify-between items-start mb-1">
                  <span className="font-medium text-sm">镜{shot.id}</span>
                  <span className="text-xs text-gray-500">{shot.duration}秒</span>
                </div>
                <p className="text-sm text-gray-700">{shot.description}</p>
                <div className="flex gap-2 mt-2">
                  {shot.characters?.map((c: string) => (
                    <span key={c} className="text-xs px-2 py-1 bg-blue-100 text-blue-600 rounded">{c}</span>
                  ))}
                </div>
              </div>
            )) || <p className="text-gray-500 text-sm py-4">暂无分镜数据，请先进行AI拆分</p>}
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
          </div>
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
            {/* AI拆分分镜头按钮 */}
            <div className="mt-4 pt-4 border-t border-gray-100">
              <button 
                onClick={handleSplitChapter}
                disabled={isSplitting}
                className="w-full py-3 px-4 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-lg font-medium hover:from-purple-600 hover:to-pink-600 transition-all shadow-sm hover:shadow-md flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSplitting ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Sparkles className="h-5 w-5" />
                )}
                {isSplitting ? 'AI拆分中...' : 'AI拆分分镜头'}
              </button>
            </div>
          </div>

          {/* JSON/角色/场景/脚本 标签页 */}
          <div className="card">
            {renderTabs()}
            <div className="mt-4 max-h-96 overflow-y-auto">
              {renderTabContent()}
            </div>
          </div>

          {/* 人设图片 */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 mb-4">
              人设图片 
              <span className="text-xs font-normal text-gray-500 ml-2">
                ({novel?.aspectRatio || '16:9'})
              </span>
            </h3>
            <div className="flex gap-4 flex-wrap">
              {(() => {
                // 获取当前选中的分镜
                const currentShotData = parsedData?.shots?.[currentShot - 1];
                const currentShotCharacters = currentShotData?.characters || [];
                
                // 将角色按是否在当前分镜中排序（在前的排前面）
                const sortedCharacters = [...(parsedData?.characters || [])].sort((a: string, b: string) => {
                  const aInShot = currentShotCharacters.includes(a);
                  const bInShot = currentShotCharacters.includes(b);
                  if (aInShot && !bInShot) return -1;
                  if (!aInShot && bInShot) return 1;
                  return 0;
                });
                
                return sortedCharacters.map((name: string, idx: number) => {
                  const imageUrl = getCharacterImage(name);
                  const aspectStyle = getAspectRatioStyle();
                  const isInCurrentShot = currentShotCharacters.includes(name);
                  
                  return (
                    <div key={idx} className={`text-center relative ${isInCurrentShot ? 'order-first' : ''}`}>
                      <div 
                        className={`rounded-xl bg-gradient-to-br from-blue-400 to-purple-500 flex items-center justify-center mb-2 overflow-hidden relative ${
                          isInCurrentShot ? 'ring-2 ring-green-500 ring-offset-2' : ''
                        }`}
                        style={aspectStyle}
                      >
                        {imageUrl ? (
                          <img 
                            src={imageUrl} 
                            alt={name}
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <Users className="h-10 w-10 text-white" />
                        )}
                        {/* 勾选标识 */}
                        {isInCurrentShot && (
                          <div className="absolute top-1 right-1 w-5 h-5 bg-green-500 rounded-full flex items-center justify-center shadow-sm">
                            <CheckCircle className="h-3.5 w-3.5 text-white" />
                          </div>
                        )}
                      </div>
                      <p className="text-sm font-medium">{name}</p>
                      <button 
                        onClick={() => handleRegenerateCharacter(name)}
                        className="text-xs text-blue-600 hover:underline mt-1"
                      >
                        重新生成
                      </button>
                    </div>
                  );
                });
              })() || <p className="text-gray-500 text-sm py-4">暂无角色图片</p>}
            </div>
          </div>

          {/* 分镜图片 */}
          <div className="card">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-gray-900">分镜图片 ({parsedData?.shots?.length || 0}张)</h3>
              <div className="flex items-center gap-2">
                <button 
                  onClick={() => setCurrentShot(Math.max(1, currentShot - 1))}
                  className="p-1 rounded hover:bg-gray-100"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm text-gray-500">{currentShot}/{parsedData?.shots?.length || 0}</span>
                <button 
                  onClick={() => setCurrentShot(Math.min(parsedData?.shots?.length || 1, currentShot + 1))}
                  className="p-1 rounded hover:bg-gray-100"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
            {parsedData?.shots?.length > 0 ? (
              <>
                <div className="flex gap-3 overflow-x-auto pb-2">
                  {parsedData.shots.map((shot: any, index: number) => {
                    const shotNum = index + 1;
                    const imageUrl = shotImages[shotNum] || shot.image_url;
                    const isSubmitting = generatingShots.has(shotNum);
                    const isPending = pendingShots.has(shotNum);
                    const hasImage = !!imageUrl;
                    
                    return (
                      <div 
                        key={shot.id}
                        onClick={() => setCurrentShot(shotNum)}
                        className={`relative flex-shrink-0 w-32 h-24 rounded-lg overflow-hidden cursor-pointer transition-transform hover:scale-105 ${
                          currentShot === shotNum ? 'ring-2 ring-offset-2 ring-gray-400' : ''
                        }`}
                      >
                        {hasImage ? (
                          <img 
                            src={imageUrl} 
                            alt={`镜${shot.id}`}
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <div className="w-full h-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                            <ImageIcon className="h-8 w-8 text-white/70" />
                          </div>
                        )}
                        
                        {/* 提交中遮罩 */}
                        {isSubmitting && (
                          <div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center">
                            <Loader2 className="h-5 w-5 text-white animate-spin mb-1" />
                            <span className="text-[10px] text-white font-medium">提交中</span>
                          </div>
                        )}
                        
                        {/* 队列中遮罩 */}
                        {isPending && !isSubmitting && (
                          <div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center">
                            <div className="flex items-center gap-1 mb-1">
                              <div className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse" />
                              <div className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse delay-75" />
                              <div className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse delay-150" />
                            </div>
                            <span className="text-[10px] text-white font-medium">队列中</span>
                          </div>
                        )}
                        
                        {/* 状态角标 */}
                        {(isSubmitting || isPending) && (
                          <div className="absolute top-1 right-1">
                            <div className="w-2 h-2 bg-yellow-400 rounded-full animate-ping" />
                          </div>
                        )}
                        
                        <span className="absolute bottom-1 left-2 text-xs text-white/90 bg-black/30 px-1.5 py-0.5 rounded">
                          镜{shot.id}
                        </span>
                      </div>
                    );
                  })}
                </div>
                {/* 当前选中的分镜大图 */}
                {(shotImages[currentShot] || parsedData.shots[currentShot - 1]?.image_url) && (
                  <div className="mt-4 mb-4">
                    <div 
                      className="aspect-video rounded-lg overflow-hidden bg-gray-100 cursor-pointer"
                      onClick={() => {
                        const url = shotImages[currentShot] || parsedData.shots[currentShot - 1]?.image_url;
                        if (url) {
                          setPreviewImageUrl(url);
                          setShowImagePreview(true);
                        }
                      }}
                    >
                      <img 
                        src={shotImages[currentShot] || parsedData.shots[currentShot - 1]?.image_url}
                        alt={`镜${currentShot}`}
                        className="w-full h-full object-contain"
                      />
                    </div>
                  </div>
                )}

                <div className="flex gap-3 mt-4 flex-wrap">
                  <button 
                    onClick={() => handleGenerateShotImage(currentShot)}
                    disabled={generatingShots.has(currentShot) || pendingShots.has(currentShot)}
                    className="btn-secondary text-sm py-1.5 disabled:opacity-50"
                  >
                    {generatingShots.has(currentShot) ? (
                      <><Loader2 className="h-3 w-3 mr-1 animate-spin" />提交中...</>
                    ) : pendingShots.has(currentShot) ? (
                      <><Clock className="h-3 w-3 mr-1" />队列中</>
                    ) : (
                      <><RefreshCw className="h-3 w-3 mr-1" />重新生成</>
                    )}
                  </button>
                  {/* 生成分镜视频按钮 - 只有当前分镜有图片时才可点击 */}
                  <button 
                    onClick={() => handleGenerateShotVideo(currentShot)}
                    disabled={
                      !(shotImages[currentShot] || parsedData.shots[currentShot - 1]?.image_url) ||
                      generatingVideos.has(currentShot) || 
                      pendingVideos.has(currentShot)
                    }
                    className="btn-secondary text-sm py-1.5 text-purple-600 hover:text-purple-700 hover:bg-purple-50 disabled:opacity-50"
                    title={
                      !(shotImages[currentShot] || parsedData.shots[currentShot - 1]?.image_url)
                        ? '请先生成分镜图片'
                        : pendingVideos.has(currentShot)
                        ? '视频生成中...'
                        : '基于当前分镜图片生成视频'
                    }
                  >
                    {generatingVideos.has(currentShot) ? (
                      <><Loader2 className="h-3 w-3 mr-1 animate-spin" />提交中...</>
                    ) : pendingVideos.has(currentShot) ? (
                      <><Clock className="h-3 w-3 mr-1" />生成中...</>
                    ) : (
                      <><Film className="h-3 w-3 mr-1" />生成分镜视频</>
                    )}
                  </button>
                  <button 
                    onClick={handleGenerateAllShots}
                    disabled={isGeneratingAll || pendingShots.size > 0}
                    className="btn-secondary text-sm py-1.5 text-blue-600 hover:text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                  >
                    {isGeneratingAll ? (
                      <><Loader2 className="h-3 w-3 mr-1 animate-spin" />批量提交中...</>
                    ) : (
                      <><RefreshCw className="h-3 w-3 mr-1" />生成全部分镜图</>
                    )}
                  </button>
                  <button 
                    onClick={handleGenerateAllVideos}
                    disabled={generatingVideos.size > 0 || pendingVideos.size > 0}
                    className="btn-secondary text-sm py-1.5 text-purple-600 hover:text-purple-700 hover:bg-purple-50 disabled:opacity-50"
                    title="为所有已有分镜图片的分镜生成视频"
                  >
                    <Film className="h-3 w-3 mr-1" />
                    生成全部分镜视频
                  </button>
                  <button 
                    onClick={() => setShowMergedImageModal(true)}
                    disabled={!mergedImage}
                    className="btn-secondary text-sm py-1.5 text-red-600 hover:text-red-700 hover:bg-red-50 disabled:opacity-50"
                    title={mergedImage ? '查看合并角色图' : '请先生成合并角色图'}
                  >
                    <Grid3x3 className="h-3 w-3 mr-1" />
                    查看合并角色图
                  </button>
                </div>
                

              </>
            ) : (
              <p className="text-gray-500 text-sm py-4">暂无分镜图片，请先进行AI拆分</p>
            )}
          </div>

          {/* 分镜视频 */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <h3 className="font-semibold text-gray-900">
                  {currentTransition && transitionVideos[currentTransition] 
                    ? `转场 ${currentTransition} 预览` 
                    : '分镜视频'}
                </h3>
                {currentTransition && transitionVideos[currentTransition] && (
                  <button
                    onClick={() => setCurrentTransition('')}
                    className="text-xs px-2 py-1 bg-orange-100 text-orange-700 rounded hover:bg-orange-200 transition-colors"
                  >
                    返回分镜视频
                  </button>
                )}
              </div>
              {parsedData?.shots && parsedData.shots.length > 1 && (
                <button
                  onClick={handleGenerateAllTransitions}
                  disabled={generatingTransitions.size > 0}
                  className="btn-secondary text-sm py-1.5 text-orange-600 hover:text-orange-700 hover:bg-orange-50 disabled:opacity-50"
                  title="为所有相邻分镜生成转场视频"
                >
                  {generatingTransitions.size > 0 ? (
                    <><Loader2 className="h-3 w-3 mr-1 animate-spin" />生成中...</>
                  ) : (
                    <><RefreshCw className="h-3 w-3 mr-1" />一键生成全部转场</>
                  )}
                </button>
              )}
            </div>
            <div className="aspect-video bg-gray-900 rounded-lg flex items-center justify-center mb-4 overflow-hidden">
              {currentTransition && transitionVideos[currentTransition] ? (
                // 转场视频播放
                <video
                  key={`transition-${currentTransition}`}
                  src={transitionVideos[currentTransition]}
                  controls
                  autoPlay
                  className="w-full h-full"
                  poster={shotImages[parseInt(currentTransition.split('-')[0])]}
                />
              ) : shotVideos[currentVideo] ? (
                // 分镜视频播放
                <video
                  key={currentVideo}
                  src={shotVideos[currentVideo]}
                  controls
                  className="w-full h-full"
                  poster={shotImages[currentVideo]}
                />
              ) : (
                <div className="text-center">
                  <Play className="h-16 w-16 text-white/50 mx-auto mb-2" />
                  <p className="text-white/50 text-sm">
                    {generatingVideos.has(currentVideo) ? '生成中...' : pendingVideos.has(currentVideo) ? '排队中...' : '暂无视频'}
                  </p>
                </div>
              )}
            </div>
            
            {/* 转场配置面板 */}
            {parsedData?.shots && parsedData.shots.length > 1 && (
              <div className="mb-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Settings className="h-4 w-4 text-gray-500" />
                    <span className="text-sm font-medium text-gray-700">转场配置</span>
                    {showTransitionConfig && (
                      <span className="text-xs px-2 py-0.5 bg-orange-100 text-orange-700 rounded">已启用自定义</span>
                    )}
                  </div>
                  <button
                    onClick={() => setShowTransitionConfig(!showTransitionConfig)}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    {showTransitionConfig ? '收起配置' : '展开配置'}
                  </button>
                </div>
                
                {showTransitionConfig && (
                  <div className="space-y-3 pt-2 border-t border-gray-200">
                    {/* 工作流选择 */}
                    <div className="flex items-center gap-3">
                      <label className="text-sm text-gray-600 whitespace-nowrap">工作流:</label>
                      <select
                        value={selectedTransitionWorkflow}
                        onChange={(e) => setSelectedTransitionWorkflow(e.target.value)}
                        className="flex-1 text-sm border border-gray-300 rounded px-2 py-1 focus:ring-2 focus:ring-orange-500 focus:border-orange-500"
                      >
                        {transitionWorkflows.map((wf) => (
                          <option key={wf.id} value={wf.id}>
                            {wf.name} {wf.isActive ? '(默认)' : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    
                    {/* 时长设置 */}
                    <div className="flex items-center gap-3">
                      <label className="text-sm text-gray-600 whitespace-nowrap">时长:</label>
                      <div className="flex items-center gap-2 flex-1">
                        <input
                          type="range"
                          min="1"
                          max="5"
                          step="0.5"
                          value={transitionDuration}
                          onChange={(e) => setTransitionDuration(parseFloat(e.target.value))}
                          className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                        />
                        <span className="text-sm text-gray-700 w-16 text-right">{transitionDuration}秒</span>
                      </div>
                    </div>
                    
                    {/* 提示信息和还原按钮 */}
                    <div className="flex items-center justify-between pt-2 border-t border-gray-200">
                      <p className="text-xs text-gray-500">
                        配置后点击"生成"或"一键生成全部转场"将使用自定义设置
                      </p>
                      <button
                        onClick={() => {
                          // 还原到默认工作流
                          const defaultWorkflow = transitionWorkflows.find((w: any) => w.isActive);
                          if (defaultWorkflow) {
                            setSelectedTransitionWorkflow(defaultWorkflow.id);
                          } else if (transitionWorkflows.length > 0) {
                            setSelectedTransitionWorkflow(transitionWorkflows[0].id);
                          }
                          // 还原时长为2秒
                          setTransitionDuration(2);
                          toast.info('已还原为默认设置');
                        }}
                        className="text-xs px-3 py-1.5 bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition-colors"
                      >
                        还原
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            
            {/* 分镜视频列表 + 转场入口 */}
            <div className="flex gap-2 overflow-x-auto pb-2 items-center">
              {parsedData?.shots?.map((shot: any, index: number) => {
                const shotNum = index + 1;
                const imageUrl = shotImages[shotNum] || shot.image_url;
                const hasVideo = !!shotVideos[shotNum];
                const isPending = pendingVideos.has(shotNum);
                const isGenerating = generatingVideos.has(shotNum);
                const duration = shot.duration || 4;
                
                return (
                  <div key={shot.id} className="flex items-center gap-2">
                    {/* 分镜视频缩略图 */}
                    <div
                      onClick={() => {
                        // 如果当前在转场预览模式，先退出
                        if (currentTransition) {
                          setCurrentTransition('');
                        }
                        setCurrentVideo(shotNum);
                      }}
                      className={`relative flex-shrink-0 w-24 h-16 rounded-lg overflow-hidden cursor-pointer transition-transform hover:scale-105 ${
                        currentVideo === shotNum && !currentTransition ? 'ring-2 ring-offset-2 ring-purple-500' : ''
                      }`}
                    >
                      {imageUrl ? (
                        <img 
                          src={imageUrl} 
                          alt={`镜${shot.id}`}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                          <ImageIcon className="h-6 w-6 text-white/70" />
                        </div>
                      )}
                      
                      {/* 状态角标 */}
                      {hasVideo && (
                        <div className="absolute top-1 right-1 w-2 h-2 bg-green-500 rounded-full" />
                      )}
                      {(isPending || isGenerating) && (
                        <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                          <Loader2 className="h-4 w-4 text-white animate-spin" />
                        </div>
                      )}
                      
                      {/* 底部信息栏 */}
                      <div className="absolute bottom-0 left-0 right-0 bg-black/50 px-1.5 py-0.5 flex items-center justify-between">
                        <span className="text-[10px] text-white font-medium">镜{shot.id}</span>
                        <span className="text-[10px] text-white/80">{duration}s</span>
                      </div>
                    </div>
                    
                    {/* 转场入口（在当前分镜和后一个分镜之间） */}
                    {index < parsedData.shots.length - 1 && (
                      <TransitionVideoItem
                        fromIndex={shotNum}
                        toIndex={shotNum + 1}
                        fromVideo={shotVideos[shotNum]}
                        toVideo={shotVideos[shotNum + 1]}
                        fromImage={shotImages[shotNum] || shot.image_url}
                        toImage={shotImages[shotNum + 1] || parsedData.shots[shotNum]?.image_url}
                        transitionVideo={transitionVideos[`${shotNum}-${shotNum + 1}`]}
                        isGenerating={generatingTransitions.has(`${shotNum}-${shotNum + 1}`)}
                        onGenerate={() => handleGenerateTransition(shotNum, shotNum + 1, true)}
                        onRegenerate={() => handleGenerateTransition(shotNum, shotNum + 1, true)}
                        onClick={() => {
                          if (transitionVideos[`${shotNum}-${shotNum + 1}`]) {
                            setCurrentTransition(`${shotNum}-${shotNum + 1}`);
                          }
                        }}
                        isActive={currentTransition === `${shotNum}-${shotNum + 1}`}
                      />
                    )}
                  </div>
                );
              }) || <p className="text-gray-500 text-sm">暂无视频</p>}
            </div>
          </div>
        </div>

        {/* 右侧边栏 */}
        <div className="col-span-4 space-y-6">
          {/* 系统状态 - 吸顶效果 */}
          <div className="sticky top-6 space-y-4">
            <ComfyUIStatus />
            
            {/* 合并视频 */}
            <MergeVideosCard
              novelId={id}
              chapterId={cid}
              shotVideos={shotVideos}
              transitionVideos={transitionVideos}
              chapter={chapter}
            />
            
            {/* 章节素材下载 */}
            <DownloadMaterialsCard 
              novelId={id} 
              chapterId={cid}
              chapterTitle={chapter?.title || '未命名章节'}
            />
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

      {/* 合并角色图预览弹窗 */}
      {showMergedImageModal && mergedImage && (
        <div className="fixed inset-0 bg-black bg-opacity-80 flex items-center justify-center z-50 p-4">
          <div className="relative max-w-4xl max-h-[90vh] flex flex-col">
            <button
              onClick={() => setShowMergedImageModal(false)}
              className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300"
            >
              <X className="h-6 w-6" />
            </button>
            <img 
              src={mergedImage} 
              alt="合并角色图" 
              className="max-w-full max-h-[80vh] object-contain rounded-lg"
            />
            <div className="mt-4 text-center">
              <button
                onClick={() => {
                  const link = document.createElement('a');
                  link.download = `角色图_镜${currentShot}.png`;
                  link.href = mergedImage;
                  link.click();
                }}
                className="btn-primary text-sm"
              >
                <Download className="h-4 w-4 mr-2" />
                下载图片
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 分镜图片预览弹窗 */}
      {showImagePreview && previewImageUrl && (
        <div 
          className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4"
          onClick={() => setShowImagePreview(false)}
        >
          <div className="relative max-w-5xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setShowImagePreview(false)}
              className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 z-10"
            >
              <X className="h-6 w-6" />
            </button>
            <img 
              src={previewImageUrl} 
              alt="分镜预览" 
              className="max-w-full max-h-[85vh] object-contain rounded-lg"
            />
            <div className="mt-4 flex justify-center gap-3">
              <button
                onClick={() => {
                  const link = document.createElement('a');
                  link.download = `分镜_${currentShot}.png`;
                  link.href = previewImageUrl;
                  link.click();
                }}
                className="btn-primary text-sm"
              >
                <Download className="h-4 w-4 mr-2" />
                下载图片
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
