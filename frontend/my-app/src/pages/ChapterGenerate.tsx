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
  Film
} from 'lucide-react';
import type { Chapter, Novel } from '../types';
import { toast } from '../stores/toastStore';
import ComfyUIStatus from '../components/ComfyUIStatus';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 步骤定义
const STEPS = [
  { key: 'parse', label: '解析文本', icon: FileJson },
  { key: 'character', label: '生成人设', icon: Users },
  { key: 'shots', label: '生成分镜图', icon: ImageIcon },
  { key: 'videos', label: '生成视频', icon: Video },
  { key: 'compose', label: '合成视频', icon: CheckCircle }
];

interface Character {
  id: string;
  name: string;
  imageUrl: string | null;
  novelId: string;
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

  // 生成分镜图片
  const handleGenerateShotImage = async (shotIndex: number) => {
    setGeneratingShots(prev => new Set(prev).add(shotIndex));
    
    try {
      const res = await fetch(
        `${API_BASE}/novels/${id}/chapters/${cid}/shots/${shotIndex}/generate`,
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
          `${API_BASE}/novels/${id}/chapters/${cid}/shots/${shotIndex}/generate`,
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

  // 生成分镜视频
  const handleGenerateShotVideo = async (shotIndex: number) => {
    console.log('[ChapterGenerate] Generating video for shot', shotIndex);
    setGeneratingVideos(prev => new Set(prev).add(shotIndex));
    
    try {
      const res = await fetch(
        `${API_BASE}/novels/${id}/chapters/${cid}/shots/${shotIndex}/generate-video`,
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
    }
  }, [cid, id]);

  // 轮询任务状态
  useEffect(() => {
    if (!cid || !id) return;
    
    let isRunning = false;
    let timeoutId: NodeJS.Timeout | null = null;
    
    // 递归轮询，确保上一个请求完成后再等待 3 秒
    const poll = async () => {
      if (pendingShots.size === 0 && pendingVideos.size === 0) {
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
  }, [cid, id, pendingShots.size, pendingVideos.size]);

  // 检查分镜任务状态并更新
  const checkShotTaskStatus = async () => {
    if (pendingShots.size === 0 && pendingVideos.size === 0) return;
    
    try {
      // 同时检查图片和视频任务
      const [imageRes, videoRes] = await Promise.all([
        fetch(`${API_BASE}/tasks?type=shot_image&limit=50`),
        fetch(`${API_BASE}/tasks?type=shot_video&limit=50`)
      ]);
      const [imageData, videoData] = await Promise.all([
        imageRes.json(),
        videoRes.json()
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
    } catch (error) {
      console.error('检查任务状态失败:', error);
    }
  };

  // 获取分镜生成任务状态
  const fetchShotTasks = async () => {
    try {
      const res = await fetch(`${API_BASE}/tasks?type=shot_image&limit=50`);
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
      const res = await fetch(`${API_BASE}/tasks?type=shot_video&limit=50`);
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

  // 获取小说数据
  const fetchNovel = async () => {
    try {
      const res = await fetch(`${API_BASE}/novels/${id}`);
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
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}`);
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
              setPendingShots(prev => {
                const next = new Set(prev);
                parsed.shots.forEach((shot: any, index: number) => {
                  const shotNum = index + 1;
                  if (shot.image_url) {
                    newShotImages[shotNum] = shot.image_url;
                    next.delete(shotNum);
                  }
                });
                return next;
              });
              // 更新 shotImages
              if (Object.keys(newShotImages).length > 0) {
                setShotImages(prev => ({ ...prev, ...newShotImages }));
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
      }
    } catch (error) {
      console.error('获取章节数据失败:', error);
    } finally {
      setLoading(false);
      // 章节数据加载完成后，获取任务状态以恢复 pending 状态
      fetchShotTasks();
      fetchVideoTasks();
    }
  };

  // 获取角色列表
  const fetchCharacters = async () => {
    try {
      const res = await fetch(`${API_BASE}/characters?novel_id=${id}`);
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
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/split`, {
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
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}`, {
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
          <div className="space-y-3">
            <textarea
              className="w-full h-64 bg-gray-900 text-gray-100 p-4 rounded-lg font-mono text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:outline-none"
              value={editableJson}
              onChange={(e) => setEditableJson(e.target.value)}
              placeholder="点击 AI拆分分镜头 按钮生成数据，或直接输入JSON..."
              spellCheck={false}
            />
            <div className="flex justify-end">
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
                        if (url) window.open(url, '_blank');
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
                  {(shotImages[currentShot] || parsedData.shots[currentShot - 1]?.image_url) && (
                    <button 
                      className="btn-secondary text-sm py-1.5"
                      onClick={() => {
                        const url = shotImages[currentShot] || parsedData.shots[currentShot - 1]?.image_url;
                        if (url) {
                          setPreviewImageUrl(url);
                          setShowImagePreview(true);
                        }
                      }}
                    >
                      <Fullscreen className="h-3 w-3 mr-1" />
                      全屏查看
                    </button>
                  )}
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
                      <><RefreshCw className="h-3 w-3 mr-1" />重新生成全部</>
                    )}
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
            <h3 className="font-semibold text-gray-900 mb-4">分镜视频</h3>
            <div className="aspect-video bg-gray-900 rounded-lg flex items-center justify-center mb-4 overflow-hidden">
              {shotVideos[currentVideo] ? (
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
            <div className="flex gap-2 flex-wrap">
              {parsedData?.shots?.map((shot: any, index: number) => {
                const shotNum = index + 1;
                const hasVideo = !!shotVideos[shotNum];
                const isPending = pendingVideos.has(shotNum);
                const isGenerating = generatingVideos.has(shotNum);
                
                return (
                  <button
                    key={shot.id}
                    onClick={() => setCurrentVideo(shotNum)}
                    className={`px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1 ${
                      currentVideo === shotNum 
                        ? 'bg-purple-100 text-purple-600' 
                        : hasVideo
                          ? 'bg-green-100 text-green-600'
                          : isPending || isGenerating
                            ? 'bg-yellow-100 text-yellow-600'
                            : 'bg-gray-100 text-gray-700'
                    }`}
                  >
                    镜{shot.id}
                    {hasVideo && <span className="w-2 h-2 bg-green-500 rounded-full"></span>}
                    {(isPending || isGenerating) && <Loader2 className="h-3 w-3 animate-spin" />}
                  </button>
                );
              }) || <p className="text-gray-500 text-sm">暂无视频</p>}
            </div>
          </div>
        </div>

        {/* 右侧边栏 */}
        <div className="col-span-4 space-y-6">
          {/* 系统状态 */}
          <ComfyUIStatus />
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
