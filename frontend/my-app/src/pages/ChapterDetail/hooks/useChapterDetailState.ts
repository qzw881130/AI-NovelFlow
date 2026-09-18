import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import { novelApi } from '../../../api/novels';
import { chapterApi } from '../../../api/chapters';
import type { Chapter, Novel } from '../../../types';
import type { PreviewImageState } from '../types';

export function useChapterDetailState() {
  const { t } = useTranslation();
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const navigate = useNavigate();
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [content, setContent] = useState('');
  const [title, setTitle] = useState('');
  const [previewImage, setPreviewImage] = useState<PreviewImageState>({ isOpen: false, url: null, index: 0, images: [] });

  useEffect(() => { if (id && cid) fetchData(); }, [id, cid]);
  const fetchData = async () => {
    setIsLoading(true);
    try {
      const novelData = await novelApi.fetch(id!);
      if (novelData.success && novelData.data) setNovel(novelData.data);
      const chapterData = await chapterApi.fetch(id!, cid!);
      if (chapterData.success && chapterData.data) {
        setChapter(chapterData.data);
        setTitle(chapterData.data.title);
        setContent(chapterData.data.content || '');
      }
    } catch (error) {
      console.error('获取数据失败:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const data = await chapterApi.update(id!, cid!, { title, content });
      if (data.success && data.data) { setChapter(data.data); toast.success(t('common.saveSuccess')); }
    } catch (error) {
      console.error('保存失败:', error);
      toast.error(t('common.saveFailed'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(t('chapterDetail.confirmDelete'))) return;
    try {
      await chapterApi.delete(id!, cid!);
      navigate(`/novels/${id}`);
    } catch (error) {
      console.error('删除失败:', error);
      toast.error(t('chapterDetail.deleteFailed'));
    }
  };

  const handleGenerate = () => {
    if (!content.trim()) { toast.warning(t('chapterDetail.pleaseEditContent')); return; }
    navigate(`/novels/${id}/chapters/${cid}/generate`);
  };

  const openImagePreview = useCallback((url: string, index: number, images: string[]) => {
    setPreviewImage({ isOpen: true, url, index, images });
  }, []);
  const closeImagePreview = useCallback(() => {
    setPreviewImage({ isOpen: false, url: null, index: 0, images: [] });
  }, []);
  const navigatePreview = useCallback((direction: 'prev' | 'next') => {
    if (!previewImage.images.length) return;
    const newIndex = direction === 'prev'
      ? (previewImage.index === 0 ? previewImage.images.length - 1 : previewImage.index - 1)
      : (previewImage.index === previewImage.images.length - 1 ? 0 : previewImage.index + 1);
    setPreviewImage({ ...previewImage, url: previewImage.images[newIndex], index: newIndex });
  }, [previewImage]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!previewImage.isOpen) return;
      if (event.key === 'ArrowLeft') { event.preventDefault(); navigatePreview('prev'); }
      else if (event.key === 'ArrowRight') { event.preventDefault(); navigatePreview('next'); }
      else if (event.key === 'Escape') { event.preventDefault(); closeImagePreview(); }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewImage.isOpen, previewImage.index, previewImage.images, navigatePreview, closeImagePreview]);

  return {
    id, cid, chapter, novel, isLoading, isSaving, content, setContent, title, setTitle, previewImage,
    handleSave, handleDelete, handleGenerate, openImagePreview, closeImagePreview, navigatePreview,
  };
}
