import { useState, useCallback } from 'react';
import { API_BASE, DEFAULT_TRANSITION_DURATION, VIDEO_FPS, FRAME_BASE } from '../constants';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import type { ParsedData } from '../types';

interface UseTransitionGenerationReturn {
  // 状态
  transitionVideos: Record<string, string>;
  generatingTransitions: Set<string>;
  currentTransition: string;
  transitionWorkflows: any[];
  selectedTransitionWorkflow: string;
  transitionDuration: number;
  // 方法
  handleGenerateTransition: (fromIndex: number, toIndex: number, useCustomConfig: boolean, novelId: string | undefined, chapterId: string | undefined) => Promise<void>;
  handleGenerateAllTransitions: (parsedData: ParsedData | null, novelId: string | undefined, chapterId: string | undefined) => Promise<void>;
  setTransitionVideos: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setGeneratingTransitions: React.Dispatch<React.SetStateAction<Set<string>>>;
  setCurrentTransition: React.Dispatch<React.SetStateAction<string>>;
  setSelectedTransitionWorkflow: React.Dispatch<React.SetStateAction<string>>;
  setTransitionDuration: React.Dispatch<React.SetStateAction<number>>;
  fetchTransitionWorkflows: () => Promise<void>;
  fetchTransitionTasks: (chapterId: string | undefined) => Promise<void>;
  checkTransitionTaskStatus: (chapterId: string | undefined, onRefresh: () => void) => Promise<void>;
}

