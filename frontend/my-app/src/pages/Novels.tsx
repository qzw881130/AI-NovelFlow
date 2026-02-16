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
  Edit2
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useNovelStore } from '../stores/novelStore';
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
    { value: '16:9', label: '16:9 (宽屏)', description: '适合横版视频' },
    { value: '9:16', label: '9:16 (竖屏)', description: '适合短视频' },
    { value: '4:3', label: '4:3 (标准)', description: '传统比例' },
    { value: '3:4', label: '3:4 (竖版)', description: '适合竖版内容' },
    { value: '1:1', label: '1:1 (正方形)', description: '适合社交媒体' },
    { value: '21:9', label: '21:9 (超宽屏)', description: '电影宽银幕' },
    { value: '2.35:1', label: '2.35:1 (电影)', description: '经典电影比例' },
  ];
  const [importing, setImporting] = useState(false);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  const [editingNovel, setEditingNovel] = useState<Novel | null>(null);
  
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

  const parseCharacters = async (novelId: string) => {
    if (!confirm('将使用 AI 分析小说内容并自动提取角色信息，是否继续？\n\n提示：解析可能需要 10-30 秒，请耐心等待。')) return;
    
    setParsingNovelId(novelId);
    try {
      // 使用同步模式，立即获取结果
      const res = await fetch(`${API_BASE}/novels/${novelId}/parse-characters/?sync=true`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        const characters = data.data || [];
        if (characters.length > 0) {
          toast.success(`解析成功！识别到 ${characters.length} 个角色`);
          // 跳转到角色库
          window.location.href = `/characters?novel=${novelId}`;
        } else {
          toast.warning('未识别到角色，请确保章节内容足够丰富');
        }
      } else {
        toast.error('解析失败: ' + data.message);
      }
    } catch (error) {
      console.error('解析角色失败:', error);
      toast.error('解析失败，请检查网络连接');
    } finally {
      setParsingNovelId(null);
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
        return '已完成';
      case 'processing':
        return '处理中';
      default:
        return '待处理';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">小说管理</h1>
          <p className="mt-1 text-sm text-gray-500">
            管理您的小说项目和章节
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowCreateModal(true)}
            className="btn-primary"
          >
            <Plus className="mr-2 h-4 w-4" />
            新建小说
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder="搜索小说..."
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
          <h3 className="mt-4 text-lg font-medium text-gray-900">暂无小说</h3>
          <p className="mt-1 text-sm text-gray-500">
            开始创建您的小说项目
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
                {/* 删除按钮 - 右上角 */}
                <button
                  onClick={() => deleteNovel(novel.id)}
                  className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
                  title="删除"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                {/* 编辑按钮 - 右下角 */}
                <button
                  onClick={() => setEditingNovel(novel)}
                  className="absolute bottom-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
                  title="编辑"
                >
                  <Edit2 className="h-4 w-4" />
                </button>
              </div>
              <div className="p-4">
                <h3 className="text-lg font-semibold text-gray-900 truncate">
                  {novel.title}
                </h3>
                <p className="text-sm text-gray-500 mt-1">{novel.author}</p>
                <p className="text-sm text-gray-600 mt-2 line-clamp-2">
                  {novel.description || '暂无描述'}
                </p>
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                  <span className="text-sm text-gray-500">
                    {novel.chapterCount} 章节
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => parseCharacters(novel.id)}
                      disabled={parsingNovelId === novel.id}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-purple-100 text-purple-600 hover:bg-purple-200 transition-colors disabled:opacity-50 text-sm"
                      title="AI解析角色"
                    >
                      {parsingNovelId === novel.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Sparkles className="h-4 w-4" />
                      )}
                      <span>AI解析角色</span>
                    </button>
                    <Link
                      to={`/characters?novel=${novel.id}`}
                      className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition-colors"
                      title="查看角色"
                    >
                      <Users className="h-4 w-4" />
                    </Link>
                    <Link
                      to={`/novels/${novel.id}`}
                      className="btn-primary text-sm py-2 px-3"
                    >
                      <Play className="h-3 w-3 mr-1" />
                      管理章节
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
            <h2 className="text-lg font-semibold text-gray-900 mb-4">新建小说</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  标题
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
                  作者
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
                  描述
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
                  人设提示词
                </label>
                <select
                  value={newNovel.promptTemplateId}
                  onChange={(e) => setNewNovel({ ...newNovel, promptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  <option value="">使用系统默认</option>
                  {promptTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name} {template.isSystem ? '(系统)' : '(自定义)'}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  选择用于生成角色人设图的提示词风格
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  拆分分镜提示词
                </label>
                <select
                  value={newNovel.chapterSplitPromptTemplateId}
                  onChange={(e) => setNewNovel({ ...newNovel, chapterSplitPromptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  <option value="">使用系统默认</option>
                  {chapterSplitTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name} {template.isSystem ? '【系统默认】' : '【用户自定义】'}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  选择用于章节拆分为分镜的提示词风格
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  画面比例
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
                  取消
                </button>
                <button type="submit" className="btn-primary">
                  创建
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
            <h2 className="text-lg font-semibold text-gray-900 mb-4">编辑小说</h2>
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
                  标题
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
                  作者
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
                  描述
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
                  人设提示词
                </label>
                <select
                  value={editingNovel.promptTemplateId || ''}
                  onChange={(e) => setEditingNovel({ ...editingNovel, promptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  <option value="">使用系统默认</option>
                  {promptTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name} {template.isSystem ? '(系统)' : '(自定义)'}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  选择用于生成角色人设图的提示词风格
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  拆分分镜提示词
                </label>
                <select
                  value={editingNovel.chapterSplitPromptTemplateId || ''}
                  onChange={(e) => setEditingNovel({ ...editingNovel, chapterSplitPromptTemplateId: e.target.value })}
                  className="input-field mt-1"
                >
                  <option value="">使用系统默认</option>
                  {chapterSplitTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name} {template.isSystem ? '【系统默认】' : '【用户自定义】'}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  选择用于章节拆分为分镜的提示词风格
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  画面比例
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
                  取消
                </button>
                <button type="submit" className="btn-primary">
                  保存
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
