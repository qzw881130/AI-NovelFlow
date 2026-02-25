import { useState, useCallback, useRef } from 'react';
import { API_BASE } from '../constants';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import type { ParsedData } from '../types';

interface UseShotGenerationReturn {
  // 状态
  generatingShots: Set<number>;
  pendingShots: Set<number>;
  shotImages: Record<number, string>;
  isGeneratingAll: boolean;
  uploadingShotIndex: number | null;
  // 方法
  handleGenerateShotImage: (shotIndex: number, novelId: string | undefined, chapterId: string | undefined) => Promise<void>;
  handleGenerateAllShots: (parsedData: ParsedData | null, novelId: string | undefined, chapterId: string | undefined) => Promise<void>;
  triggerShotFileUpload: (shotIndex: number) => void;
  handleUploadShotImage: (event: React.ChangeEvent<HTMLInputElement>, novelId: string | undefined, chapterId: string | undefined, currentShot: number) => Promise<void>;
  setShotImages: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  setPendingShots: React.Dispatch<React.SetStateAction<Set<number>>>;
  checkShotTaskStatus: (chapterId: string | undefined, onRefresh: () => void) => Promise<void>;
  fetchShotTasks: (chapterId: string | undefined) => Promise<void>;
  shotFileInputRef: React.RefObject<HTMLInputElement>;
}

