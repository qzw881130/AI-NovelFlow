import { useState, useEffect } from 'react';
import { 
  Plus, 
  Search, 
  Trash2, 
  Edit2, 
  Loader2,
  User,
  Wand2,
  Sparkles,
  RefreshCw
} from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import type { Character, Novel } from '../types';
import { toast } from '../stores/toastStore';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface CharacterWithNovel extends Character {
  novelName?: string;
}

export default function Characters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [characters, setCharacters] = useState<CharacterWithNovel[]>([]);
  const [novels, setNovels] = useState<Novel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  // 支持 novel 或 novel_id 参数
  const novelIdFromUrl = searchParams.get('novel') || searchParams.get('novel_id') || 'all';
  const highlightId = searchParams.get('highlight');
  const [selectedNovel, setSelectedNovel] = useState<string>(novelIdFromUrl);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingCharacter, setEditingCharacter] = useState<Character | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [generatingAppearanceId, setGeneratingAppearanceId] = useState<string | null>(null);
  const [characterPrompts, setCharacterPrompts] = useState<Record<string, { prompt: string; templateName: string }>>({});
  const [highlightedId, setHighlightedId] = useState<string | null>(highlightId);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    novelId: string | null;
  }>({ isOpen: false, novelId: null });
  
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    appearance: '',
    novelId: '',
  });

  // 加载角色和小说数据
  useEffect(() => {
    fetchCharacters();
    fetchNovels();
  }, [selectedNovel]);

  // 处理高亮角色 - 滚动到对应位置并添加高亮效果
  useEffect(() => {
    if (highlightedId && characters.length > 0) {
      const element = document.getElementById(`character-${highlightedId}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // 3秒后移除高亮效果
        setTimeout(() => setHighlightedId(null), 3000);
      }
    }
  }, [highlightedId, characters]);

  const fetchCharacters = async () => {
    setIsLoading(true);
    try {
      const url = selectedNovel !== 'all' 
        ? `${API_BASE}/characters?novel_id=${selectedNovel}` 
        : `${API_BASE}/characters`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.success) {
        setCharacters(data.data || []);
        // 加载每个角色的提示词
        const chars = data.data || [];
        for (const char of chars) {
          fetchCharacterPrompt(char.id);
        }
      }
    } catch (error) {
      console.error('获取角色失败:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchCharacterPrompt = async (characterId: string) => {
    try {
      const res = await fetch(`${API_BASE}/characters/${characterId}/prompt/`);
      const data = await res.json();
      if (data.success) {
        setCharacterPrompts(prev => ({
          ...prev,
          [characterId]: {
            prompt: data.data.prompt,
            templateName: data.data.templateName
          }
        }));
      }
    } catch (error) {
      console.error('获取角色提示词失败:', error);
    }
  };

  const fetchNovels = async () => {
    try {
      const res = await fetch(`${API_BASE}/novels/`);
      const data = await res.json();
      if (data.success) {
        setNovels(data.data || []);
      }
    } catch (error) {
      console.error('获取小说失败:', error);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/characters/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      const data = await res.json();
      if (data.success) {
        setCharacters([data.data, ...characters]);
        setShowCreateModal(false);
        setFormData({ name: '', description: '', appearance: '', novelId: '' });
      }
    } catch (error) {
      console.error('创建角色失败:', error);
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingCharacter) return;
    
    try {
      const res = await fetch(`${API_BASE}/characters/${editingCharacter.id}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingCharacter),
      });
      const data = await res.json();
      if (data.success) {
        setCharacters(characters.map(c => c.id === data.data.id ? data.data : c));
        setEditingCharacter(null);
      }
    } catch (error) {
      console.error('更新角色失败:', error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个角色吗？')) return;
    
    try {
      await fetch(`${API_BASE}/characters/${id}/`, { method: 'DELETE' });
      setCharacters(characters.filter(c => c.id !== id));
    } catch (error) {
      console.error('删除角色失败:', error);
    }
  };

  const generateAppearance = async (character: Character) => {
    if (!character.description) {
      toast.warning('请先在编辑中添加角色描述，才能智能生成外貌');
      return;
    }
    
    setGeneratingAppearanceId(character.id);
    try {
      const res = await fetch(`${API_BASE}/characters/${character.id}/generate-appearance/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (data.success) {
        // 更新角色数据
        setCharacters(prev => prev.map(c => 
          c.id === character.id ? { ...c, appearance: data.data.appearance } : c
        ));
        toast.success('外貌描述生成成功！');
      } else {
        toast.error('生成失败: ' + data.message);
      }
    } catch (error) {
      console.error('生成外貌描述失败:', error);
      toast.error('生成失败');
    } finally {
      setGeneratingAppearanceId(null);
    }
  };

  const generatePortrait = async (character: Character) => {
    // 检查是否已经在生成中
    if (character.generatingStatus === 'running') {
      toast.info('该角色正在生成形象中，请稍后再试');
      return;
    }
    
    setGeneratingId(character.id);
    try {
      // 调用任务API创建设定图生成任务
      const res = await fetch(`${API_BASE}/tasks/character/${character.id}/generate-portrait/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (data.success) {
        // 更新本地状态为生成中
        setCharacters(prev => prev.map(c => 
          c.id === character.id ? { ...c, generatingStatus: 'running' } : c
        ));
        toast.success('人设图生成任务已创建，请前往任务队列查看进度');
        // 跳转到任务队列
        window.location.href = '/tasks';
      } else {
        toast.error(data.message || '创建任务失败');
        setGeneratingId(null);
      }
    } catch (error) {
      console.error('生成人设图失败:', error);
      toast.error('创建任务失败');
      setGeneratingId(null);
    }
  };

  const filteredCharacters = characters.filter(c => 
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const openParseConfirm = (novelId: string) => {
    setConfirmDialog({ isOpen: true, novelId });
  };

  const closeParseConfirm = () => {
    setConfirmDialog({ isOpen: false, novelId: null });
  };

  const confirmParseCharacters = async () => {
    const novelId = confirmDialog.novelId;
    if (!novelId) return;
    
    closeParseConfirm();
    setParsingNovelId(novelId);
    
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/parse-characters/?sync=true`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        const chars = data.data || [];
        if (chars.length > 0) {
          toast.success(`解析成功！识别到 ${chars.length} 个角色`);
          fetchCharacters();
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

  const getNovelName = (novelId: string) => {
    const novel = novels.find(n => n.id === novelId);
    return novel?.title || '未知小说';
  };

  // 根据小说ID获取画面比例
  const getNovelAspectRatio = (novelId: string): string => {
    const novel = novels.find(n => n.id === novelId);
    return novel?.aspectRatio || '16:9';
  };

  // 根据画面比例计算图片容器样式
  const getAspectRatioClass = (aspectRatio: string): string => {
    switch (aspectRatio) {
      case '16:9':
        return 'aspect-video'; // 16:9
      case '9:16':
        return 'aspect-[9/16]';
      case '4:3':
        return 'aspect-[4/3]';
      case '3:4':
        return 'aspect-[3/4]';
      case '1:1':
        return 'aspect-square';
      case '21:9':
        return 'aspect-[21/9]';
      case '2.35:1':
        return 'aspect-[2.35/1]';
      default:
        return 'aspect-video';
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">角色库</h1>
          <p className="mt-1 text-sm text-gray-500">
            管理小说角色的详细信息和形象设定
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="btn-primary"
        >
          <Plus className="mr-2 h-4 w-4" />
          新建角色
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
          <input
            type="text"
            placeholder="搜索角色..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="input-field pl-10"
          />
        </div>
        <select
          value={selectedNovel}
          onChange={(e) => {
            setSelectedNovel(e.target.value);
            if (e.target.value !== 'all') {
              setSearchParams({ novel: e.target.value });
            } else {
              setSearchParams({});
            }
          }}
          className="input-field sm:w-48"
        >
          <option value="all">所有小说</option>
          {novels.map(novel => (
            <option key={novel.id} value={novel.id}>{novel.title}</option>
          ))}
        </select>
      </div>

      {/* Characters Grid */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
        </div>
      ) : filteredCharacters.length === 0 ? (
        <div className="card text-center py-12">
          <User className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">暂无角色</h3>
          <p className="mt-1 text-sm text-gray-500">
            点击"新建角色"创建你的第一个角色或者"AI解析角色"
          </p>
          {selectedNovel !== 'all' && (
            <div className="mt-4">
              <button
                onClick={() => openParseConfirm(selectedNovel)}
                disabled={parsingNovelId === selectedNovel}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-100 text-purple-600 hover:bg-purple-200 transition-colors disabled:opacity-50"
              >
                {parsingNovelId === selectedNovel ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                <span>AI解析角色</span>
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredCharacters.map((character) => {
            const aspectRatio = getNovelAspectRatio(character.novelId);
            const aspectClass = getAspectRatioClass(aspectRatio);
            
            return (
            <div
              key={character.id}
              id={`character-${character.id}`}
              className={`bg-white rounded-lg shadow-sm border overflow-hidden hover:shadow-md transition-all ${
                highlightedId === character.id 
                  ? 'ring-4 ring-blue-500 ring-opacity-50 border-blue-500 animate-pulse' 
                  : 'border-gray-200'
              }`}
            >
              {/* Character Image - 根据小说画面比例显示 */}
              <div className={`${aspectClass} bg-gray-100 relative w-full`}>
                {character.imageUrl ? (
                  <img
                    src={character.imageUrl}
                    alt={character.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <User className="h-20 w-20 text-gray-300" />
                  </div>
                )}
                
                {/* Status Badge */}
                {character.generatingStatus === 'running' && (
                  <div className="absolute top-2 left-2 px-2 py-1 bg-blue-500 text-white text-xs rounded-full flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    生成中
                  </div>
                )}
                {character.generatingStatus === 'failed' && (
                  <div className="absolute top-2 left-2 px-2 py-1 bg-red-500 text-white text-xs rounded-full">
                    生成失败
                  </div>
                )}
                
                {/* Generate Button Overlay - 只在悬停时显示提示 */}
                {!character.imageUrl && character.generatingStatus !== 'running' && (
                  <div className="absolute inset-0 bg-black bg-opacity-30 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity pointer-events-none">
                    <span className="text-white text-sm font-medium">点击下方按钮生成</span>
                  </div>
                )}
                
                {/* Loading Overlay - when local state shows generating */}
                {generatingId === character.id && (
                  <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
                    <div className="text-center">
                      <Loader2 className="h-8 w-8 animate-spin text-white mx-auto" />
                      <p className="text-white text-sm mt-2">生成中...</p>
                    </div>
                  </div>
                )}
              </div>

              {/* Character Info */}
              <div className="p-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-gray-900 truncate">
                    {character.name}
                  </h3>
                  <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded">
                    {aspectRatio}
                  </span>
                </div>
                <p className="text-xs text-primary-600 mt-1">
                  {getNovelName(character.novelId)}
                </p>
                
                {/* 角色描述 - 可滚动显示完整内容 */}
                {character.description && (
                  <div className="mt-3">
                    <p className="text-xs text-gray-400 mb-1">描述</p>
                    <div className="text-sm text-gray-600 max-h-20 overflow-y-auto pr-1 scrollbar-thin">
                      {character.description}
                    </div>
                  </div>
                )}
                
                {/* 外貌特征 - 可滚动显示完整内容 */}
                {character.appearance ? (
                  <div className="mt-3">
                    <p className="text-xs text-gray-400 mb-1">外貌特征</p>
                    <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-24 overflow-y-auto scrollbar-thin">
                      {character.appearance}
                    </div>
                  </div>
                ) : (
                  <div className="mt-3">
                    <button
                      onClick={() => generateAppearance(character)}
                      disabled={generatingAppearanceId === character.id || !character.description}
                      className="text-xs inline-flex items-center text-primary-600 hover:text-primary-700 disabled:opacity-50"
                    >
                      {generatingAppearanceId === character.id ? (
                        <>
                          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                          生成中...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-3 w-3 mr-1" />
                          AI生成外貌描述
                        </>
                      )}
                    </button>
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                  <div className="flex gap-2">
                    {/* 生成形象按钮 - 无论是否有图片都显示 */}
                    <button
                      onClick={() => generatePortrait(character)}
                      disabled={generatingId === character.id || character.generatingStatus === 'running'}
                      className="p-2 text-gray-400 hover:text-primary-600 transition-colors disabled:opacity-50"
                      title={character.imageUrl ? '重新生成' : '生成形象'}
                    >
                      {character.generatingStatus === 'running' ? (
                        <Loader2 className="h-4 w-4 animate-spin text-primary-600" />
                      ) : (
                        <Wand2 className="h-4 w-4" />
                      )}
                    </button>
                    <button
                      onClick={() => setEditingCharacter(character)}
                      className="p-2 text-gray-400 hover:text-blue-600 transition-colors"
                      title="编辑"
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                  </div>
                  <button
                    onClick={() => handleDelete(character.id)}
                    className="p-2 text-gray-400 hover:text-red-600 transition-colors"
                    title="删除"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>

                {/* 生成提示词 */}
                {characterPrompts[character.id] && (
                  <div className="mt-3 pt-3 border-t border-gray-100">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs text-gray-400">生成提示词</p>
                      <span className="text-xs text-gray-400">{characterPrompts[character.id].templateName}</span>
                    </div>
                    <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-20 overflow-y-auto scrollbar-thin font-mono">
                      {characterPrompts[character.id].prompt}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
          })}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">新建角色</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  所属小说
                </label>
                <select
                  required
                  value={formData.novelId}
                  onChange={(e) => setFormData({ ...formData, novelId: e.target.value })}
                  className="input-field mt-1"
                >
                  <option value="">请选择小说</option>
                  {novels.map(novel => (
                    <option key={novel.id} value={novel.id}>{novel.title}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  角色名称 *
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="input-field mt-1"
                  placeholder="如：萧炎"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  角色描述
                </label>
                <textarea
                  rows={3}
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="input-field mt-1"
                  placeholder="角色的背景故事、性格特点等"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  外貌特征
                </label>
                <textarea
                  rows={3}
                  value={formData.appearance}
                  onChange={(e) => setFormData({ ...formData, appearance: e.target.value })}
                  className="input-field mt-1"
                  placeholder="用于生成人设图的描述，如：黑发，红衣，手持长剑..."
                />
                <p className="mt-1 text-xs text-gray-500">
                  详细的外貌描述有助于生成更准确的角色形象
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
                  创建角色
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editingCharacter && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">编辑角色</h2>
            <form onSubmit={handleUpdate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  角色名称 *
                </label>
                <input
                  type="text"
                  required
                  value={editingCharacter.name}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, name: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  角色描述
                </label>
                <textarea
                  rows={3}
                  value={editingCharacter.description}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, description: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  外貌特征
                </label>
                <textarea
                  rows={3}
                  value={editingCharacter.appearance}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, appearance: e.target.value })}
                  className="input-field mt-1"
                  placeholder="用于生成人设图的描述..."
                />
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setEditingCharacter(null)}
                  className="btn-secondary"
                >
                  取消
                </button>
                <button type="submit" className="btn-primary">
                  保存修改
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* AI解析角色确认对话框 */}
      {confirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-purple-100 rounded-full">
                <Sparkles className="h-6 w-6 text-purple-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">AI解析角色</h3>
            </div>
            <p className="text-gray-600 mb-2">
              将使用 AI 分析小说内容并自动提取角色信息，是否继续？
            </p>
            <p className="text-sm text-gray-500 mb-6">
              提示：解析可能需要 10-30 秒，请耐心等待。
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={closeParseConfirm}
                className="px-4 py-2 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={confirmParseCharacters}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
