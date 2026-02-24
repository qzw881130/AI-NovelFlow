import { useState, useEffect } from 'react';
import { 
  Plus, 
  Search, 
  Upload, 
  MoreVertical,
  Trash2,
  Play,
  BookOpen,
  Loader2,
  Users,
  Sparkles,
  Edit2,
  MapPin
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useNovelStore } from '../stores/novelStore';
import { useTranslation } from '../stores/i18nStore';
import type { Novel } from '../types';
import { toast } from '../stores/toastStore';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  isSystem: boolean;
  type: string;
}

export default function Novels() {
  const { t } = useTranslation();
  const { novels, isLoading, fetchNovels, createNovel, deleteNovel, importNovel, updateNovel } = useNovelStore();
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newNovel, setNewNovel] = useState({ 
    title: '', 
    author: '', 
    description: '', 
    promptTemplateId: '',
    chapterSplitPromptTemplateId: '',
    aspectRatio: '16:9'
  });
  
  // 画面比例选项
  const aspectRatioOptions = [
    { value: '16:9', label: `16:9 (${t('novels.aspectRatio.widescreen')})`, description: t('novels.aspectRatio.widescreenDesc') },
    { value: '9:16', label: `9:16 (${t('novels.aspectRatio.vertical')})`, description: t('novels.aspectRatio.verticalDesc') },
    { value: '4:3', label: `4:3 (${t('novels.aspectRatio.standard')})`, description: t('novels.aspectRatio.standardDesc') },
    { value: '3:4', label: `3:4 (${t('novels.aspectRatio.portrait')})`, description: t('novels.aspectRatio.portraitDesc') },
    { value: '1:1', label: `1:1 (${t('novels.aspectRatio.square')})`, description: t('novels.aspectRatio.squareDesc') },
    { value: '21:9', label: `21:9 (${t('novels.aspectRatio.ultrawide')})`, description: t('novels.aspectRatio.ultrawideDesc') },
    { value: '2.35:1', label: `2.35:1 (${t('novels.aspectRatio.cinema')})`, description: t('novels.aspectRatio.cinemaDesc') },
  ];
  const [importing, setImporting] = useState(false);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  const [editingNovel, setEditingNovel] = useState<Novel | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    novelId: string | null;
    type: 'characters' | 'scenes';  // 区分角色解析和场景解析
  }>({ isOpen: false, novelId: null, type: 'characters' });
  
  // 章节范围解析状态
  const [chapterRange, setChapterRange] = useState<{
    startChapter: number | null;
    endChapter: number | null;
    isIncremental: boolean;
  }>({
    startChapter: null,
    endChapter: null,
    isIncremental: true
  });
  
  // 场景解析状态
  const [parsingScenesNovelId, setParsingScenesNovelId] = useState<string | null>(null);
  
  // 提示词模板
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [chapterSplitTemplates, setChapterSplitTemplates] = useState<PromptTemplate[]>([]);

  useEffect(() => {
    fetchNovels();
    fetchPromptTemplates();
  }, []);

  const fetchPromptTemplates = async () => {
    try {
      // 获取人设提示词模板
      const res1 = await fetch(`${API_BASE}/prompt-templates/?type=character`);
      const data1 = await res1.json();
      if (data1.success) {
        setPromptTemplates(data1.data);
      }
      // 获取章节拆分提示词模板
      const res2 = await fetch(`${API_BASE}/prompt-templates/?type=chapter_split`);
      const data2 = await res2.json();
      if (data2.success) {
        setChapterSplitTemplates(data2.data);
      }
    } catch (error) {
      console.error('加载提示词模板失败:', error);
    }
  };

  // 获取翻译后的模板名称（系统预设模板会翻译，自定义模板保持原样）
  const getTemplateDisplayName = (template: PromptTemplate | undefined): string => {
    if (!template) return t('novels.default');
    if (template.isSystem) {
      return t(`promptConfig.templateNames.${template.name}`, { defaultValue: template.name });
    }
    return template.name;
  };

  const filteredNovels = novels.filter(
    (novel) =>
      novel.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      novel.author.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    await createNovel(newNovel);
    setShowCreateModal(false);
    setNewNovel({ title: '', author: '', description: '', promptTemplateId: '', chapterSplitPromptTemplateId: '', aspectRatio: '16:9' });
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setImporting(true);
    await importNovel(file);
    setImporting(false);
  };

  const openParseConfirm = (novelId: string, type: 'characters' | 'scenes' = 'characters') => {
    setConfirmDialog({ isOpen: true, novelId, type });
  };

  const closeParseConfirm = () => {
    setConfirmDialog({ isOpen: false, novelId: null, type: 'characters' });
  };

  const confirmParseCharacters = async () => {
    const novelId = confirmDialog.novelId;
    if (!novelId) return;
    
    closeParseConfirm();
    setParsingNovelId(novelId);
    
    try {
      // 构建查询参数
      const params = new URLSearchParams();
      params.append('sync', 'true');
      
      if (chapterRange.startChapter !== null) {
        params.append('start_chapter', chapterRange.startChapter.toString());
      }
      if (chapterRange.endChapter !== null) {
        params.append('end_chapter', chapterRange.endChapter.toString());
      }
      params.append('is_incremental', chapterRange.isIncremental.toString());
      
      const res = await fetch(`${API_BASE}/novels/${novelId}/parse-characters/?${params.toString()}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        const chars = data.data || [];
        const stats = data.statistics || {};
        
        let message = '';
        if (stats.created > 0) {
          message += t('novels.parseResult', { created: stats.created, updated: stats.updated });
        }
        
        if (message) {
          toast.success(message);
        } else {
          toast.warning(t('novels.noNewCharacters'));
        }
        
        // 重置章节范围
        setChapterRange({
          startChapter: null,
          endChapter: null,
          isIncremental: true
        });
        
        window.location.href = `/characters?novel=${novelId}`;
      } else {
        toast.error(t('novels.parseError') + ': ' + data.message);
      }
    } catch (error) {
      console.error(t('novels.parseFailed') + ':', error);
      toast.error(t('novels.parseNetworkError'));
    } finally {
      setParsingNovelId(null);
    }
  };

  // 场景解析
  const confirmParseScenes = async () => {
    const novelId = confirmDialog.novelId;
    if (!novelId) return;
    
    closeParseConfirm();
    setParsingScenesNovelId(novelId);
    
    try {
      const res = await fetch(`${API_BASE}/scenes/parse-scenes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          novel_id: novelId,
          chapter_ids: [],
          mode: chapterRange.isIncremental ? 'incremental' : 'full'
        }),
      });
      const data = await res.json();
      if (data.success) {
        const stats = data.statistics || {};
        
        let message = '';
        if (stats.created > 0 || stats.updated > 0) {
          message = t('novels.parseScenesResult', { created: stats.created || 0, updated: stats.updated || 0 });
        }
        
        if (message) {
          toast.success(message);
        } else {
          toast.info(t('novels.noNewScenes'));
        }
        
        // 重置章节范围
        setChapterRange({
          startChapter: null,
          endChapter: null,
          isIncremental: true
        });
        
        window.location.href = `/scenes?novel=${novelId}`;
      } else {
        toast.error(t('novels.parseError') + ': ' + data.message);
      }
    } catch (error) {
      console.error(t('novels.parseFailed') + ':', error);
      toast.error(t('novels.parseNetworkError'));
    } finally {
      setParsingScenesNovelId(null);
    }
  };

  const getStatusColor = (status: Novel['status']) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'processing':
        return 'bg-yellow-100 text-yellow-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusText = (status: Novel['status']) => {
    switch (status) {
      case 'completed':
        return t('novels.statusCompleted');
      case 'processing':
        return t('novels.statusProcessing');
      default:
        return t('novels.statusPending');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('novels.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {t('novels.subtitle')}
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowCreateModal(true)}
            className="btn-primary"
          >
            <Plus className="mr-2 h-4 w-4" />
            {t('novels.createNovel')}
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder={t('novels.searchPlaceholder')}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="input-field pl-10"
        />
      </div>

      {/* Novels Grid */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
        </div>
      ) : filteredNovels.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <BookOpen className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">{t('novels.noNovelsTitle')}</h3>
          <p className="mt-1 text-sm text-gray-500">
            {t('novels.noNovelsSubtitle')}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredNovels.map((novel) => (
            <div
              key={novel.id}
              className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden hover:shadow-md transition-shadow group"
            >
              <div className="aspect-video bg-gray-100 relative">
                {novel.cover ? (
                  <img
                    src={novel.cover}
                    alt={novel.title}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <BookOpen className="h-16 w-16 text-gray-300" />
                  </div>
                )}
                {/* 章节数目 - 左上角 */}
                <div className="absolute top-2 left-2 px-2 py-1 bg-black/60 text-white text-xs rounded-lg flex items-center gap-1">
                  <BookOpen className="h-3 w-3" />
                  <span>{novel.chapterCount} {t('novelDetail.chapters')}</span>
                </div>
                {/* 删除按钮 - 右上角 */}
                <button
                  onClick={() => deleteNovel(novel.id)}
                  className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
                  title={t('common.delete')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                {/* 编辑按钮 - 右下角 */}
                <button
                  onClick={() => setEditingNovel(novel)}
                  className="absolute bottom-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
                  title={t('common.edit')}
                >
                  <Edit2 className="h-4 w-4" />
                </button>
              </div>
              <div className="p-4">
                <h3 className="text-lg font-semibold text-gray-900 truncate">
                  {novel.title}
                </h3>
                <p className="text-sm text-gray-500 mt-1">{novel.author}</p>
                <p className="text-sm text-gray-600 mt-2 line-clamp-2 h-10">
                  {novel.description || t('novels.noDescription')}
                </p>
                {/* 小说配置信息 */}
                <div className="mt-3 flex flex-wrap gap-1.5 h-16 content-start">
                  {/* 人设提示词 */}
                  <span className="inline-flex items-center gap-1 px-2 py-1 bg-blue-50 text-blue-600 text-xs rounded whitespace-nowrap">
                    <span className="font-medium">{t('novels.characterPrompt')}</span>
                    <span className="truncate max-w-[80px]">{getTemplateDisplayName(promptTemplates.find(t => t.id === novel.promptTemplateId))}</span>
                  </span>
                  {/* AI拆分分镜提示词 */}
                  <span className="inline-flex items-center gap-1 px-2 py-1 bg-purple-50 text-purple-600 text-xs rounded whitespace-nowrap">
                    <span className="font-medium">{t('novels.splitPrompt')}</span>
                    <span className="truncate max-w-[80px]">{getTemplateDisplayName(chapterSplitTemplates.find(t => t.id === novel.chapterSplitPromptTemplateId))}</span>
                  </span>
                  {/* 画面比例 */}
                  <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-50 text-green-600 text-xs rounded whitespace-nowrap">
                    <span className="font-medium">{t('novels.aspectRatioShort')}</span>
                    {novel.aspectRatio || '16:9'}
                  </span>
                </div>
                <div className="flex flex-col sm:flex-row sm:items-center justify-end mt-4 pt-4 border-t border-gray-100 gap-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      onClick={() => openParseConfirm(novel.id, 'characters')}
                      disabled={parsingNovelId === novel.id}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-purple-100 text-purple-600 hover:bg-purple-200 transition-colors disabled:opacity-50 text-sm"
                      title={t('novels.aiParseCharacters')}
                    >
                      {parsingNovelId === novel.id ? (
                        <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" />
                      ) : (
                        <Sparkles className="h-4 w-4 flex-shrink-0" />
                      )}
                      <span>{t('novels.aiParseCharacters')}</span>
                    </button>
                    <button
                      onClick={() => openParseConfirm(novel.id, 'scenes')}
                      disabled={parsingScenesNovelId === novel.id}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-teal-100 text-teal-600 hover:bg-teal-200 transition-colors disabled:opacity-50 text-sm"
                      title={t('novels.aiParseScenes')}
                    >
                      {parsingScenesNovelId === novel.id ? (
                        <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" />
                      ) : (
                        <Sparkles className="h-4 w-4 flex-shrink-0" />
                      )}
                      <span>{t('novels.aiParseScenes')}</span>
                    </button>
                    <Link
                      to={`/characters?novel=${novel.id}`}
                      className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition-colors flex-shrink-0"
                      title={t('novels.viewCharacters')}
                    >
                      <Users className="h-4 w-4" />
                    </Link>
                    <Link
                      to={`/scenes?novel=${novel.id}`}
                      className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition-colors flex-shrink-0"
                      title={t('novels.viewScenes')}
                    >
                      <MapPin className="h-4 w-4" />
                    </Link>
                    <Link
                      to={`/novels/${novel.id}`}
                      className="btn-primary text-sm py-2 px-3 flex-shrink-0"
                    >
                      <Play className="h-3 w-3 mr-1 flex-shrink-0" />
                      {t('novels.manageChapters')}
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('novels.createNovelTitle')}</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.titleLabel')}
                </label>
                <input
                  type="text"
                  required
                  value={newNovel.title}
                  onChange={(e) => setNewNovel({ ...newNovel, title: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.authorLabel')}
                </label>
                <input
                  type="text"
                  value={newNovel.author}
                  onChange={(e) => setNewNovel({ ...newNovel, author: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.descriptionLabel')}
                </label>
                <textarea
                  rows={3}
                  value={newNovel.description}
                  onChange={(e) => setNewNovel({ ...newNovel, description: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.characterPromptLabel')}
                </label>
                <select
                  value={newNovel.promptTemplateId}
                  onChange={(e) => setNewNovel({ ...newNovel, promptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  {promptTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {getTemplateDisplayName(template)} {template.isSystem ? t('novels.systemTemplate') : t('novels.customTemplate')}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  {t('novels.characterPromptHint')}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.splitPromptLabel')}
                </label>
                <select
                  value={newNovel.chapterSplitPromptTemplateId}
                  onChange={(e) => setNewNovel({ ...newNovel, chapterSplitPromptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  {chapterSplitTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {getTemplateDisplayName(template)} {template.isSystem ? t('novels.systemTemplate') : t('novels.customTemplate')}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  {t('novels.splitPromptHint')}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.aspectRatioLabel')}
                </label>
                <select
                  value={newNovel.aspectRatio}
                  onChange={(e) => setNewNovel({ ...newNovel, aspectRatio: e.target.value })}
                  className="input-field mt-1"
                >
                  {aspectRatioOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  {aspectRatioOptions.find(o => o.value === newNovel.aspectRatio)?.description}
                </p>
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

      {/* Edit Modal */}
      {editingNovel && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('novels.editNovel')}</h2>
            <form 
              onSubmit={(e) => {
                e.preventDefault();
                updateNovel(editingNovel.id, {
                  title: editingNovel.title,
                  author: editingNovel.author,
                  description: editingNovel.description,
                  promptTemplateId: editingNovel.promptTemplateId,
                  chapterSplitPromptTemplateId: editingNovel.chapterSplitPromptTemplateId,
                  aspectRatio: editingNovel.aspectRatio,
                });
                setEditingNovel(null);
              }} 
              className="space-y-4"
            >
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.titleLabel')}
                </label>
                <input
                  type="text"
                  required
                  value={editingNovel.title}
                  onChange={(e) => setEditingNovel({ ...editingNovel, title: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.authorLabel')}
                </label>
                <input
                  type="text"
                  value={editingNovel.author}
                  onChange={(e) => setEditingNovel({ ...editingNovel, author: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.descriptionLabel')}
                </label>
                <textarea
                  rows={3}
                  value={editingNovel.description || ''}
                  onChange={(e) => setEditingNovel({ ...editingNovel, description: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.characterPromptLabel')}
                </label>
                <select
                  value={editingNovel.promptTemplateId || ''}
                  onChange={(e) => setEditingNovel({ ...editingNovel, promptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  {promptTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {getTemplateDisplayName(template)} {template.isSystem ? t('novels.systemTemplate') : t('novels.customTemplate')}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  {t('novels.characterPromptHint')}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.splitPromptLabel')}
                </label>
                <select
                  value={editingNovel.chapterSplitPromptTemplateId || ''}
                  onChange={(e) => setEditingNovel({ ...editingNovel, chapterSplitPromptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  {chapterSplitTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {getTemplateDisplayName(template)} {template.isSystem ? t('novels.systemTemplate') : t('novels.customTemplate')}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  {t('novels.splitPromptHint')}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('novels.aspectRatioLabel')}
                </label>
                <select
                  value={editingNovel.aspectRatio || '16:9'}
                  onChange={(e) => setEditingNovel({ ...editingNovel, aspectRatio: e.target.value })}
                  className="input-field mt-1"
                >
                  {aspectRatioOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  {aspectRatioOptions.find(o => o.value === (editingNovel.aspectRatio || '16:9'))?.description}
                </p>
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setEditingNovel(null)}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                <button type="submit" className="btn-primary">
                  {t('common.save')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* AI解析确认对话框 */}
      {confirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className={`p-2 rounded-full ${confirmDialog.type === 'characters' ? 'bg-purple-100' : 'bg-teal-100'}`}>
                <Sparkles className={`h-6 w-6 ${confirmDialog.type === 'characters' ? 'text-purple-600' : 'text-teal-600'}`} />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">
                {confirmDialog.type === 'characters' ? t('novels.aiParseCharactersTitle') : t('novels.aiParseScenesTitle')}
              </h3>
            </div>
            
            <p className="text-gray-600 mb-4">
              {confirmDialog.type === 'characters' ? t('novels.parseConfirmMessage') : t('novels.parseScenesConfirmMessage')}
            </p>
            
            {/* 章节范围选择 */}
            <div className="mb-4 space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('novels.chapterRange')}
                </label>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <input
                      type="number"
                      min="1"
                      placeholder={t('novels.startChapter')}
                      value={chapterRange.startChapter || ''}
                      onChange={(e) => setChapterRange({
                        ...chapterRange,
                        startChapter: e.target.value ? parseInt(e.target.value) : null
                      })}
                      className="input-field w-full text-sm"
                    />
                  </div>
                  <div className="flex items-center text-gray-400">-</div>
                  <div className="flex-1">
                    <input
                      type="number"
                      min="1"
                      placeholder={t('novels.endChapter')}
                      value={chapterRange.endChapter || ''}
                      onChange={(e) => setChapterRange({
                        ...chapterRange,
                        endChapter: e.target.value ? parseInt(e.target.value) : null
                      })}
                      className="input-field w-full text-sm"
                    />
                  </div>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {t('novels.parseEntireNovel')}
                </p>
              </div>
              
              <div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={chapterRange.isIncremental}
                    onChange={(e) => setChapterRange({
                      ...chapterRange,
                      isIncremental: e.target.checked
                    })}
                    className={`rounded focus:ring-0 ${confirmDialog.type === 'characters' ? 'text-purple-600 focus:ring-purple-500' : 'text-teal-600 focus:ring-teal-500'}`}
                  />
                  <span className="text-sm text-gray-700">
                    {t('novels.incrementalUpdate')}
                  </span>
                </label>
                <p className="text-xs text-gray-500 mt-1">
                  {t('novels.incrementalUpdateDesc')}
                </p>
              </div>
            </div>
            
            <p className="text-sm text-gray-500 mb-6">
              {t('novels.parseConfirmHint')}
            </p>
            
            <div className="flex justify-end gap-3">
              <button
                onClick={closeParseConfirm}
                className="px-4 py-2 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={confirmDialog.type === 'characters' ? confirmParseCharacters : confirmParseScenes}
                className={`px-4 py-2 text-white rounded-lg transition-colors flex items-center gap-2 ${confirmDialog.type === 'characters' ? 'bg-purple-600 hover:bg-purple-700' : 'bg-teal-600 hover:bg-teal-700'}`}
              >
                {(confirmDialog.type === 'characters' ? parsingNovelId : parsingScenesNovelId) === confirmDialog.novelId ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('novels.parseInProgress')}
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />
                    {t('common.confirm')}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
