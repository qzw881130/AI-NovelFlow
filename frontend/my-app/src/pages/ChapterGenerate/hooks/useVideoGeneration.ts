import { useState, useCallback } from 'react';
import { API_BASE } from '../constants';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import type { ParsedData } from '../types';

interface UseVideoGenerationReturn {
  // 状态
  generatingVideos: Set<number>;
  pendingVideos: Set<number>;
  shotVideos: Record<number, string>;
  // 方法
  handleGenerateShotVideo: (shotIndex: number, novelId: string | undefined, chapterId: string | undefined) => Promise<void>;
  handleGenerateAllVideos: (parsedData: ParsedData | null, shotImages: Record<number, string>, novelId: string | undefined, chapterId: string | undefined) => Promise<void>;
  setShotVideos: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  setPendingVideos: React.Dispatch<React.SetStateAction<Set<number>>>;
  checkVideoTaskStatus: (chapterId: string | undefined, onRefresh: () => void) => Promise<void>;
  fetchVideoTasks: (chapterId: string | undefined) => Promise<void>;
}

export default function useVideoGeneration(): UseVideoGenerationReturn {
  const { t } = useTranslation();
  const [generatingVideos, setGeneratingVideos] = useState<Set<number>>(new Set());
  const [pendingVideos, setPendingVideos] = useState<Set<number>>(new Set());
  const [shotVideos, setShotVideos] = useState<Record<number, string>>({});

  // 生成分镜视频
  const handleGenerateShotVideo = useCallback(async (
    shotIndex: number,
    novelId: string | undefined,
    chapterId: string | undefined
  ) => {
    if (!novelId || !chapterId) return;
    
    console.log('[ChapterGenerate] Generating video for shot', shotIndex);
    setGeneratingVideos(prev => new Set(prev).add(shotIndex));
    
    try {
      const res = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/generate-video/`,
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
        toast.success(data.message || t('chapterGenerate.videoTaskCreated'));
      } else if (data.message?.includes('已有进行中的')) {
        toast.info(data.message);
      } else {
        toast.error(data.message || t('chapterGenerate.createVideoTaskFailed'));
      }
    } catch (error) {
      console.error('创建视频生成任务失败:', error);
      toast.error(t('chapterGenerate.createVideoTaskFailedCheckNetwork'));
    } finally {
      setGeneratingVideos(prev => {
        const next = new Set(prev);
        next.delete(shotIndex);
        return next;
      });
    }
  }, [t]);

  // 批量生成所有分镜视频
  const handleGenerateAllVideos = useCallback(async (
    parsedData: ParsedData | null,
    shotImages: Record<number, string>,
    novelId: string | undefined,
    chapterId: string | undefined
  ) => {
    if (!parsedData?.shots || parsedData.shots.length === 0 || !novelId || !chapterId) {
      toast.warning(t('chapterGenerate.noShotsToGenerateVideo'));
      return;
    }
    
    // 找出所有已有分镜图片的分镜
    const shotsWithImages: number[] = [];
    parsedData?.shots?.forEach((_: any, index: number) => {
      const shotNum = index + 1;
      const hasImage = shotImages[shotNum] || parsedData?.shots?.[index]?.image_url;
      const isPending = pendingVideos.has(shotNum);
      const isGenerating = generatingVideos.has(shotNum);
      if (hasImage && !isPending && !isGenerating) {
        shotsWithImages.push(shotNum);
      }
    });
    
    if (shotsWithImages.length === 0) {
      toast.warning(t('chapterGenerate.noShotsWithImages'));
      return;
    }
    
    toast.info(t('chapterGenerate.startBatchGenerateVideos', { count: shotsWithImages.length }));
    
    let successCount = 0;
    let skipCount = 0;
    let failCount = 0;
    
    for (let i = 0; i < shotsWithImages.length; i++) {
      const shotIndex = shotsWithImages[i];
      
      try {
        setGeneratingVideos(prev => new Set(prev).add(shotIndex));
        
        const res = await fetch(
          `${API_BASE}/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/generate-video/`,
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
      
      if (i < shotsWithImages.length - 1) {
        await new Promise(resolve => setTimeout(resolve, 200));
      }
    }
    
    if (successCount > 0) {
      toast.success(t('chapterGenerate.videoTasksSubmitted', { count: successCount }));
    }
    if (skipCount > 0) {
      toast.info(t('chapterGenerate.videosAlreadyInQueue', { count: skipCount }));
    }
    if (failCount > 0) {
      toast.error(t('chapterGenerate.videosSubmitFailed', { count: failCount }));
    }
  }, [pendingVideos, generatingVideos, t]);

  // 检查视频任务状态
  const checkVideoTaskStatus = useCallback(async (
    chapterId: string | undefined,
    onRefresh: () => void
  ) => {
    if (pendingVideos.size === 0 || !chapterId) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=shot_video&limit=50`);
      const data = await res.json();
      
      if (data.success) {
        const chapterTasks = data.data.filter((task: any) => task.chapterId === chapterId);
        
        console.log('[ChapterGenerate] Checking video tasks:', chapterTasks.length, 'pending:', pendingVideos.size);
        
        let hasCompleted = false;
        const stillPending = new Set<number>();
        
        chapterTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)/);
          if (!match) return;
          const shotNum = parseInt(match[1]);
          
          console.log('[ChapterGenerate] Video task:', task.name, 'status:', task.status, 'shotNum:', shotNum);
          
          if (task.status === 'completed') {
            if (task.resultUrl) {
              console.log('[ChapterGenerate] Video completed, setting URL for shot', shotNum);
              setShotVideos(prev => ({ ...prev, [shotNum]: task.resultUrl }));
              hasCompleted = true;
            }
          } else if (task.status === 'pending' || task.status === 'running') {
            stillPending.add(shotNum);
          } else if (task.status === 'failed') {
            hasCompleted = true;
          }
        });
        
        console.log('[ChapterGenerate] Video check result - hasCompleted:', hasCompleted, 'stillPending:', [...stillPending]);
        
        if (hasCompleted || stillPending.size !== pendingVideos.size) {
          setPendingVideos(stillPending);
        }
        
        if (hasCompleted) {
          console.log('[ChapterGenerate] Fetching chapter data after video completion');
          onRefresh();
        }
      }
    } catch (error) {
      console.error('检查任务状态失败:', error);
    }
  }, [pendingVideos.size]);

  // 获取视频任务状态
  const fetchVideoTasks = useCallback(async (chapterId: string | undefined) => {
    if (!chapterId) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=shot_video&limit=50`);
      const data = await res.json();
      if (data.success) {
        const activeTasks = data.data.filter((task: any) => 
          task.chapterId === chapterId && 
          (task.status === 'pending' || task.status === 'running')
        );
        
        const pendingVideoIndices = new Set<number>();
        activeTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)/);
          if (match) {
            pendingVideoIndices.add(parseInt(match[1]));
          }
        });
        
        console.log('[ChapterGenerate] fetchVideoTasks found active:', [...pendingVideoIndices]);
        
        if (pendingVideoIndices.size > 0) {
          setPendingVideos(pendingVideoIndices);
        }
      }
    } catch (error) {
      console.error('获取视频任务状态失败:', error);
    }
  }, []);

  return {
    generatingVideos,
    pendingVideos,
    shotVideos,
    handleGenerateShotVideo,
    handleGenerateAllVideos,
    setShotVideos,
    setPendingVideos,
    checkVideoTaskStatus,
    fetchVideoTasks,
  };
}