export default function useTransitionGeneration(): UseTransitionGenerationReturn {
  const { t } = useTranslation();
  const [transitionVideos, setTransitionVideos] = useState<Record<string, string>>({});
  const [generatingTransitions, setGeneratingTransitions] = useState<Set<string>>(new Set());
  const [currentTransition, setCurrentTransition] = useState<string>("");
  const [transitionWorkflows, setTransitionWorkflows] = useState<any[]>([]);
  const [selectedTransitionWorkflow, setSelectedTransitionWorkflow] = useState<string>("");
  const [transitionDuration, setTransitionDuration] = useState<number>(DEFAULT_TRANSITION_DURATION);

  // 获取转场工作流列表
  const fetchTransitionWorkflows = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/workflows/?type=transition`);
      const data = await res.json();
      if (data.success) {
        setTransitionWorkflows(data.data || []);
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
  }, []);

  // 生成单个转场视频
  const handleGenerateTransition = useCallback(async (
    fromIndex: number,
    toIndex: number,
    useCustomConfig: boolean,
    novelId: string | undefined,
    chapterId: string | undefined
  ) => {
    if (!novelId || !chapterId) return;
    
    const transitionKey = `${fromIndex}-${toIndex}`;
    setGeneratingTransitions(prev => new Set(prev).add(transitionKey));
    
    try {
      const body: any = { 
        from_index: fromIndex, 
        to_index: toIndex
      };
      
      if (useCustomConfig) {
        if (selectedTransitionWorkflow) {
          body.workflow_id = selectedTransitionWorkflow;
        }
        const frameCount = Math.max(9, Math.round(transitionDuration * VIDEO_FPS / FRAME_BASE) * FRAME_BASE + 1);
        body.frame_count = frameCount;
        console.log(`[GenerateTransition] Using custom config: duration=${transitionDuration}s, frames=${frameCount}`);
      }
      
      const res = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/transitions/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        }
      );
      const data = await res.json();
      
      if (data.success) {
        toast.success(t('chapterGenerate.transitionVideoStarted', { from: fromIndex, to: toIndex }));
      } else {
        toast.error(data.message || t('chapterGenerate.generateFailed'));
        setGeneratingTransitions(prev => {
          const next = new Set(prev);
          next.delete(transitionKey);
          return next;
        });
      }
    } catch (error) {
      console.error('生成转场视频失败:', error);
      toast.error(t('chapterGenerate.generateFailed'));
      setGeneratingTransitions(prev => {
        const next = new Set(prev);
        next.delete(transitionKey);
        return next;
      });
    }
  }, [selectedTransitionWorkflow, transitionDuration, t]);

  // 一键生成所有转场视频
  const handleGenerateAllTransitions = useCallback(async (
    parsedData: ParsedData | null,
    novelId: string | undefined,
    chapterId: string | undefined
  ) => {
    if (!parsedData?.shots || parsedData.shots.length < 2 || !novelId || !chapterId) {
      toast.warning(t('chapterGenerate.notEnoughShots'));
      return;
    }
    
    try {
      const body: any = {};
      
      if (selectedTransitionWorkflow) {
        body.workflow_id = selectedTransitionWorkflow;
      }
      const frameCount = Math.max(9, Math.round(transitionDuration * VIDEO_FPS / FRAME_BASE) * FRAME_BASE + 1);
      body.frame_count = frameCount;
      console.log(`[GenerateAllTransitions] Using config: duration=${transitionDuration}s, frames=${frameCount}, workflow=${selectedTransitionWorkflow || 'default'}`);
      
      const res = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/transitions/batch/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        }
      );
      const data = await res.json();
      
      if (data.success) {
        toast.success(t('chapterGenerate.transitionTasksCreated', { count: data.task_count }));
        const allTransitions = new Set<string>();
        for (let i = 1; i < parsedData.shots.length; i++) {
          allTransitions.add(`${i}-${i + 1}`);
        }
        setGeneratingTransitions(allTransitions);
      } else {
        toast.error(data.message || t('chapterGenerate.generateFailed'));
      }
    } catch (error) {
      console.error('批量生成转场视频失败:', error);
      toast.error(t('chapterGenerate.generateFailed'));
    }
  }, [selectedTransitionWorkflow, transitionDuration, t]);

  // 获取转场视频任务状态
  const fetchTransitionTasks = useCallback(async (chapterId: string | undefined) => {
    if (!chapterId) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=transition_video&limit=50`);
      const data = await res.json();
      if (data.success) {
        const activeTasks = data.data.filter((task: any) => 
          task.chapterId === chapterId && 
          (task.status === 'pending' || task.status === 'running')
        );
        
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
  }, []);

  // 检查转场视频任务状态
  const checkTransitionTaskStatus = useCallback(async (
    chapterId: string | undefined,
    onRefresh: () => void
  ) => {
    if (generatingTransitions.size === 0 || !chapterId) return;
    
    try {
      const res = await fetch(`${API_BASE}/tasks/?type=transition_video&limit=50`);
      const data = await res.json();
      
      if (data.success) {
        const chapterTasks = data.data.filter((task: any) => task.chapterId === chapterId);
        
        console.log('[ChapterGenerate] Checking transition tasks:', chapterTasks.length, 'generating:', generatingTransitions.size);
        
        let hasCompleted = false;
        const stillGenerating = new Set<string>();
        
        chapterTasks.forEach((task: any) => {
          const match = task.name.match(/镜(\d+)→镜(\d+)/);
          if (!match) return;
          const transitionKey = `${match[1]}-${match[2]}`;
          
          console.log('[ChapterGenerate] Transition task:', task.name, 'status:', task.status, 'key:', transitionKey);
          
          if (task.status === 'completed') {
            if (task.resultUrl) {
              console.log('[ChapterGenerate] Transition completed, setting URL for', transitionKey);
              setTransitionVideos(prev => ({ ...prev, [transitionKey]: task.resultUrl }));
              hasCompleted = true;
            }
          } else if (task.status === 'pending' || task.status === 'running') {
            stillGenerating.add(transitionKey);
          } else if (task.status === 'failed') {
            hasCompleted = true;
          }
        });
        
        console.log('[ChapterGenerate] Transition check result - hasCompleted:', hasCompleted, 'stillGenerating:', [...stillGenerating]);
        
        if (hasCompleted || stillGenerating.size !== generatingTransitions.size) {
          setGeneratingTransitions(stillGenerating);
        }
        
        if (hasCompleted) {
          console.log('[ChapterGenerate] Fetching chapter data after transition completion');
          onRefresh();
        }
      }
    } catch (error) {
      console.error('检查任务状态失败:', error);
    }
  }, [generatingTransitions.size]);

  return {
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
  };
}
