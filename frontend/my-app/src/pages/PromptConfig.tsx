import { useState, useEffect } from 'react';
import { 
  Plus, 
  Edit2, 
  Trash2, 
  Loader2,
  Save,
  X,
  Eye,
  FileText,
  BookOpen,
  Copy
} from 'lucide-react';
import { toast } from '../stores/toastStore';

interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  template: string;
  type: string;
  isSystem: boolean;
  isActive: boolean;
  createdAt: string;
}

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 默认人设提示词模板
const DEFAULT_CHARACTER_TEMPLATE = "character portrait, anime style, high quality, detailed, {appearance}, {description}, single character, centered, clean background, professional artwork, 8k";

// 默认章节拆分提示词模板
const DEFAULT_CHAPTER_SPLIT_TEMPLATE = `你是一名资深影视导演、分镜设计师、动画脚本结构专家。

任务：
将用户提供的小说章节内容，拆分为适用于AI动画制作的分镜数据结构。

核心要求：

1. 严格按照影视分镜逻辑进行拆分
2. 每个分镜必须具备：
   - 明确的画面动作
   - 清晰的场景位置
   - 出现角色
   - 可视化描述（用于AI生成图像）
3. 每个分镜的剧情字数必须控制在 {每个分镜对应拆分故事字数} 左右（允许±20%浮动）
4. 所有画面视觉描述必须符合：{图像风格}
5. 不允许长段叙事，一个镜头只表达一个清晰动作或画面
6. 输出必须是纯JSON，不允许任何解释文字，不允许Markdown
7. 必须提取：
   - chapter 章节标题
   - characters 本章出现角色（去重）
   - scenes 本章出现的场景（去重）
   - shots 分镜数组

分镜规则：

- id：从1递增
- description：必须是画面级描述，带动作感，便于AI生图
- characters：当前镜头出现角色
- scene：当前镜头所在场景
- duration：根据动作复杂度自动估算时长（3-10秒）

时长规则：
- 静态画面：3-5秒
- 对话画面：5-8秒
- 动作冲突：6-10秒

禁止：
- 不得出现心理描写无法可视化内容
- 不得输出无效空镜头
- 不得改变原剧情走向

输出格式必须严格如下：

{
    "chapter": "第3章 客人",
    "characters": [
        "萧炎",
        "萧战",
        "葛叶"
    ],
    "scenes": [
        "萧家门口",
        "萧家大厅",
        "练武场"
    ],
    "shots": [
        {
            "id": 1,
            "description": "萧炎站在萧家门口，仰望牌匾",
            "characters": [
                "萧炎"
            ],
            "scene": "萧家门口",
            "duration": 5
        },
        {
            "id": 2,
            "description": "萧战从大厅走出，面带忧色",
            "characters": [
                "萧战"
            ],
            "scene": "萧家大厅",
            "duration": 8
        }
    ]
}`;

