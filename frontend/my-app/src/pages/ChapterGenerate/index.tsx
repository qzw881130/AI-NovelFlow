import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useTranslation } from '../../stores/i18nStore';
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
  Code,
  AlertCircle,
  AlertTriangle,
  Upload
} from 'lucide-react';
import { toast } from '../../stores/toastStore';
import ComfyUIStatus from '../../components/ComfyUIStatus';

// 导入拆分后的组件和 hooks
import { STEPS_CONFIG, API_BASE } from './constants';
import type { ParsedData, Character, Scene } from './types';
import DownloadMaterialsCard from './components/DownloadMaterialsCard';
import JsonTableEditor from './components/JsonTableEditor';
import MergeVideosCard from './components/MergeVideosCard';
import TransitionVideoItem from './components/TransitionVideoItem';
import useChapterData from './hooks/useChapterData';
import useShotGeneration from './hooks/useShotGeneration';
import useVideoGeneration from './hooks/useVideoGeneration';
import useTransitionGeneration from './hooks/useTransitionGeneration';

export default function ChapterGenerate() {
  const { t } = useTranslation();
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const navigate = useNavigate();

  // 使用自定义 hooks
  const {
    chapter,
    novel,
    parsedData,
    editableJson,
    characters,
    scenes,
    loading,
    fetchNovel,
    fetchChapter,
    fetchCharacters,
    fetchScenes,
    setParsedData,
    setEditableJson,
    getCharacterImage,
    getSceneImage,
  } = useChapterData();

  const {
    generatingShots,
    pendingShots,
    shotImages,
    isGeneratingAll,
    uploadingShotIndex,
    handleGenerateShotImage,
    handleGenerateAllShots,
    triggerShotFileUpload,
    handleUploadShotImage,
    setShotImages,
    setPendingShots,
    checkShotTaskStatus,
    fetchShotTasks,
    shotFileInputRef,
  } = useShotGeneration();

  const {
    generatingVideos,
    pendingVideos,
    shotVideos,
    handleGenerateShotVideo,
    handleGenerateAllVideos,
    setShotVideos,
    setPendingVideos,
    checkVideoTaskStatus,
    fetchVideoTasks,
  } = useVideoGeneration();

  const {
    transitionVideos,
    generatingTransitions,
    currentTransition,
    transitionWorkflows,
    selectedTransitionWorkflow,
    transitionDuration,
    handleGenerateTransition,
    handleGenerateAllTransitions,
    setTransitionVideos,
    setGeneratingTransitions,
    setCurrentTransition,
    setSelectedTransitionWorkflow,
    setTransitionDuration,
    fetchTransitionWorkflows,
    fetchTransitionTasks,
    checkTransitionTaskStatus,
  } = useTransitionGeneration();

  // UI 状态
  const [activeTab, setActiveTab] = useState<'json' | 'characters' | 'scenes' | 'script'>('json');
  const [currentShot, setCurrentShot] = useState(1);
  const [currentVideo, setCurrentVideo] = useState(1);
  const [jsonEditMode, setJsonEditMode] = useState<'text' | 'table'>('text');
  const [showFullTextModal, setShowFullTextModal] = useState(false);
  const [showMergedImageModal, setShowMergedImageModal] = useState(false);
  const [showImagePreview, setShowImagePreview] = useState(false);
  const [previewImageUrl, setPreviewImageUrl] = useState<string | null>(null);
  const [previewImageIndex, setPreviewImageIndex] = useState<number>(0);
  const [mergedImage, setMergedImage] = useState<string | null>(null);
  const [isMerging, setIsMerging] = useState(false);
  const [editorKey, setEditorKey] = useState<number>(0);
  const [splitConfirmDialog, setSplitConfirmDialog] = useState<{ isOpen: boolean; hasResources: boolean }>({ isOpen: false, hasResources: false });
  const [showTransitionConfig, setShowTransitionConfig] = useState<boolean>(false);

  // 生成状态
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSplitting, setIsSplitting] = useState(false);
  const [isSavingJson, setIsSavingJson] = useState(false);

  // Shot 工作流状态
  const [shotWorkflows, setShotWorkflows] = useState<any[]>([]);
  const [activeShotWorkflow, setActiveShotWorkflow] = useState<any>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);

  // 验证分镜场景是否在场景库中
  const getInvalidSceneShots = () => {
    if (!editableJson.trim() || scenes.length === 0) return [];
    try {
      const parsed = JSON.parse(editableJson);
      if (!parsed.shots || !Array.isArray(parsed.shots)) return [];
      const sceneNames = scenes.map(s => s.name);
      return parsed.shots.filter((shot: any) => shot.scene && !sceneNames.includes(shot.scene));
    } catch (e) {
      return [];
    }
  };

  const invalidSceneShots = getInvalidSceneShots();
  const hasInvalidScenesInShots = invalidSceneShots.length > 0;

  // 获取真实章节数据和角色列表
  useEffect(() => {
    if (cid && id) {
      fetchNovel(id);
      fetchCharacters(id);
      fetchScenes(id);
      fetchChapter(id, cid);
      fetchTransitionWorkflows();
      fetchShotWorkflows();
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

  // 键盘左右方向键切换分镜或图片预览
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (showImagePreview && previewImageUrl) {
        if (e.key === 'ArrowLeft') {
          e.preventDefault();
          navigateImagePreview('prev');
          return;
        } else if (e.key === 'ArrowRight') {
          e.preventDefault();
          navigateImagePreview('next');
          return;
        } else if (e.key === 'Escape') {
          e.preventDefault();
          setShowImagePreview(false);
          return;
        }
      }
      
      if (!parsedData?.shots || parsedData.shots.length === 0) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      
      if (e.key === 'ArrowLeft') {
        setCurrentShot(prev => Math.max(1, prev - 1));
      } else if (e.key === 'ArrowRight') {
        setCurrentShot(prev => Math.min(parsedData?.shots?.length || 1, prev + 1));
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [parsedData?.shots?.length, showImagePreview, previewImageUrl, previewImageIndex]);
  
  // 图片预览导航
  const navigateImagePreview = (direction: 'prev' | 'next') => {
    const allImages = parsedData?.shots?.map((_shot: any, idx: number) => {
      const shotNum = idx + 1;
      return shotImages[shotNum] || parsedData?.shots?.[idx]?.image_url;
    }).filter(Boolean) as string[] || [];
    
    if (allImages.length <= 1) return;
    
    let newIndex: number;
    if (direction === 'prev') {
      newIndex = previewImageIndex === 0 ? allImages.length - 1 : previewImageIndex - 1;
    } else {
      newIndex = previewImageIndex === allImages.length - 1 ? 0 : previewImageIndex + 1;
    }
    
    setPreviewImageIndex(newIndex);
    setPreviewImageUrl(allImages[newIndex] || null);
    setCurrentShot(newIndex + 1);
  };

  // 轮询任务状态
  useEffect(() => {
    if (!cid || !id) return;
    
    let isRunning = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    
    const poll = async () => {
      if (pendingShots.size === 0 && pendingVideos.size === 0 && generatingTransitions.size === 0) {
        timeoutId = setTimeout(poll, 3000);
        return;
      }
      
      if (isRunning) {
        timeoutId = setTimeout(poll, 3000);
        return;
      }
      
      isRunning = true;
      try {
        await Promise.all([
          checkShotTaskStatus(cid, () => fetchChapter(id, cid)),
          checkVideoTaskStatus(cid, () => fetchChapter(id, cid)),
          checkTransitionTaskStatus(cid, () => fetchChapter(id, cid)),
        ]);
      } finally {
        isRunning = false;
        timeoutId = setTimeout(poll, 3000);
      }
    };
    
    timeoutId = setTimeout(poll, 3000);
    
    return () => {
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [cid, id, pendingShots.size, pendingVideos.size, generatingTransitions.size]);

  // 获取 shot 工作流列表
  const fetchShotWorkflows = async () => {
    try {
      const res = await fetch(`${API_BASE}/workflows/?type=shot`);
      const data = await res.json();
      if (data.success) {
        setShotWorkflows(data.data || []);
        const activeWorkflow = data.data.find((w: any) => w.isActive);
        if (activeWorkflow) {
          setActiveShotWorkflow(activeWorkflow);
        }
      }
    } catch (error) {
      console.error('获取 shot 工作流失败:', error);
    }
  };

  // 合并角色图
  const handleMergeCharacterImages = async () => {
    const currentShotData = parsedData?.shots?.[currentShot - 1];
    const shotCharacters = currentShotData?.characters || [];
    
    if (shotCharacters.length === 0) {
      toast.warning(t('chapterGenerate.noCharactersInShot'));
      return;
    }

    setIsMerging(true);
    try {
      const imageUrls = shotCharacters.map((name: string) => getCharacterImage(name)).filter(Boolean) as string[];
      
      if (imageUrls.length === 0) {
        toast.warning(t('chapterGenerate.characterImagesNotGenerated'));
        return;
      }

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

      const images = await Promise.all(
        imageUrls.map(url => new Promise<HTMLImageElement>((resolve, reject) => {
          const img = new Image();
          img.crossOrigin = 'anonymous';
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = url;
        }))
      );

      const canvas = document.createElement('canvas');
      const cellWidth = 200;
      const cellHeight = 200;
      const nameHeight = 30;
      const padding = 10;
      
      canvas.width = cols * (cellWidth + padding) + padding;
      canvas.height = rows * (cellHeight + nameHeight + padding) + padding;
      
      const ctx = canvas.getContext('2d')!;
      
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      
      images.forEach((img, index) => {
        const col = index % cols;
        const row = Math.floor(index / cols);
        const x = padding + col * (cellWidth + padding);
        const y = padding + row * (cellHeight + nameHeight + padding);
        
        const scale = Math.min(cellWidth / img.width, cellHeight / img.height);
        const drawWidth = img.width * scale;
        const drawHeight = img.height * scale;
        const drawX = x + (cellWidth - drawWidth) / 2;
        const drawY = y + (cellHeight - drawHeight) / 2;
        
        ctx.drawImage(img, drawX, drawY, drawWidth, drawHeight);
        
        ctx.fillStyle = '#333333';
        ctx.font = 'bold 14px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(shotCharacters[index], x + cellWidth / 2, y + cellHeight + 20);
      });
      
      const mergedUrl = canvas.toDataURL('image/png');
      setMergedImage(mergedUrl);
    } catch (error) {
      console.error('合并角色图失败:', error);
      toast.error(t('chapterGenerate.mergeFailedRetry'));
    } finally {
      setIsMerging(false);
    }
  };

  // 根据画面比例计算图片容器尺寸
  const getAspectRatioStyle = (): React.CSSProperties => {
    const aspectRatio = novel?.aspectRatio || '16:9';
    const baseSize = 120;
    
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
    const character = characters.find(c => c.name === characterName);
    if (character) {
      navigate(`/characters?novel_id=${id}&highlight=${character.id}`);
    } else {
      navigate(`/characters?novel_id=${id}`);
    }
  };

  // 跳转到场景库页面
  const handleRegenerateScene = (sceneName: string) => {
    const scene = scenes.find(s => s.name === sceneName);
    if (scene) {
      navigate(`/scenes?novel_id=${id}&highlight=${scene.id}`);
    } else {
      navigate(`/scenes?novel_id=${id}`);
    }
  };

  // 步骤标签翻译
  const getStepLabel = (key: string) => {
    const labels: Record<string, string> = {
      'content': t('chapterGenerate.stepContent'),
      'ai-parse': t('chapterGenerate.stepAiParse'),
      'json': t('chapterGenerate.stepJson'),
      'character': t('chapterGenerate.stepCharacter'),
      'shots': t('chapterGenerate.stepShots'),
      'videos': t('chapterGenerate.stepVideos'),
      'transitions': t('chapterGenerate.stepTransitions'),
      'compose': t('chapterGenerate.stepCompose'),
    };
    return labels[key] || key;
  };

  // 处理AI拆分分镜头按钮点击
  const handleSplitChapterClick = () => {
    if (!id || !cid) return;
    
    const hasResources = !!parsedData || 
      Object.keys(shotImages).length > 0 || 
      Object.keys(shotVideos).length > 0 ||
      Object.keys(transitionVideos).length > 0 ||
      !!mergedImage;
    
    if (hasResources) {
      setSplitConfirmDialog({ isOpen: true, hasResources: true });
    } else {
      doSplitChapter();
    }
  };

  // 确认后执行拆分
  const doSplitChapter = async () => {
    if (!id || !cid) return;
    
    setSplitConfirmDialog({ isOpen: false, hasResources: false });
    
    try {
      const clearRes = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/clear-resources`, {
        method: 'POST'
      });
      const clearData = await clearRes.json();
      if (!clearData.success) {
        console.error('清除资源失败:', clearData.message);
      }
    } catch (error) {
      console.error('清除资源请求失败:', error);
    }
    
    setIsSplitting(true);
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/split/`, {
        method: 'POST'
      });
      const data = await res.json();
      
      if (data.success) {
        setShotImages({});
        setShotVideos({});
        setTransitionVideos({});
        setMergedImage(null);
        setParsedData(data.data);
        setEditableJson(JSON.stringify(data.data, null, 2));
        setEditorKey(prev => prev + 1);
        setActiveTab('json');
        toast.success(t('chapterGenerate.splitSuccess'));
        fetchChapter(id, cid);
      } else {
        toast.error(data.message || t('chapterGenerate.splitFailed'));
      }
    } catch (error) {
      console.error('拆分章节失败:', error);
      toast.error(t('chapterGenerate.splitFailedCheckNetwork'));
    } finally {
      setIsSplitting(false);
    }
  };

  // 保存JSON修改
  const handleSaveJson = async () => {
    if (!id || !cid || !editableJson.trim()) return;
    
    let parsedJson;
    try {
      parsedJson = JSON.parse(editableJson);
    } catch (e) {
      toast.error(t('chapterGenerate.jsonFormatErrorCheck'));
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
        toast.success(t('chapterGenerate.saveSuccess'));
      } else {
        toast.error(data.message || t('chapterGenerate.saveFailed'));
      }
    } catch (error) {
      console.error('保存JSON失败:', error);
      toast.error(t('chapterGenerate.saveFailedCheckNetwork'));
    } finally {
      setIsSavingJson(false);
    }
  };

  // 步骤指示器
  const renderStepIndicator = () => (
    <div className="card mb-6">
      <div className="flex items-center justify-between">
        {STEPS_CONFIG.map((step, index) => {
          const StepIcon = step.icon;
          
          return (
            <div key={step.key} className="flex items-center flex-1">
              <div className="flex flex-col items-center">
                <div className={`w-14 h-14 rounded-xl flex items-center justify-center mb-2 bg-gradient-to-br ${step.color} text-white shadow-md`}>
                  <StepIcon className="h-7 w-7" />
                </div>
                <span className="text-xs font-medium text-gray-700 text-center whitespace-nowrap">
                  {getStepLabel(step.key)}
                </span>
              </div>
              {index < STEPS_CONFIG.length - 1 && (
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

  // 标签页
  const renderTabs = () => (
    <div className="flex gap-4 mb-4 border-b border-gray-200">
      {[
        { key: 'characters', label: t('chapterGenerate.characterList') },
        { key: 'scenes', label: t('chapterGenerate.sceneList') },
        { key: 'script', label: t('chapterGenerate.shotScript') }
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

  // JSON 编辑器组件
  const renderJsonEditor = () => (
    <div className="space-y-3">
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
            {t('chapterGenerate.jsonText')}
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
            {t('chapterGenerate.tableEdit')}
          </button>
        </div>
        <button
          onClick={handleSaveJson}
          disabled={isSavingJson || !editableJson.trim()}
          className="btn-primary text-sm py-2 px-4 disabled:opacity-50"
        >
          {isSavingJson ? (
            <><Loader2 className="h-4 w-4 mr-2 animate-spin" />{t('common.saving')}</>
          ) : (
            <><Save className="h-4 w-4 mr-2" />{t('chapterGenerate.saveChanges')}</>
          )}
        </button>
      </div>
      
      {jsonEditMode === 'text' ? (
        <textarea
          className="w-full h-64 bg-gray-900 text-gray-100 p-4 rounded-lg font-mono text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:outline-none"
          value={editableJson}
          onChange={(e) => setEditableJson(e.target.value)}
          placeholder={t('chapterGenerate.jsonPlaceholder')}
          spellCheck={false}
        />
      ) : (
        <JsonTableEditor 
          key={editorKey}
          value={editableJson}
          onChange={setEditableJson}
          availableScenes={scenes.map(s => s.name)}
          availableCharacters={characters.map(c => c.name)}
          activeShotWorkflow={activeShotWorkflow}
        />
      )}
    </div>
  );

  // 标签页内容
  const renderTabContent = () => {
    switch (activeTab) {
      case 'characters':
        return (
          <div className="space-y-2">
            {parsedData?.characters?.map((name: string, idx: number) => (
              <div key={idx} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                <Users className="h-5 w-5 text-blue-500" />
                <span className="font-medium">{name}</span>
              </div>
            )) || <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noCharacterData')}</p>}
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
            )) || <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noSceneData')}</p>}
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
            )) || <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noShotDataYet')}</p>}
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
              {loading ? t('chapterGenerate.loading') : chapter?.title || t('chapterGenerate.unnamedChapter')}
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
              <h3 className="font-semibold text-gray-900">{t('chapterGenerate.originalContent')}</h3>
              <button 
                onClick={() => setShowFullTextModal(true)}
                className="text-sm text-blue-600 hover:underline"
              >
                {t('chapterGenerate.expandFullText')}
              </button>
            </div>
            <p className="text-gray-600 text-sm leading-relaxed line-clamp-3">
              {loading ? t('chapterGenerate.loading') : chapter?.content || t('chapterGenerate.noContent')}
            </p>
            <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
              {hasInvalidScenesInShots && !isSplitting && activeShotWorkflow?.extension?.reference_image_count === 'dual' && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2">
                  <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-amber-700">
                      {t('chapterGenerate.sceneValidation.warning')}
                    </p>
                    <p className="text-xs text-amber-600 mt-1">
                      {t('chapterGenerate.sceneValidation.detected', { count: invalidSceneShots.length })}
                    </p>
                  </div>
                </div>
              )}
              <button 
                onClick={handleSplitChapterClick}
                disabled={isSplitting}
                className={`w-full py-3 px-4 text-white rounded-lg font-medium transition-all shadow-sm hover:shadow-md flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed ${
                  hasInvalidScenesInShots && !isSplitting && activeShotWorkflow?.extension?.reference_image_count === 'dual'
                    ? 'bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600'
                    : 'bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600'
                }`}
              >
                {isSplitting ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Sparkles className="h-5 w-5" />
                )}
                {isSplitting ? t('chapterGenerate.aiSplitting') : t('chapterGenerate.aiSplitShots')}
              </button>
            </div>
          </div>

          {/* JSON 编辑器 */}
          <div className="card">
            {renderJsonEditor()}
          </div>

          {/* 人设图片 */}
          <div className="card">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-gray-900">
                {t('chapterGenerate.characterImages')}
                <span className="text-xs font-normal text-gray-500 ml-2">
                  ({novel?.aspectRatio || '16:9'})
                </span>
              </h3>
              <Link 
                to={`/characters?novel=${id}`}
                className="text-sm text-blue-600 hover:text-blue-700 hover:underline flex items-center gap-1"
              >
                <Sparkles className="h-4 w-4" />
                {t('chapterGenerate.aiGenerateCharacter')}
              </Link>
            </div>
            <div className="flex gap-4 flex-wrap">
              {(() => {
                const currentShotData = parsedData?.shots?.[currentShot - 1];
                const currentShotCharacters = currentShotData?.characters || [];
                
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
                        {t('chapterGenerate.regenerate')}
                      </button>
                    </div>
                  );
                });
              })() || <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noCharacterImages')}</p>}
            </div>
          </div>

          {/* 场景图片 */}
          <div className="card">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-gray-900">
                {t('chapterGenerate.sceneImages')}
                <span className="text-xs font-normal text-gray-500 ml-2">
                  ({novel?.aspectRatio || '16:9'})
                </span>
              </h3>
              <Link 
                to={`/scenes?novel_id=${id}`}
                className="text-sm text-green-600 hover:text-green-700 hover:underline flex items-center gap-1"
              >
                <Sparkles className="h-4 w-4" />
                {t('chapterGenerate.aiGenerateScene')}
              </Link>
            </div>
            
            {activeShotWorkflow && activeShotWorkflow.extension?.reference_image_count !== 'dual' && (
              <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
                <AlertCircle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-amber-700">
                  {t('chapterGenerate.dualReferenceWorkflowNotActive')}
                </p>
              </div>
            )}
            
            <div className="flex gap-4 flex-wrap">
              {(() => {
                const currentShotData = parsedData?.shots?.[currentShot - 1];
                const currentShotScene = currentShotData?.scene || '';
                
                const sortedScenes = [...(parsedData?.scenes || [])].sort((a: string, b: string) => {
                  const aInShot = a === currentShotScene;
                  const bInShot = b === currentShotScene;
                  if (aInShot && !bInShot) return -1;
                  if (!aInShot && bInShot) return 1;
                  return 0;
                });
                
                return sortedScenes.map((name: string, idx: number) => {
                  const imageUrl = getSceneImage(name);
                  const aspectStyle = getAspectRatioStyle();
                  const isInCurrentShot = name === currentShotScene;
                  
                  return (
                    <div key={idx} className={`text-center relative ${isInCurrentShot ? 'order-first' : ''}`}>
                      <div 
                        className={`rounded-xl bg-gradient-to-br from-green-400 to-teal-500 flex items-center justify-center mb-2 overflow-hidden relative cursor-pointer ${
                          isInCurrentShot ? 'ring-2 ring-green-500 ring-offset-2' : ''
                        }`}
                        style={aspectStyle}
                        onClick={() => {
                          if (imageUrl) {
                            setPreviewImageUrl(imageUrl);
                            setShowImagePreview(true);
                          }
                        }}
                      >
                        {imageUrl ? (
                          <img 
                            src={imageUrl} 
                            alt={name}
                            className="w-full h-full object-cover hover:scale-105 transition-transform"
                          />
                        ) : (
                          <MapPin className="h-10 w-10 text-white" />
                        )}
                        {isInCurrentShot && (
                          <div className="absolute top-1 right-1 w-5 h-5 bg-green-500 rounded-full flex items-center justify-center shadow-sm">
                            <CheckCircle className="h-3.5 w-3.5 text-white" />
                          </div>
                        )}
                      </div>
                      <p className="text-sm font-medium">{name}</p>
                      <button 
                        onClick={() => handleRegenerateScene(name)}
                        className="text-xs text-green-600 hover:underline mt-1"
                      >
                        {t('chapterGenerate.regenerate')}
                      </button>
                    </div>
                  );
                });
              })() || <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noSceneImages')}</p>}
            </div>
          </div>

          {/* 分镜图片 */}
          <div className="card">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-gray-900">{t('chapterGenerate.shotImages')} ({parsedData?.shots?.length || 0}{t('chapterGenerate.unit')})</h3>
              <div className="flex items-center gap-3">
                {(parsedData?.shots?.length ?? 0) > 0 && (
                  <>
                    <button 
                      onClick={() => handleGenerateAllShots(parsedData, id, cid)}
                      disabled={isGeneratingAll || pendingShots.size > 0}
                      className="btn-secondary text-sm py-1.5 text-blue-600 hover:text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                    >
                      {isGeneratingAll ? (
                        <><Loader2 className="h-3 w-3 mr-1 animate-spin" />{t('chapterGenerate.batchSubmitting')}</>
                      ) : (
                        <><RefreshCw className="h-3 w-3 mr-1" />{t('chapterGenerate.generateAllShots')}</>
                      )}
                    </button>
                    <button 
                      onClick={() => handleGenerateAllVideos(parsedData, shotImages, id, cid)}
                      disabled={generatingVideos.size > 0 || pendingVideos.size > 0}
                      className="btn-secondary text-sm py-1.5 text-purple-600 hover:text-purple-700 hover:bg-purple-50 disabled:opacity-50"
                      title={t('chapterGenerate.generateVideoForShotsWithImages')}
                    >
                      <Film className="h-3 w-3 mr-1" />
                      {t('chapterGenerate.generateAllShotVideos')}
                    </button>
                  </>
                )}
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
            </div>
            {(parsedData?.shots?.length ?? 0) > 0 ? (
              <>
                <div className="flex gap-3 overflow-x-auto pb-2">
                  {parsedData?.shots?.map((shot: any, index: number) => {
                    const shotNum = index + 1;
                    const isSubmitting = generatingShots.has(shotNum);
                    const isPending = pendingShots.has(shotNum);
                    const imageUrl = (!isSubmitting && !isPending) ? (shotImages[shotNum] || shot.image_url) : null;
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
                        
                        {isSubmitting && (
                          <div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center">
                            <Loader2 className="h-5 w-5 text-white animate-spin mb-1" />
                            <span className="text-[10px] text-white font-medium">{t('chapterGenerate.submitting')}</span>
                          </div>
                        )}
                        
                        {isPending && !isSubmitting && (
                          <div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center">
                            <div className="flex items-center gap-1 mb-1">
                              <div className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse" />
                              <div className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse delay-75" />
                              <div className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse delay-150" />
                            </div>
                            <span className="text-[10px] text-white font-medium">{t('chapterGenerate.inQueue')}</span>
                          </div>
                        )}
                        
                        {(isSubmitting || isPending) && (
                          <div className="absolute top-1 right-1">
                            <div className="w-2 h-2 bg-yellow-400 rounded-full animate-ping" />
                          </div>
                        )}
                        
                        <span className="absolute bottom-1 left-2 text-xs text-white font-bold bg-blue-600/90 px-1.5 py-0.5 rounded shadow-lg">
                          {t('chapterGenerate.shot')}{shot.id}
                        </span>
                      </div>
                    );
                  })}
                </div>
                {generatingShots.has(currentShot) || pendingShots.has(currentShot) ? (
                  <div className="mt-4 mb-4">
                    <div className="aspect-video rounded-lg overflow-hidden bg-gradient-to-br from-blue-50 to-indigo-50 flex flex-col items-center justify-center border-2 border-dashed border-blue-200">
                      <Loader2 className="h-12 w-12 text-blue-400 mb-3 animate-spin" />
                      <span className="text-blue-500 text-sm font-medium">
                        {generatingShots.has(currentShot) ? t('chapterGenerate.submitting') : t('chapterGenerate.inQueue')}
                      </span>
                    </div>
                  </div>
                ) : (shotImages[currentShot] || parsedData?.shots?.[currentShot - 1]?.image_url) ? (
                  <div className="mt-4 mb-4">
                    <div 
                      className="aspect-video rounded-lg overflow-hidden bg-gray-100 cursor-pointer"
                      onClick={() => {
                        const url = shotImages[currentShot] || parsedData?.shots?.[currentShot - 1]?.image_url;
                        if (url) {
                          setPreviewImageUrl(url);
                          setPreviewImageIndex(currentShot - 1);
                          setShowImagePreview(true);
                        }
                      }}
                    >
                      <img 
                        src={shotImages[currentShot] || parsedData?.shots?.[currentShot - 1]?.image_url}
                        alt={`${t('chapterGenerate.shot')}${currentShot}`}
                        className="w-full h-full object-contain"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 mb-4">
                    <div className="aspect-video rounded-lg overflow-hidden bg-gradient-to-br from-purple-100 to-pink-100 flex flex-col items-center justify-center border-2 border-dashed border-purple-200">
                      <ImageIcon className="h-16 w-16 text-purple-300 mb-2" />
                      <span className="text-purple-400 text-sm">{t('chapterGenerate.shotImageNotGenerated')}</span>
                    </div>
                  </div>
                )}

                <div className="flex gap-3 mt-4 flex-wrap">
                  <button 
                    onClick={() => handleGenerateShotImage(currentShot, id, cid)}
                    disabled={generatingShots.has(currentShot) || pendingShots.has(currentShot)}
                    className="btn-secondary text-sm py-1.5 disabled:opacity-50"
                  >
                    {generatingShots.has(currentShot) ? (
                      <><Loader2 className="h-3 w-3 mr-1 animate-spin" />{t('chapterGenerate.submitting')}</>
                    ) : pendingShots.has(currentShot) ? (
                      <><Clock className="h-3 w-3 mr-1" />{t('chapterGenerate.inQueue')}</>
                    ) : (
                      <><RefreshCw className="h-3 w-3 mr-1" />{t('chapterGenerate.regenerateShotImage')}</>
                    )}
                  </button>
                  <button 
                    onClick={() => triggerShotFileUpload(currentShot)}
                    disabled={uploadingShotIndex === currentShot || generatingShots.has(currentShot) || pendingShots.has(currentShot)}
                    className="btn-secondary text-sm py-1.5 text-green-600 hover:text-green-700 hover:bg-green-50 disabled:opacity-50"
                    title={t('chapterGenerate.orUploadLocal')}
                  >
                    {uploadingShotIndex === currentShot ? (
                      <><Loader2 className="h-3 w-3 mr-1 animate-spin" />{t('common.upload')}...</>
                    ) : (
                      <><Upload className="h-3 w-3 mr-1" />{t('chapterGenerate.uploadImage')}</>
                    )}
                  </button>
                  <button 
                    onClick={() => handleGenerateShotVideo(currentShot, id, cid)}
                    disabled={
                      !(shotImages[currentShot] || parsedData?.shots?.[currentShot - 1]?.image_url) ||
                      generatingVideos.has(currentShot) || 
                      pendingVideos.has(currentShot)
                    }
                    className="btn-secondary text-sm py-1.5 text-purple-600 hover:text-purple-700 hover:bg-purple-50 disabled:opacity-50"
                    title={
                      !(shotImages[currentShot] || parsedData?.shots?.[currentShot - 1]?.image_url)
                        ? t('chapterGenerate.generateShotImageFirst')
                        : pendingVideos.has(currentShot)
                        ? t('chapterGenerate.videoGenerating')
                        : t('chapterGenerate.generateVideoBasedOnImage')
                    }
                  >
                    {generatingVideos.has(currentShot) ? (
                      <><Loader2 className="h-3 w-3 mr-1 animate-spin" />{t('chapterGenerate.submitting')}</>
                    ) : pendingVideos.has(currentShot) ? (
                      <><Clock className="h-3 w-3 mr-1" />{t('chapterGenerate.generating')}</>
                    ) : (
                      <><Film className="h-3 w-3 mr-1" />{t('chapterGenerate.generateShotVideo')}</>
                    )}
                  </button>
                  <button 
                    onClick={() => setShowMergedImageModal(true)}
                    disabled={!mergedImage}
                    className="btn-secondary text-sm py-1.5 text-red-600 hover:text-red-700 hover:bg-red-50 disabled:opacity-50"
                    title={mergedImage ? t('chapterGenerate.viewMergedImage') : t('chapterGenerate.generateMergedImageFirst')}
                  >
                    <Grid3x3 className="h-3 w-3 mr-1" />
                    {t('chapterGenerate.viewMergedImage')}
                  </button>
                </div>
              </>
            ) : (
              <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noShotImages')}</p>
            )}
          </div>

          {/* 分镜视频 */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <h3 className="font-semibold text-gray-900">
                  {currentTransition && transitionVideos[currentTransition] 
                    ? t('chapterGenerate.transitionPreview', { transition: currentTransition })
                    : t('chapterGenerate.shotVideosTitle')}
                </h3>
                {currentTransition && transitionVideos[currentTransition] && (
                  <button
                    onClick={() => setCurrentTransition('')}
                    className="text-xs px-2 py-1 bg-orange-100 text-orange-700 rounded hover:bg-orange-200 transition-colors"
                  >
                    {t('chapterGenerate.backToShotVideos')}
                  </button>
                )}
              </div>
              {parsedData?.shots && parsedData.shots.length > 1 && (
                <button
                  onClick={() => handleGenerateAllTransitions(parsedData, id, cid)}
                  disabled={generatingTransitions.size > 0}
                  className="btn-secondary text-sm py-1.5 text-orange-600 hover:text-orange-700 hover:bg-orange-50 disabled:opacity-50"
                  title={t('chapterGenerate.generateTransitionsForAll')}
                >
                  {generatingTransitions.size > 0 ? (
                    <><Loader2 className="h-3 w-3 mr-1 animate-spin" />{t('chapterGenerate.generating')}</>
                  ) : (
                    <><RefreshCw className="h-3 w-3 mr-1" />{t('chapterGenerate.generateAllTransitions')}</>
                  )}
                </button>
              )}
            </div>
            <div className="aspect-video bg-gray-900 rounded-lg flex items-center justify-center mb-4 overflow-hidden">
              {currentTransition && transitionVideos[currentTransition] ? (
                <video
                  key={`transition-${currentTransition}`}
                  src={transitionVideos[currentTransition]}
                  controls
                  autoPlay
                  className="w-full h-full"
                  poster={shotImages[parseInt(currentTransition.split('-')[0])]}
                />
              ) : shotVideos[currentVideo] ? (
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
                    {generatingVideos.has(currentVideo) ? t('chapterGenerate.generating') : pendingVideos.has(currentVideo) ? t('chapterGenerate.inQueue') : t('chapterGenerate.noVideo')}
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
                    <span className="text-sm font-medium text-gray-700">{t('chapterGenerate.transitionConfig')}</span>
                    {showTransitionConfig && (
                      <span className="text-xs px-2 py-0.5 bg-orange-100 text-orange-700 rounded">{t('chapterGenerate.customEnabled')}</span>
                    )}
                  </div>
                  <button
                    onClick={() => setShowTransitionConfig(!showTransitionConfig)}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    {showTransitionConfig ? t('chapterGenerate.collapseConfig') : t('chapterGenerate.expandConfig')}
                  </button>
                </div>
                
                {showTransitionConfig && (
                  <div className="space-y-3 pt-2 border-t border-gray-200">
                    <div className="flex items-center gap-3">
                      <label className="text-sm text-gray-600 whitespace-nowrap">{t('chapterGenerate.workflow')}:</label>
                      <select
                        value={selectedTransitionWorkflow}
                        onChange={(e) => setSelectedTransitionWorkflow(e.target.value)}
                        className="flex-1 text-sm border border-gray-300 rounded px-2 py-1 focus:ring-2 focus:ring-orange-500 focus:border-orange-500"
                      >
                        {transitionWorkflows.map((wf) => {
                          const displayName = wf.nameKey ? t(wf.nameKey, { defaultValue: wf.name }) : wf.name;
                          return (
                            <option key={wf.id} value={wf.id}>
                              {displayName} {wf.isActive ? `(${t('chapterGenerate.default')})` : ''}
                            </option>
                          );
                        })}
                      </select>
                    </div>
                    
                    <div className="flex items-center gap-3">
                      <label className="text-sm text-gray-600 whitespace-nowrap">{t('chapterGenerate.duration')}:</label>
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
                        <span className="text-sm text-gray-700 w-16 text-right">{transitionDuration}{t('chapterGenerate.second')}</span>
                      </div>
                    </div>
                    
                    <div className="flex items-center justify-between pt-2 border-t border-gray-200">
                      <p className="text-xs text-gray-500">
                        {t('chapterGenerate.configTip')}
                      </p>
                      <button
                        onClick={() => {
                          const defaultWorkflow = transitionWorkflows.find((w: any) => w.isActive);
                          if (defaultWorkflow) {
                            setSelectedTransitionWorkflow(defaultWorkflow.id);
                          } else if (transitionWorkflows.length > 0) {
                            setSelectedTransitionWorkflow(transitionWorkflows[0].id);
                          }
                          setTransitionDuration(2);
                          toast.info(t('chapterGenerate.resetToDefault'));
                        }}
                        className="text-xs px-3 py-1.5 bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition-colors"
                      >
                        {t('chapterGenerate.reset')}
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
                const isImagePending = pendingShots.has(shotNum) || generatingShots.has(shotNum);
                const imageUrl = !isImagePending ? (shotImages[shotNum] || shot.image_url) : null;
                const hasVideo = !!shotVideos[shotNum];
                const isPending = pendingVideos.has(shotNum);
                const isGenerating = generatingVideos.has(shotNum);
                const duration = shot.duration || 4;
                
                return (
                  <div key={shot.id} className="flex items-center gap-2">
                    <div
                      onClick={() => {
                        if (currentTransition) {
                          setCurrentTransition('');
                        }
                        setCurrentVideo(shotNum);
                      }}
                      className={`relative flex-shrink-0 w-32 h-24 rounded-lg overflow-hidden cursor-pointer transition-transform hover:scale-105 ${
                        currentVideo === shotNum && !currentTransition ? 'ring-2 ring-offset-2 ring-purple-500' : ''
                      }`}
                    >
                      {imageUrl ? (
                        <img 
                          src={imageUrl} 
                          alt={`${t('chapterGenerate.shot')}${shot.id}`}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                          <ImageIcon className="h-6 w-6 text-white/70" />
                        </div>
                      )}
                      
                      {hasVideo && (
                        <div className="absolute top-1 right-1 w-2 h-2 bg-green-500 rounded-full" />
                      )}
                      {(isPending || isGenerating) && (
                        <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                          <Loader2 className="h-4 w-4 text-white animate-spin" />
                        </div>
                      )}
                      
                      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1 flex items-center justify-between">
                        <span className="text-xs text-white font-bold bg-blue-600/90 px-1.5 py-0.5 rounded">{t('chapterGenerate.shot')}{shot.id}</span>
                        <span className="text-[10px] text-white/90 font-medium">{duration}{t('chapterGenerate.second')}</span>
                      </div>
                    </div>
                    
                    {index < (parsedData?.shots?.length || 0) - 1 && (
                      <TransitionVideoItem
                        fromIndex={shotNum}
                        toIndex={shotNum + 1}
                        fromVideo={shotVideos[shotNum]}
                        toVideo={shotVideos[shotNum + 1]}
                        fromImage={(!pendingShots.has(shotNum) && !generatingShots.has(shotNum)) ? (shotImages[shotNum] || shot.image_url) : undefined}
                        toImage={(!pendingShots.has(shotNum + 1) && !generatingShots.has(shotNum + 1)) ? (shotImages[shotNum + 1] || parsedData?.shots?.[shotNum]?.image_url) : undefined}
                        transitionVideo={transitionVideos[`${shotNum}-${shotNum + 1}`]}
                        isGenerating={generatingTransitions.has(`${shotNum}-${shotNum + 1}`)}
                        onGenerate={() => handleGenerateTransition(shotNum, shotNum + 1, true, id, cid)}
                        onRegenerate={() => handleGenerateTransition(shotNum, shotNum + 1, true, id, cid)}
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
              }) || <p className="text-gray-500 text-sm">{t('chapterGenerate.noVideos')}</p>}
            </div>
          </div>
        </div>

        {/* 右侧边栏 */}
        <div className="col-span-4 space-y-6">
          <div className="sticky top-6 space-y-4">
            <ComfyUIStatus />
            
            <MergeVideosCard
              novelId={id || ''}
              chapterId={cid || ''}
              shotVideos={shotVideos}
              transitionVideos={transitionVideos}
              chapter={chapter}
              aspectRatio={novel?.aspectRatio || '16:9'}
            />
            
            <DownloadMaterialsCard 
              novelId={id || ''} 
              chapterId={cid || ''}
              chapterTitle={chapter?.title || t('chapterGenerate.unnamedChapter')}
            />
          </div>
        </div>
      </div>

      {/* 展开全文弹层 */}
      {showFullTextModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-6 border-b">
              <h3 className="text-lg font-semibold text-gray-900">{t('chapterGenerate.originalContent')}</h3>
              <button
                onClick={() => setShowFullTextModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto flex-1">
              <h2 className="text-xl font-bold text-gray-900 mb-4">
                {chapter?.title || t('chapterGenerate.unnamedChapter')}
              </h2>
              <div className="prose prose-gray max-w-none">
                <p className="text-gray-700 leading-loose whitespace-pre-wrap text-base">
                  {chapter?.content || t('chapterGenerate.noContent')}
                </p>
              </div>
            </div>
            <div className="p-6 border-t bg-gray-50 flex justify-end">
              <button
                onClick={() => setShowFullTextModal(false)}
                className="btn-secondary"
              >
                {t('common.close')}
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
              alt={t('chapterGenerate.mergedCharacterImage')} 
              className="max-w-full max-h-[80vh] object-contain rounded-lg"
            />
            <div className="mt-4 text-center">
              <button
                onClick={() => {
                  const link = document.createElement('a');
                  link.download = `${t('chapterGenerate.characterImage')}_${t('chapterGenerate.shot')}${currentShot}.png`;
                  link.href = mergedImage;
                  link.click();
                }}
                className="btn-primary text-sm"
              >
                <Download className="h-4 w-4 mr-2" />
                {t('chapterGenerate.downloadImage')}
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
          <div className="relative max-w-5xl max-h-[90vh] w-full flex items-center" onClick={e => e.stopPropagation()}>
            <button
              onClick={(e) => { e.stopPropagation(); navigateImagePreview('prev'); }}
              className="absolute -left-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all z-10"
              title={`${t('chapterGenerate.previous')} (←)`}
            >
              <ChevronLeft className="h-10 w-10" />
            </button>
            
            <div className="flex-1 flex flex-col">
              <button
                onClick={() => setShowImagePreview(false)}
                className="absolute -top-10 right-0 p-2 text-white hover:text-gray-300 z-10"
              >
                <X className="h-6 w-6" />
              </button>
              
              <img 
                src={previewImageUrl} 
                alt={t('chapterGenerate.shotPreview')} 
                className="max-w-full max-h-[75vh] object-contain rounded-lg mx-auto"
              />
              
              <div className="mt-4 flex flex-col items-center gap-2">
                <button
                  onClick={() => {
                    const link = document.createElement('a');
                    link.download = `${t('chapterGenerate.shot')}_${currentShot}.png`;
                    link.href = previewImageUrl;
                    link.click();
                  }}
                  className="btn-primary text-sm"
                >
                  <Download className="h-4 w-4 mr-2" />
                  {t('chapterGenerate.downloadImage')}
                </button>
                
                <div className="text-gray-400 text-sm">
                  <span className="inline-flex items-center gap-2">
                    <kbd className="px-2 py-1 bg-gray-700 rounded text-xs">←</kbd>
                    <kbd className="px-2 py-1 bg-gray-700 rounded text-xs">→</kbd>
                    <span>{t('chapterGenerate.keyboardNavigate')}</span>
                    <span className="mx-2">|</span>
                    <span>{previewImageIndex + 1} / {parsedData?.shots?.filter((_shot: any, idx: number) => shotImages[idx + 1] || parsedData?.shots?.[idx]?.image_url).length || 0}</span>
                  </span>
                </div>
              </div>
            </div>
            
            <button
              onClick={(e) => { e.stopPropagation(); navigateImagePreview('next'); }}
              className="absolute -right-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all z-10"
              title={`${t('chapterGenerate.next')} (→)`}
            >
              <ChevronRight className="h-10 w-10" />
            </button>
          </div>
        </div>
      )}

      {/* 隐藏的文件输入元素 - 分镜图上传 */}
      <input
        type="file"
        ref={shotFileInputRef}
        onChange={(e) => handleUploadShotImage(e, id, cid, currentShot)}
        accept="image/png,image/jpeg,image/jpg,image/webp"
        className="hidden"
      />

      {/* AI拆分确认对话框 */}
      {splitConfirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-xl shadow-2xl border border-gray-700 w-full max-w-md p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-500" />
              </div>
              <h3 className="text-lg font-semibold text-white">
                {t('chapterGenerate.confirmResplit')}
              </h3>
            </div>
            
            <p className="text-gray-300 mb-4 leading-relaxed">
              {t('chapterGenerate.resplitWarning')}
            </p>
            
            <div className="bg-gray-900/50 rounded-lg p-4 mb-6 border border-gray-700">
              <ul className="space-y-2 text-sm text-gray-400">
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
                  {t('chapterGenerate.shotJsonData')}
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
                  {t('chapterGenerate.generatedShotImages')}
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
                  {t('chapterGenerate.generatedShotVideos')}
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
                  {t('chapterGenerate.generatedTransitionVideos')}
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-red-500 rounded-full"></span>
                  {t('chapterGenerate.mergedCharacterImage')}
                </li>
              </ul>
            </div>
            
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setSplitConfirmDialog({ isOpen: false, hasResources: false })}
                className="px-4 py-2 text-gray-300 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={doSplitChapter}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg transition-colors flex items-center gap-2"
              >
                <AlertTriangle className="w-4 h-4" />
                {t('chapterGenerate.confirmResplitBtn')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 隐藏的 canvas 元素 - 合并角色图 */}
      <canvas ref={canvasRef} className="hidden" />
    </div>
  );
}
