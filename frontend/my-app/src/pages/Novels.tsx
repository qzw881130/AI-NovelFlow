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

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function Novels() {
  const { novels, isLoading, fetchNovels, createNovel, deleteNovel, importNovel, updateNovel } = useNovelStore();
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newNovel, setNewNovel] = useState({ title: '', author: '', description: '' });
  const [importing, setImporting] = useState(false);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  const [editingNovel, setEditingNovel] = useState<Novel | null>(null);

  useEffect(() => {
    fetchNovels();
  }, []);

  const filteredNovels = novels.filter(
    (novel) =>
      novel.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      novel.author.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    await createNovel(newNovel);
    setShowCreateModal(false);
    setNewNovel({ title: '', author: '', description: '' });
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setImporting(true);
    await importNovel(file);
    setImporting(false);
  };

  const parseCharacters = async (novelId: string) => {
    if (!confirm('将使用 AI 分析小说内容并自动提取角色信息，是否继续？')) return;
    
    setParsingNovelId(novelId);
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/parse-characters`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        alert('角色解析任务已启动，请稍后到角色库查看结果');
      } else {
        alert('启动失败: ' + data.message);
      }
    } catch (error) {
      console.error('解析角色失败:', error);
      alert('解析失败');
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
          <label className="btn-secondary cursor-pointer">
            <input
              type="file"
              accept=".txt"
              className="hidden"
              onChange={handleImport}
              disabled={importing}
            />
            {importing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            导入 TXT
          </label>
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
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
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
            开始创建您的小说项目或导入 TXT 文件
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredNovels.map((novel) => (
            <div
              key={novel.id}
              className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden hover:shadow-md transition-shadow"
            >
              <div className="aspect-[3/4] bg-gray-100 relative">
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
                <div className="absolute top-2 right-2">
                  <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(novel.status)}`}>
                    {getStatusText(novel.status)}
                  </span>
                </div>
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
                  <div className="flex gap-1">
                    <button
                      onClick={() => parseCharacters(novel.id)}
                      disabled={parsingNovelId === novel.id}
                      className="p-2 text-gray-400 hover:text-purple-600 transition-colors disabled:opacity-50"
                      title="AI解析角色"
                    >
                      {parsingNovelId === novel.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Sparkles className="h-4 w-4" />
                      )}
                    </button>
                    <Link
                      to={`/characters?novel=${novel.id}`}
                      className="p-2 text-gray-400 hover:text-primary-600 transition-colors"
                      title="查看角色"
                    >
                      <Users className="h-4 w-4" />
                    </Link>
                    <button
                      onClick={() => setEditingNovel(novel)}
                      className="p-2 text-gray-400 hover:text-blue-600 transition-colors"
                      title="编辑"
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => deleteNovel(novel.id)}
                      className="p-2 text-gray-400 hover:text-red-600 transition-colors"
                      title="删除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                    <Link
                      to={`/novels/${novel.id}`}
                      className="btn-primary text-sm py-1.5 px-3"
                    >
                      <Play className="h-3 w-3 mr-1" />
                      开始
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
