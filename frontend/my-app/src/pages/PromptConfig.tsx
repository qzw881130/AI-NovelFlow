import { useState, useEffect } from 'react';
import { 
  Plus, 
  Edit2, 
  Trash2, 
  Loader2,
  Save,
  X,
  Eye,
  FileText
} from 'lucide-react';

interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  template: string;
  isSystem: boolean;
  isActive: boolean;
  createdAt: string;
}

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 默认提示词模板
const DEFAULT_TEMPLATE = "character portrait, anime style, high quality, detailed, {appearance}, {description}, single character, centered, clean background, professional artwork, 8k";

export default function PromptConfig() {
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<PromptTemplate | null>(null);
  const [form, setForm] = useState({ name: '', description: '', template: DEFAULT_TEMPLATE });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchPromptTemplates();
  }, []);

  const fetchPromptTemplates = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/`);
      const data = await res.json();
      if (data.success) {
        setPromptTemplates(data.data);
      }
    } catch (error) {
      console.error('加载提示词模板失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenModal = (template?: PromptTemplate) => {
    if (template) {
      setEditingPrompt(template);
      setForm({
        name: template.name,
        description: template.description,
        template: template.template
      });
    } else {
      setEditingPrompt(null);
      setForm({ name: '', description: '', template: DEFAULT_TEMPLATE });
    }
    setShowModal(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      const url = editingPrompt 
        ? `${API_BASE}/prompt-templates/${editingPrompt.id}`
        : `${API_BASE}/prompt-templates/`;
      
      const method = editingPrompt ? 'PUT' : 'POST';
      
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form)
      });

      const data = await res.json();
      if (data.success) {
        setShowModal(false);
        fetchPromptTemplates();
      } else {
        alert(data.message || '保存失败');
      }
    } catch (error) {
      console.error('保存提示词模板失败:', error);
      alert('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async (template: PromptTemplate) => {
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/${template.id}/copy`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.success) {
        fetchPromptTemplates();
      } else {
        alert(data.message || '复制失败');
      }
    } catch (error) {
      console.error('复制提示词模板失败:', error);
      alert('复制失败');
    }
  };

  const handleDelete = async (template: PromptTemplate) => {
    if (!confirm(`确定要删除提示词模板 "${template.name}" 吗？`)) return;
    
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/${template.id}`, {
        method: 'DELETE'
      });
      const data = await res.json();
      if (data.success) {
        fetchPromptTemplates();
      } else {
        alert(data.message || '删除失败');
      }
    } catch (error) {
      console.error('删除提示词模板失败:', error);
      alert('删除失败');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">提示词配置</h1>
        <p className="mt-1 text-sm text-gray-500">
          管理 AI 角色生成提示词模板
        </p>
      </div>

      {/* 提示词模板列表 */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-purple-600" />
            <h2 className="text-lg font-semibold text-gray-900">AI角色提示词管理</h2>
          </div>
          <button
            type="button"
            onClick={() => handleOpenModal()}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors"
          >
            <Plus className="h-4 w-4" />
            新建提示词
          </button>
        </div>

        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : promptTemplates.length === 0 ? (
          <p className="text-sm text-gray-500 py-4">暂无提示词模板</p>
        ) : (
          <div className="space-y-3">
            {promptTemplates.map((template) => (
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
                  <p className="text-xs text-gray-400 mt-1 truncate font-mono">{template.template.substring(0, 80)}...</p>
                </div>
                <div className="flex items-center gap-1 ml-4">
                  {template.isSystem ? (
                    <>
                      <button
                        type="button"
                        onClick={() => handleOpenModal(template)}
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
                        <Plus className="h-4 w-4" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => handleOpenModal(template)}
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
        )}
      </div>

      {/* 提示词模板编辑/创建弹窗 */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
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
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  提示词模板
                  <span className="text-xs text-gray-500 ml-2">使用 {"{appearance}"} 和 {"{description}"} 作为占位符</span>
                </label>
                <textarea
                  rows={6}
                  required
                  value={form.template}
                  onChange={(e) => setForm({ ...form, template: e.target.value })}
                  className="input-field font-mono text-sm"
                  placeholder="character portrait, anime style, {appearance}, {description}, high quality"
                  readOnly={editingPrompt?.isSystem}
                />
                <p className="text-xs text-gray-500 mt-1">
                  提示：{"{appearance}"} 会被替换为角色外貌，{"{description}"} 会被替换为角色描述
                </p>
              </div>
              
              {/* 预览 */}
              <div className="bg-gray-50 p-3 rounded-lg">
                <label className="block text-xs font-medium text-gray-500 mb-1">预览效果</label>
                <p className="text-sm text-gray-700 font-mono">
                  {form.template
                    .replace('{appearance}', 'brown hair, blue eyes')
                    .replace('{description}', 'a cheerful young girl')}
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
    </div>
  );
}