export default function useShotGeneration(): UseShotGenerationReturn {
  const { t } = useTranslation();
  const [generatingShots, setGeneratingShots] = useState<Set<number>>(new Set());
  const [pendingShots, setPendingShots] = useState<Set<number>>(new Set());
  const [shotImages, setShotImages] = useState<Record<number, string>>({});
  const [isGeneratingAll, setIsGeneratingAll] = useState(false);
  const [uploadingShotIndex, setUploadingShotIndex] = useState<number | null>(null);
  const shotFileInputRef = useRef<HTMLInputElement>(null);

  // 生成分镜图片
  const handleGenerateShotImage = useCallback(async (
    shotIndex: number,
    novelId: string | undefined,
    chapterId: string | undefined
  ) => {
    if (!novelId || !chapterId) return;
    
    setGeneratingShots(prev => new Set(prev).add(shotIndex));
    
    // 立即清除本地状态中的旧图，避免显示旧图
    setShotImages(prev => {
      const next = { ...prev };
      delete next[shotIndex];
      return next;
    });
    
    try {
      const res = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/generate/`,
        { method: 'POST' }
      );
      const data = await res.json();
      
      if (data.success) {
        setPendingShots(prev => new Set(prev).add(shotIndex));
        toast.success(data.message || t('chapterGenerate.shotImageTaskCreated'));
      } else if (data.message?.includes('已有进行中的生成任务')) {
        toast.info(data.message);
      } else {
        toast.error(data.message || t('chapterGenerate.generateFailed'));
      }
    } catch (error) {
      console.error('生成分镜图片失败:', error);
      toast.error(t('chapterGenerate.generateFailedCheckNetwork'));
    } finally {
      setGeneratingShots(prev => {
        const next = new Set(prev);
        next.delete(shotIndex);
        return next;
      });
    }
  }, [t]);

  // 批量生成所有分镜图片
  const handleGenerateAllShots = useCallback(async (
    parsedData: ParsedData | null,
    novelId: string | undefined,
    chapterId: string | undefined
  ) => {
    if (!parsedData?.shots || parsedData.shots.length === 0 || !novelId || !chapterId) {
      toast.warning(t('chapterGenerate.noShotsToGenerate'));
      return;
    }
    
    const totalShots = parsedData.shots.length;
    
    if (pendingShots.size > 0) {
      toast.info(t('chapterGenerate.pendingShotsInQueue', { count: pendingShots.size }));
      return;
    }
    
    setIsGeneratingAll(true);
    toast.info(t('chapterGenerate.startBatchGenerateShots', { count: totalShots }));
    
    let successCount = 0;
    let skipCount = 0;
    let failCount = 0;
    
    for (let i = 0; i < totalShots; i++) {
      const shotIndex = i + 1;
      
      try {
        setGeneratingShots(prev => new Set(prev).add(shotIndex));
        
        const res = await fetch(
          `${API_BASE}/novels/${novelId}/chapters/${chapterId}/shots/${shotIndex}/generate/`,
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
      
      if (i < totalShots - 1) {
        await new Promise(resolve => setTimeout(resolve, 200));
      }
    }
    
    setIsGeneratingAll(false);
    
    if (successCount > 0) {
      toast.success(t('chapterGenerate.shotTasksSubmitted', { count: successCount }));
    }
    if (skipCount > 0) {
      toast.info(t('chapterGenerate.shotsAlreadyInQueue', { count: skipCount }));
    }
    if (failCount > 0) {
      toast.error(t('chapterGenerate.shotsSubmitFailed', { count: failCount }));
    }
  }, [pendingShots.size, t]);

  // 触发分镜图文件选择
  const triggerShotFileUpload = useCallback((shotIndex: number) => {
    if (shotFileInputRef.current) {
      shotFileInputRef.current.click();
    }
  }, []);

  // 上传分镜图片
  const handleUploadShotImage = useCallback(async (
    event: React.ChangeEvent<HTMLInputElement>,
    novelId: string | undefined,
    chapterId: string | undefined,
    currentShot: number
  ) => {
    const file = event.target.files?.[0];
    if (!file || !novelId || !chapterId) return;
    
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'];
    if (!allowedTypes.includes(file.type)) {
      toast.error(t('common.error') + ': 仅支持 PNG, JPG, WEBP 格式');
      return;
    }
    
    setUploadingShotIndex(currentShot);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const res = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/shots/${currentShot}/upload-image`,
        {
          method: 'POST',
          body: formData
        }
      );
      
      const data = await res.json();
      
      if (data.success) {
        setShotImages(prev => ({
          ...prev,
          [currentShot]: data.data.imageUrl
        }));
        toast.success(t('chapterGenerate.uploadSuccess'));
      } else {
        toast.error(data.message || t('chapterGenerate.uploadFailed'));
      }
    } catch (error) {
      console.error('上传分镜图片失败:', error);
      toast.error(t('chapterGenerate.uploadFailed'));
    } finally {
      setUploadingShotIndex(null);
      if (shotFileInputRef.current) {
        shotFileInputRef.current.value = '';
      }
    }
  }, [t]);

  // 检查分镜任务状态
  const checkShotTaskStatus = useCallback(async (
    chapterId: string | undefined,
    onRefresh: () => void
  ) => {
    if (pendingShots.size === 0 || !chapterId) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=shot_image&limit=50`);
      const data = await res.json();
      
      if (data.success) {
        const chapterTasks = data.data.filter((task: any) => task.chapterId === chapterId);
        
        let hasCompleted = false;
        const stillPending = new Set<number>();
        
        chapterTasks.forEach((task: any) => {
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
        
        if (hasCompleted) {
          onRefresh();
        }
      }
    } catch (error) {
      console.error('检查任务状态失败:', error);
    }
  }, [pendingShots.size]);

  // 获取分镜任务状态
  const fetchShotTasks = useCallback(async (chapterId: string | undefined) => {
    if (!chapterId) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=shot_image&limit=50`);
      const data = await res.json();
      if (data.success) {
        const activeTasks = data.data.filter((task: any) => 
          task.chapterId === chapterId && 
          (task.status === 'pending' || task.status === 'running')
        );
        
        const pendingShotIndices = new Set<number>();
        activeTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)/);
          if (match) {
            pendingShotIndices.add(parseInt(match[1]));
          }
        });
        
        if (pendingShotIndices.size > 0) {
          setPendingShots(pendingShotIndices);
        }
      }
    } catch (error) {
      console.error('获取分镜任务状态失败:', error);
    }
  }, []);

  return {
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
  };
}
