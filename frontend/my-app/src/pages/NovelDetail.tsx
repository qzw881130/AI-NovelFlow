import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { 
  ArrowLeft, 
  Plus, 
  Loader2, 
  FileText,
  Play,
  Trash2,
  Edit3,
  Sparkles,
  CheckCircle,
  AlertCircle,
  Clock,
  Wand2
} from 'lucide-react';
import type { Novel, Chapter } from '../types';
import { toast } from '../stores/toastStore';
import { useTranslation } from '../stores/i18nStore';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function NovelDetail() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newChapter, setNewChapter] = useState({ title: '', content: '', number: 1 });

  useEffect(() => {
    if (id) {
      fetchData();
    }
  }, [id]);

  const fetchData = async () => {
    setIsLoading(true);
    try {
      // 获取小说
      const novelRes = await fetch(`${API_BASE}/novels/${id}/`);
      const novelData = await novelRes.json();
      if (novelData.success) {
        setNovel(novelData.data);
      }

      // 获取章节
      const chaptersRes = await fetch(`${API_BASE}/novels/${id}/chapters/`);
      const chaptersData = await chaptersRes.json();
      if (chaptersData.success) {
        setChapters(chaptersData.data);
        // 设置新章节的序号
        setNewChapter(prev => ({ ...prev, number: chaptersData.data.length + 1 }));
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
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newChapter),
      });
      const data = await res.json();
      if (data.success) {
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
      await fetch(`${API_BASE}/novels/${id}/chapters/${chapterId}/`, {
        method: 'DELETE',
      });
      setChapters(chapters.filter(c => c.id !== chapterId));
    } catch (error) {
      console.error('删除失败:', error);
      toast.error(t('common.deleteFailed'));
    }
  };

  const getStatusIcon = (status: Chapter['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'failed':
        return <AlertCircle className="h-5 w-5 text-red-600" />;
      case 'pending':
        return <Clock className="h-5 w-5 text-gray-400" />;
      default:
        return <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />;
    }
  };

  const getStatusText = (status: Chapter['status']) => {
    return t(`chapterStatus.${status}`, { defaultValue: status });
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    );
  }

  if (!novel) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">{t('novelDetail.novelNotFound')}</p>
        <Link to="/novels" className="text-primary-600 hover:underline mt-2 inline-block">
          {t('novelDetail.backToNovels')}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link 
            to="/novels"
            className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{novel.title}</h1>
            <p className="text-sm text-gray-500">{novel.author} · {chapters.length} {t('novelDetail.chapters')}</p>
          </div>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="btn-primary"
        >
          <Plus className="h-4 w-4 mr-2" />
          {t('novelDetail.addChapter')}
        </button>
      </div>

      {/* Description */}
      {novel.description && (
        <div className="card bg-gray-50">
          <p className="text-gray-600">{novel.description}</p>
        </div>
      )}

      {/* Chapters List */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('novelDetail.chapterCount', { count: chapters.length })}</h2>
        
        {chapters.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">{t('novelDetail.noChapters')}</h3>
            <p className="mt-1 text-sm text-gray-500">{t('novelDetail.clickAddChapter')}</p>
          </div>
        ) : (
          <div className="space-y-2">
            {chapters.map((chapter, index) => (
              <div
                key={chapter.id}
                className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <span className="text-sm font-medium text-gray-400 w-8">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  {getStatusIcon(chapter.status)}
                  <div>
                    <h3 className="font-medium text-gray-900">{chapter.title}</h3>
                    <p className="text-xs text-gray-500">
                      {getStatusText(chapter.status)}
                      {chapter.progress > 0 && ` · ${chapter.progress}%`}
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleDeleteChapter(chapter.id)}
                    className="p-2 text-gray-400 hover:text-red-600 transition-colors"
                    title={t('common.actions')}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                  <Link
                    to={`/novels/${id}/chapters/${chapter.id}`}
                    className="btn-primary text-sm py-1.5 px-3"
                  >
                    <Edit3 className="h-3 w-3 mr-1" />
                    {t('common.edit')}
                  </Link>
                  <Link
                    to={`/novels/${id}/chapters/${chapter.id}/generate`}
                    className="btn-secondary text-sm py-1.5 px-3 bg-purple-50 text-purple-600 hover:bg-purple-100 border-purple-200"
                  >
                    <Wand2 className="h-3 w-3 mr-1" />
                    {t('common.generate')}
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('novelDetail.addChapter')}</h2>
            <form onSubmit={handleCreateChapter} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novelDetail.chapterNumber')}
                </label>
                <input
                  type="number"
                  min={1}
                  value={newChapter.number}
                  onChange={(e) => setNewChapter({ ...newChapter, number: parseInt(e.target.value) })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novelDetail.chapterName')}
                </label>
                <input
                  type="text"
                  required
                  value={newChapter.title}
                  onChange={(e) => setNewChapter({ ...newChapter, title: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('novelDetail.chapterNamePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novelDetail.chapterContent')}
                </label>
                <textarea
                  rows={6}
                  value={newChapter.content}
                  onChange={(e) => setNewChapter({ ...newChapter, content: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('novelDetail.chapterContentPlaceholder')}
                />
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                <button type="submit" className="btn-primary">
                  {t('common.create')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
