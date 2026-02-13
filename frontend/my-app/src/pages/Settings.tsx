import { useState, useEffect } from 'react';
import { 
  Save, 
  Loader2, 
  Eye, 
  EyeOff, 
  Upload, 
  Edit2, 
  Play, 
  Server, 
  User, 
  Image as ImageIcon, 
  Film, 
  CheckCircle,
  Star,
  Trash2,
  X,
  Plus,
  Check,
  Download
} from 'lucide-react';
import { useConfigStore } from '../stores/configStore';
import JSONEditor from '../components/JSONEditor';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface Workflow {
  id: string;
  name: string;
  description?: string;
  type: 'character' | 'shot' | 'video';
  typeName: string;
  isSystem: boolean;
  isActive: boolean;
}

const typeIcons = {
  character: User,
  shot: ImageIcon,
  video: Film
};

const typeColors = {
  character: 'bg-blue-100 text-blue-600',
  shot: 'bg-amber-100 text-amber-600',
  video: 'bg-pink-100 text-pink-600'
};

const typeNames = {
  character: '人设生成',
  shot: '分镜生图',
  video: '分镜生视频'
};

export default function Settings() {
  const config = useConfigStore();
  const [formData, setFormData] = useState({
    deepseekApiKey: config.deepseekApiKey,
    deepseekApiUrl: config.deepseekApiUrl,
    comfyUIHost: config.comfyUIHost,
    outputResolution: config.outputResolution,
    outputFrameRate: config.outputFrameRate,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  
  // 工作流管理
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadType, setUploadType] = useState<'character' | 'shot' | 'video'>('character');
  const [uploadForm, setUploadForm] = useState({ name: '', description: '', file: null as File | null });
  const [uploading, setUploading] = useState(false);
  
  // 编辑工作流
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [editForm, setEditForm] = useState({ name: '', description: '', workflowJson: '' });
  const [loadingEdit, setLoadingEdit] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);

  // 加载工作流
  useEffect(() => {
    fetchWorkflows();
  }, []);

  const fetchWorkflows = async () => {
    try {
      const res = await fetch(`${API_BASE}/workflows/`);
      const data = await res.json();
      if (data.success) {
        setWorkflows(data.data);
      }
    } catch (error) {
      console.error('加载工作流失败:', error);
    } finally {
      setLoadingWorkflows(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    config.setConfig(formData);
    await new Promise(resolve => setTimeout(resolve, 500));
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleSetDefault = async (workflow: Workflow) => {
    try {
      const res = await fetch(`${API_BASE}/workflows/${workflow.id}/set-default/`, {
        method: 'POST'
      });
      if (res.ok) {
        fetchWorkflows();
      }
    } catch (error) {
      console.error('设置默认工作流失败:', error);
    }
  };

  const handleDelete = async (workflow: Workflow) => {
    if (workflow.isSystem) {
      alert('系统预设工作流不能删除');
      return;
    }
    if (!confirm('确定要删除这个工作流吗？')) return;
    
    try {
      await fetch(`${API_BASE}/workflows/${workflow.id}/`, { method: 'DELETE' });
      fetchWorkflows();
    } catch (error) {
      console.error('删除失败:', error);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadForm.file) {
      alert('请选择工作流文件');
      return;
    }
    
    setUploading(true);
    const formData = new FormData();
    formData.append('name', uploadForm.name);
    formData.append('type', uploadType);
    formData.append('description', uploadForm.description || '');
    formData.append('file', uploadForm.file);
    
    try {
      const res = await fetch(`${API_BASE}/workflows/upload/`, {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        setShowUploadModal(false);
        setUploadForm({ name: '', description: '', file: null });
        fetchWorkflows();
      } else {
        // 处理 FastAPI 验证错误格式
        let errorMsg = '上传失败';
        if (data.detail) {
          if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          } else if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map((e: any) => e.msg || e).join(', ');
          } else {
            errorMsg = JSON.stringify(data.detail);
          }
        }
        alert(errorMsg);
      }
    } catch (error) {
      console.error('上传失败:', error);
      alert('上传失败: ' + (error instanceof Error ? error.message : '网络错误'));
    } finally {
      setUploading(false);
    }
  };

  const handleOpenEdit = async (workflow: Workflow) => {
    setLoadingEdit(true);
    setEditingWorkflow(workflow);
    
    try {
      const res = await fetch(`${API_BASE}/workflows/${workflow.id}/`);
      const data = await res.json();
      if (data.success) {
        const wf = data.data;
        setEditForm({
          name: wf.name,
          description: wf.description || '',
          workflowJson: wf.workflowJson ? JSON.stringify(JSON.parse(wf.workflowJson), null, 2) : ''
        });
      }
    } catch (error) {
      console.error('加载工作流详情失败:', error);
      alert('加载工作流详情失败');
      setEditingWorkflow(null);
    } finally {
      setLoadingEdit(false);
    }
  };

  const handleDownload = async (workflow: Workflow) => {
    try {
      const res = await fetch(`${API_BASE}/workflows/${workflow.id}/`);
      const data = await res.json();
      if (data.success) {
        const wf = data.data;
        const blob = new Blob([wf.workflowJson], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${wf.name}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    } catch (error) {
      console.error('下载失败:', error);
      alert('下载失败');
    }
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingWorkflow) return;
    
    setSavingEdit(true);
    
    try {
      // 验证 JSON 格式（如果是用户工作流且修改了 JSON）
      let payload: any = {
        name: editForm.name,
        description: editForm.description
      };
      
      if (!editingWorkflow.isSystem && editForm.workflowJson) {
        try {
          JSON.parse(editForm.workflowJson);
          payload.workflowJson = editForm.workflowJson;
        } catch {
          alert('JSON 格式错误，请检查工作流内容');
          setSavingEdit(false);
          return;
        }
      }
      
      const res = await fetch(`${API_BASE}/workflows/${editingWorkflow.id}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      const data = await res.json();
      if (res.ok) {
        setEditingWorkflow(null);
        fetchWorkflows();
      } else {
        alert(data.detail || '保存失败');
      }
    } catch (error) {
      console.error('保存失败:', error);
      alert('保存失败');
    } finally {
      setSavingEdit(false);
    }
  };

  const getWorkflowsByType = (type: 'character' | 'shot' | 'video') => {
    return workflows.filter(w => w.type === type);
  };

  const resolutions = [
    { value: '1920x1080', label: '1920x1080 (1080p)' },
    { value: '1280x720', label: '1280x720 (720p)' },
    { value: '3840x2160', label: '3840x2160 (4K)' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">系统配置</h1>
        <p className="mt-1 text-sm text-gray-500">
          配置 AI 服务和输出参数
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* AI 配置 */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">AI 服务配置</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                DeepSeek API 地址
              </label>
              <input
                type="url"
                value={formData.deepseekApiUrl}
                onChange={(e) => setFormData({ ...formData, deepseekApiUrl: e.target.value })}
                className="input-field mt-1"
                placeholder="https://api.deepseek.com"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">
                DeepSeek API Key
              </label>
              <div className="relative mt-1">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  value={formData.deepseekApiKey}
                  onChange={(e) => setFormData({ ...formData, deepseekApiKey: e.target.value })}
                  className="input-field pr-10"
                  placeholder="sk-..."
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-500"
                >
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                您的 API Key 仅存储在本地浏览器中
              </p>
            </div>
          </div>
        </div>

        {/* 输出配置 */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">输出配置</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                输出分辨率
              </label>
              <select
                value={formData.outputResolution}
                onChange={(e) => setFormData({ ...formData, outputResolution: e.target.value })}
                className="input-field mt-1"
              >
                {resolutions.map((res) => (
                  <option key={res.value} value={res.value}>{res.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">
                帧率 (FPS)
              </label>
              <input
                type="number"
                min="1"
                max="60"
                value={formData.outputFrameRate}
                onChange={(e) => setFormData({ ...formData, outputFrameRate: parseInt(e.target.value) })}
                className="input-field mt-1"
              />
            </div>
          </div>
        </div>

        {/* ComfyUI 工作流配置 */}
        <div className="card">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-purple-100 rounded-lg">
                <Server className="h-5 w-5 text-purple-600" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900">ComfyUI 工作流</h2>
                <p className="text-sm text-gray-500">管理 AI 生成工作流，支持系统预设和自定义上传</p>
              </div>
            </div>
          </div>

          {/* 服务器地址 */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              ComfyUI 服务器地址
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={formData.comfyUIHost}
                onChange={(e) => setFormData({ ...formData, comfyUIHost: e.target.value })}
                className="input-field flex-1"
                placeholder="http://localhost:8188"
              />
              <span className="inline-flex items-center px-3 py-2 rounded-lg text-sm font-medium bg-green-100 text-green-700">
                <CheckCircle className="h-4 w-4 mr-1" />
                已连接
              </span>
            </div>
          </div>

          {/* 工作流类型标签页 */}
          {(['character', 'shot', 'video'] as const).map((type) => {
            const Icon = typeIcons[type];
            const typeWorkflows = getWorkflowsByType(type);
            const activeWorkflow = typeWorkflows.find(w => w.isActive);
            
            return (
              <div key={type} className="mb-6">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div className={`p-1.5 rounded ${typeColors[type]}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <h3 className="font-medium text-gray-900">{typeNames[type]}</h3>
                    {activeWorkflow && (
                      <span className="text-xs text-gray-500">
                        当前: {activeWorkflow.name} {activeWorkflow.isSystem ? '(系统)' : '(自定义)'}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setUploadType(type);
                      setShowUploadModal(true);
                    }}
                    className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
                  >
                    <Plus className="h-4 w-4" />
                    上传工作流
                  </button>
                </div>
                
                {loadingWorkflows ? (
                  <div className="flex justify-center py-4">
                    <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                  </div>
                ) : typeWorkflows.length === 0 ? (
                  <p className="text-sm text-gray-500 py-2">暂无工作流</p>
                ) : (
                  <div className="space-y-2">
                    {typeWorkflows.map((workflow) => (
                      <div 
                        key={workflow.id} 
                        className={`flex items-center justify-between p-3 rounded-lg border ${
                          workflow.isActive 
                            ? 'border-primary-500 bg-primary-50' 
                            : 'border-gray-200 hover:border-gray-300 bg-white'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          {/* 单选按钮选择默认 */}
                          <button
                            type="button"
                            onClick={() => !workflow.isActive && handleSetDefault(workflow)}
                            className={`flex-shrink-0 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${
                              workflow.isActive 
                                ? 'border-primary-500 bg-primary-500' 
                                : 'border-gray-300 hover:border-primary-400'
                            }`}
                            title={workflow.isActive ? '当前默认' : '设为默认'}
                          >
                            {workflow.isActive && <div className="w-2 h-2 bg-white rounded-full" />}
                          </button>
                          
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="font-medium text-sm text-gray-900">{workflow.name}</p>
                              {workflow.isActive && (
                                <span className="text-xs px-1.5 py-0.5 rounded-full bg-primary-100 text-primary-700 font-medium">
                                  默认
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500">
                              {workflow.isSystem ? '系统预设' : '自定义'} 
                              {workflow.description && ` · ${workflow.description}`}
                            </p>
                          </div>
                        </div>
                        
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => handleDownload(workflow)}
                            className="p-1.5 text-gray-400 hover:text-green-600 hover:bg-green-100 rounded transition-colors"
                            title="下载工作流"
                          >
                            <Download className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(workflow)}
                            className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                            title={workflow.isSystem ? '查看' : '编辑'}
                          >
                            <Edit2 className="h-4 w-4" />
                          </button>
                          {!workflow.isSystem && (
                            <button
                              type="button"
                              onClick={() => handleDelete(workflow)}
                              className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-100 rounded transition-colors"
                              title="删除"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* 保存按钮 */}
        <div className="flex justify-end">
          <button type="submit" disabled={saving} className="btn-primary">
            {saving ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" />保存中...</>
            ) : saved ? (
              <><Save className="mr-2 h-4 w-4" />已保存</>
            ) : (
              <><Save className="mr-2 h-4 w-4" />保存配置</>
            )}
          </button>
        </div>
      </form>

      {/* 上传工作流弹窗 */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">
                上传{typeNames[uploadType]}工作流
              </h3>
              <button
                type="button"
                onClick={() => setShowUploadModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">工作流名称</label>
                <input
                  type="text"
                  required
                  value={uploadForm.name}
                  onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })}
                  className="input-field mt-1"
                  placeholder="例如：我的自定义人设工作流"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">描述（可选）</label>
                <textarea
                  rows={2}
                  value={uploadForm.description}
                  onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
                  className="input-field mt-1"
                  placeholder="工作流描述..."
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">工作流JSON文件</label>
                <div className="mt-1">
                  <label className="flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-md hover:border-primary-500 cursor-pointer">
                    <div className="space-y-1 text-center">
                      <Upload className="mx-auto h-8 w-8 text-gray-400" />
                      <div className="flex text-sm text-gray-600">
                        <span className="relative cursor-pointer bg-white rounded-md font-medium text-primary-600 hover:text-primary-500">
                          {uploadForm.file ? uploadForm.file.name : '选择文件'}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500">ComfyUI 导出的 JSON 工作流文件</p>
                    </div>
                    <input
                      type="file"
                      accept=".json"
                      className="sr-only"
                      onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files?.[0] || null })}
                    />
                  </label>
                </div>
              </div>
              
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowUploadModal(false)}
                  className="btn-secondary"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={uploading || !uploadForm.file}
                  className="btn-primary"
                >
                  {uploading ? (
                    <><Loader2 className="mr-2 h-4 w-4 animate-spin" />上传中...</>
                  ) : (
                    <><Upload className="mr-2 h-4 w-4" />上传</>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 编辑/查看工作流弹窗 */}
      {editingWorkflow && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-5xl max-h-[95vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">
                {editingWorkflow.isSystem ? '查看工作流' : '编辑工作流'}
                {editingWorkflow.isSystem && (
                  <span className="ml-2 text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">系统预设（只读）</span>
                )}
              </h3>
              <button
                type="button"
                onClick={() => setEditingWorkflow(null)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            {loadingEdit ? (
              <div className="flex justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
              </div>
            ) : (
              <form onSubmit={handleSaveEdit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700">工作流名称</label>
                  <input
                    type="text"
                    required
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    className="input-field mt-1"
                    placeholder="工作流名称"
                    readOnly={editingWorkflow.isSystem}
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700">描述</label>
                  <textarea
                    rows={2}
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    className="input-field mt-1"
                    placeholder="工作流描述..."
                    readOnly={editingWorkflow.isSystem}
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    工作流 JSON
                    {!editingWorkflow.isSystem && (
                      <span className="text-xs text-gray-500 ml-2">可编辑，请确保 JSON 格式正确</span>
                    )}
                  </label>
                  <JSONEditor
                    value={editForm.workflowJson}
                    onChange={(value) => setEditForm({ ...editForm, workflowJson: value })}
                    readOnly={editingWorkflow.isSystem}
                    height="60vh"
                  />
                </div>
                
                <div className="flex justify-end gap-3 mt-6">
                  <button
                    type="button"
                    onClick={() => setEditingWorkflow(null)}
                    className="btn-secondary"
                  >
                    {editingWorkflow.isSystem ? '关闭' : '取消'}
                  </button>
                  {!editingWorkflow.isSystem && (
                    <button
                      type="submit"
                      disabled={savingEdit}
                      className="btn-primary"
                    >
                      {savingEdit ? (
                        <><Loader2 className="mr-2 h-4 w-4 animate-spin" />保存中...</>
                      ) : (
                        <><Save className="mr-2 h-4 w-4" />保存</>
                      )}
                    </button>
                  )}
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