export default function PromptConfig() {
  // 人设提示词状态
  const [characterTemplates, setCharacterTemplates] = useState<PromptTemplate[]>([]);
  const [loadingCharacter, setLoadingCharacter] = useState(true);
  
  // 章节拆分提示词状态
  const [chapterSplitTemplates, setChapterSplitTemplates] = useState<PromptTemplate[]>([]);
  const [loadingChapterSplit, setLoadingChapterSplit] = useState(true);
  
  // 模态框状态
  const [showModal, setShowModal] = useState(false);
  const [showViewModal, setShowViewModal] = useState(false);
  const [modalType, setModalType] = useState<'character' | 'chapter_split'>('character');
  const [editingPrompt, setEditingPrompt] = useState<PromptTemplate | null>(null);
  const [viewingPrompt, setViewingPrompt] = useState<PromptTemplate | null>(null);
  const [form, setForm] = useState({ 
    name: '', 
    description: '', 
    template: DEFAULT_CHARACTER_TEMPLATE,
    wordCount: 50  // 每个分镜对应拆分故事字数
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchCharacterTemplates();
    fetchChapterSplitTemplates();
  }, []);

  const fetchCharacterTemplates = async () => {
    setLoadingCharacter(true);
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/?type=character`);
      const data = await res.json();
      if (data.success) {
        setCharacterTemplates(data.data);
      }
    } catch (error) {
      console.error('加载人设提示词模板失败:', error);
    } finally {
      setLoadingCharacter(false);
    }
  };

  const fetchChapterSplitTemplates = async () => {
    setLoadingChapterSplit(true);
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/?type=chapter_split`);
      const data = await res.json();
      if (data.success) {
        setChapterSplitTemplates(data.data);
      }
    } catch (error) {
      console.error('加载章节拆分提示词模板失败:', error);
    } finally {
      setLoadingChapterSplit(false);
    }
  };

  const handleOpenModal = (type: 'character' | 'chapter_split', template?: PromptTemplate) => {
    setModalType(type);
    if (template) {
      setEditingPrompt(template);
      // 从模板内容中提取字数设置（如果是章节拆分类型）
      let wordCount = 50;
      if (type === 'chapter_split') {
        const match = template.template.match(/必须控制在\s*{?每个分镜对应拆分故事字数}?\s*左右/);
        if (match) {
          // 尝试从模板中提取已设置的字数
          const numMatch = template.template.match(/必须控制在\s*(\d+)\s*字/);
          if (numMatch) {
            wordCount = parseInt(numMatch[1]);
          }
        }
      }
      setForm({
        name: template.name,
        description: template.description,
        template: template.template,
        wordCount
      });
    } else {
      setEditingPrompt(null);
      setForm({ 
        name: '', 
        description: '', 
        template: type === 'character' ? DEFAULT_CHARACTER_TEMPLATE : DEFAULT_CHAPTER_SPLIT_TEMPLATE,
        wordCount: 50
      });
    }
    setShowModal(true);
  };

  const handleOpenViewModal = (template: PromptTemplate) => {
    setViewingPrompt(template);
    setShowViewModal(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      // 处理章节拆分提示词中的字数占位符
      let templateContent = form.template;
      if (modalType === 'chapter_split') {
        // 替换或插入字数设置
        templateContent = templateContent.replace(
          /每个分镜的剧情字数必须控制在\s*{?每个分镜对应拆分故事字数}?\s*左右/,
          `每个分镜的剧情字数必须控制在 ${form.wordCount} 字左右`
        );
        // 同时更新占位符的默认值
        templateContent = templateContent.replace(
          /{每个分镜对应拆分故事字数}/g,
          `${form.wordCount}`
        );
      }

      const url = editingPrompt 
        ? `${API_BASE}/prompt-templates/${editingPrompt.id}/`
        : `${API_BASE}/prompt-templates/`;
      
      const method = editingPrompt ? 'PUT' : 'POST';
      
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          description: form.description,
          template: templateContent,
          type: modalType
        })
      });

      const data = await res.json();
      if (data.success) {
        setShowModal(false);
        if (modalType === 'character') {
          fetchCharacterTemplates();
        } else {
          fetchChapterSplitTemplates();
        }
      } else {
        toast.error(data.message || '保存失败');
      }
    } catch (error) {
      console.error('保存提示词模板失败:', error);
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async (template: PromptTemplate) => {
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/${template.id}/copy/`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.success) {
        if (template.type === 'character') {
          fetchCharacterTemplates();
        } else {
          fetchChapterSplitTemplates();
        }
      } else {
        toast.error(data.message || '复制失败');
      }
    } catch (error) {
      console.error('复制提示词模板失败:', error);
      toast.error('复制失败');
    }
  };

  const handleDelete = async (template: PromptTemplate) => {
    if (!confirm(`确定要删除提示词模板 "${template.name}" 吗？`)) return;
    
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/${template.id}/`, {
        method: 'DELETE'
      });
      const data = await res.json();
      if (data.success) {
        if (template.type === 'character') {
          fetchCharacterTemplates();
        } else {
          fetchChapterSplitTemplates();
        }
      } else {
        toast.error(data.message || '删除失败');
      }
    } catch (error) {
      console.error('删除提示词模板失败:', error);
      toast.error('删除失败');
    }
  };

  // 渲染提示词列表
  const renderTemplateList = (templates: PromptTemplate[], loading: boolean, type: 'character' | 'chapter_split') => {
    if (loading) {
      return (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      );
    }

    if (templates.length === 0) {
      return <p className="text-sm text-gray-500 py-4">暂无提示词模板</p>;
    }

    return (
      <div className="space-y-3">
        {templates.map((template) => (
          <div 
            key={template.id} 
            className="flex items-center justify-between p-4 rounded-lg border border-gray-200 hover:border-gray-300 bg-white transition-colors"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h4 className="font-medium text-gray-900">{template.name}</h4>
                {template.isSystem ? (
                  <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-600 rounded-full">系统默认</span>
                ) : (
                  <span className="text-xs px-2 py-0.5 bg-green-100 text-green-600 rounded-full">用户自定义</span>
                )}
              </div>
              <p className="text-sm text-gray-500 truncate">{template.description}</p>
              <p className="text-xs text-gray-400 mt-1 truncate font-mono">
                {template.template.substring(0, type === 'chapter_split' ? 120 : 80)}...
              </p>
            </div>
            <div className="flex items-center gap-1 ml-4">
              {template.isSystem ? (
                <>
                  <button
                    type="button"
                    onClick={() => handleOpenViewModal(template)}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                    title="查看"
                  >
                    <Eye className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleCopy(template)}
                    className="p-1.5 text-gray-400 hover:text-green-600 hover:bg-green-100 rounded transition-colors"
                    title="复制为用户模板"
                  >
                    <Copy className="h-4 w-4" />
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => handleOpenViewModal(template)}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                    title="查看"
                  >
                    <Eye className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleOpenModal(type, template)}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                    title="编辑"
                  >
                    <Edit2 className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(template)}
                    className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-100 rounded transition-colors"
                    title="删除"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">提示词配置</h1>
        <p className="mt-1 text-sm text-gray-500">
          管理 AI 角色生成和章节拆分提示词模板
        </p>
      </div>

      {/* AI角色提示词管理 */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-purple-600" />
            <h2 className="text-lg font-semibold text-gray-900">AI角色提示词管理</h2>
          </div>
          <button
            type="button"
            onClick={() => handleOpenModal('character')}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors"
          >
            <Plus className="h-4 w-4" />
            新建提示词
          </button>
        </div>
        {renderTemplateList(characterTemplates, loadingCharacter, 'character')}
      </div>

      {/* 章节拆分分镜提示词管理 */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-orange-600" />
            <h2 className="text-lg font-semibold text-gray-900">章节拆分分镜提示词管理</h2>
          </div>
          <button
            type="button"
            onClick={() => handleOpenModal('chapter_split')}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors"
          >
            <Plus className="h-4 w-4" />
            新建提示词
          </button>
        </div>
        {renderTemplateList(chapterSplitTemplates, loadingChapterSplit, 'chapter_split')}
      </div>

      {/* 编辑/创建模态框 */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">
                {editingPrompt ? (editingPrompt.isSystem ? '查看提示词模板' : '编辑提示词模板') : '新建提示词模板'}
                {editingPrompt?.isSystem && (
                  <span className="ml-2 text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">系统预设（只读）</span>
                )}
              </h3>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">名称</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="input-field mt-1"
                  placeholder="例如：标准动漫风格"
                  readOnly={editingPrompt?.isSystem}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">描述</label>
                <textarea
                  rows={2}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="input-field mt-1"
                  placeholder="描述这个提示词模板的用途..."
                  readOnly={editingPrompt?.isSystem}
                />
              </div>

              {/* 章节拆分特有：字数设置 */}
              {modalType === 'chapter_split' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700">
                    每个分镜对应拆分故事字数
                  </label>
                  <div className="flex items-center gap-2 mt-1">
                    <input
                      type="number"
                      min={10}
                      max={500}
                      value={form.wordCount}
                      onChange={(e) => setForm({ ...form, wordCount: parseInt(e.target.value) || 50 })}
                      className="input-field w-24"
                      readOnly={editingPrompt?.isSystem}
                    />
                    <span className="text-sm text-gray-500">字</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    每个分镜的剧情字数控制在此数值左右（允许±20%浮动）
                  </p>
                </div>
              )}
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  提示词模板
                  <span className="text-xs text-gray-500 ml-2">
                    {modalType === 'character' 
                      ? '使用 {appearance} 和 {description} 作为占位符'
                      : '使用 {每个分镜对应拆分故事字数} 和 {图像风格} 作为占位符'
                    }
                  </span>
                </label>
                <textarea
                  rows={modalType === 'chapter_split' ? 12 : 6}
                  required
                  value={form.template}
                  onChange={(e) => setForm({ ...form, template: e.target.value })}
                  className="input-field font-mono text-sm"
                  placeholder={modalType === 'character' ? "character portrait..." : "你是一名资深影视导演..."}
                  readOnly={editingPrompt?.isSystem}
                />
                <p className="text-xs text-gray-500 mt-1">
                  {modalType === 'character' 
                    ? '提示：{appearance} 会被替换为角色外貌，{description} 会被替换为角色描述'
                    : '提示：{每个分镜对应拆分故事字数} 会被替换为上面设置的字数'
                  }
                </p>
              </div>
              
              {/* 预览 */}
              <div className="bg-gray-50 p-3 rounded-lg">
                <label className="block text-xs font-medium text-gray-500 mb-1">预览效果</label>
                <p className="text-sm text-gray-700 font-mono whitespace-pre-wrap">
                  {modalType === 'character' 
                    ? form.template
                        .replace('{appearance}', 'brown hair, blue eyes')
                        .replace('{description}', 'a cheerful young girl')
                    : form.template
                        .substring(0, 200) + (form.template.length > 200 ? '...' : '')
                  }
                </p>
              </div>
              
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="btn-secondary"
                >
                  {editingPrompt?.isSystem ? '关闭' : '取消'}
                </button>
                {!editingPrompt?.isSystem && (
                  <button
                    type="submit"
                    disabled={saving}
                    className="btn-primary"
                  >
                    {saving ? (
                      <><Loader2 className="mr-2 h-4 w-4 animate-spin" />保存中...</>
                    ) : (
                      <><Save className="mr-2 h-4 w-4" />保存</>
                    )}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 查看模态框（只读，用于显示完整内容） */}
      {showViewModal && viewingPrompt && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold text-gray-900">{viewingPrompt.name}</h3>
                {viewingPrompt.isSystem && (
                  <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-600 rounded-full">系统默认</span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setShowViewModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-500">描述</label>
                <p className="text-sm text-gray-700 mt-1">{viewingPrompt.description}</p>
              </div>

              {/* 字数设置显示（仅章节拆分类型） */}
              {viewingPrompt.type === 'chapter_split' && (
                <div>
                  <label className="block text-sm font-medium text-gray-500">每个分镜对应拆分故事字数</label>
                  <p className="text-sm text-gray-700 mt-1">
                    {(() => {
                      const match = viewingPrompt.template.match(/必须控制在\s*(\d+)\s*字左右/);
                      return match ? match[1] : '50';
                    })()} 字
                  </p>
                </div>
              )}
              
              <div>
                <label className="block text-sm font-medium text-gray-500">提示词内容</label>
                <div className="mt-1 p-4 bg-gray-50 rounded-lg border border-gray-200">
                  <pre className="text-sm text-gray-700 font-mono whitespace-pre-wrap">
                    {viewingPrompt.template}
                  </pre>
                </div>
              </div>
              
              <div className="flex justify-end gap-3 pt-4">
                {viewingPrompt.isSystem && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowViewModal(false);
                      handleCopy(viewingPrompt);
                    }}
                    className="btn-primary"
                  >
                    <Copy className="mr-2 h-4 w-4" />
                    复制为用户模板
                  </button>
                )}
                {!viewingPrompt.isSystem && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowViewModal(false);
                      handleOpenModal(viewingPrompt.type as 'character' | 'chapter_split', viewingPrompt);
                    }}
                    className="btn-primary"
                  >
                    <Edit2 className="mr-2 h-4 w-4" />
                    编辑
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setShowViewModal(false)}
                  className="btn-secondary"
                >
                  关闭
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
