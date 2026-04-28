import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import { novelApi } from '../../../api/novels';
import { chapterApi } from '../../../api/chapters';
import type { Novel, Chapter } from '../../../types';

export function useNovelDetailState() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showBatchImportModal, setShowBatchImportModal] = useState(false);
  const [newChapter, setNewChapter] = useState({ title: '', content: '', number: 1 });

  useEffect(() => { if (id) fetchData(); }, [id]);

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const novelData = await novelApi.fetch(id!);
      if (novelData.success && novelData.data) setNovel(novelData.data);
      const chaptersData = await chapterApi.fetchByNovel(id!);
      if (chaptersData.success && chaptersData.data) {
        setChapters(chaptersData.data);
        setNewChapter(prev => ({ ...prev, number: chaptersData.data!.length + 1 }));
      }
    } catch (error) {
      console.error('获取数据失败:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateChapter = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const data = await chapterApi.create(id!, newChapter);
      if (data.success && data.data) {
        setChapters([...chapters, data.data]);
        setShowCreateModal(false);
        setNewChapter({ title: '', content: '', number: chapters.length + 2 });
      }
    } catch (error) {
      console.error('创建章节失败:', error);
      toast.error(t('common.createFailed'));
    }
  };

  const handleDeleteChapter = async (chapterId: string) => {
    if (!confirm(t('chapterDetail.confirmDelete'))) return;
    try {
      await chapterApi.delete(id!, chapterId);
      setChapters(chapters.filter(c => c.id !== chapterId));
    } catch (error) {
      console.error('删除失败:', error);
      toast.error(t('common.deleteFailed'));
    }
  };

  const handleBatchImportComplete = async () => {
    await fetchData();
  };

  const getStatusIcon = (status: Chapter['status']) => {
    switch (status) {
      case 'completed': return { icon: 'check', color: 'text-green-600' };
      case 'failed': return { icon: 'alert', color: 'text-red-600' };
      case 'pending': return { icon: 'clock', color: 'text-gray-400' };
      default: return { icon: 'loading', color: 'text-blue-600', spin: true };
    }
  };

  const getStatusText = (status: Chapter['status']) => t(`chapterStatus.${status}`, { defaultValue: status });

  return {
    id, novel, chapters, isLoading, showCreateModal, setShowCreateModal, showBatchImportModal, setShowBatchImportModal, newChapter, setNewChapter,
    handleCreateChapter, handleDeleteChapter, handleBatchImportComplete, getStatusIcon, getStatusText
  };
}
