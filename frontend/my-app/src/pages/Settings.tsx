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
  Download,
  Bot,
  Globe,
  Network,
  HelpCircle
} from 'lucide-react';
import { useConfigStore, LLM_PROVIDER_PRESETS, getDefaultApiUrl, getDefaultModels, getApiKeyPlaceholder, getApiKeyHelp } from '../stores/configStore';
import JSONEditor from '../components/JSONEditor';
import { toast } from '../stores/toastStore';
import type { LLMProvider, ProxyConfig } from '../types';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface Workflow {
  id: string;
  name: string;
  description?: string;
  type: 'character' | 'shot' | 'video' | 'transition';
  typeName: string;
  isSystem: boolean;
  isActive: boolean;
  nodeMapping?: {
    prompt_node_id?: string;
    save_image_node_id?: string;
    width_node_id?: string;
    height_node_id?: string;
  };
}

const typeIcons = {
  character: User,
  shot: ImageIcon,
  video: Film,
  transition: Film
};

const typeColors = {
  character: 'bg-blue-100 text-blue-600',
  shot: 'bg-amber-100 text-amber-600',
  video: 'bg-pink-100 text-pink-600',
  transition: 'bg-purple-100 text-purple-600'
};

const typeNames = {
  character: '人设生成',
  shot: '分镜生图',
  video: '分镜生视频',
  transition: '分镜生转场视频'
};

export default function Settings() {
  const config = useConfigStore();
  
  // 安全获取 config 值的辅助函数
  const getSafeConfig = () => ({
    llmProvider: config.llmProvider || 'deepseek',
    llmModel: config.llmModel || 'deepseek-chat',
    llmApiKey: config.llmApiKey || '',
    llmApiUrl: config.llmApiUrl || 'https://api.deepseek.com',
    proxy: config.proxy || { enabled: false, httpProxy: '', httpsProxy: '' },
    comfyUIHost: config.comfyUIHost || 'http://localhost:8188',
  });
  
  const [formData, setFormData] = useState(getSafeConfig());
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [activeTab, setActiveTab] = useState<'llm' | 'proxy' | 'comfyui'>('llm');
  
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
  
  // 节点映射配置
  const [mappingWorkflow, setMappingWorkflow] = useState<Workflow | null>(null);
  const [mappingForm, setMappingForm] = useState({ 
    promptNodeId: '', 
    saveImageNodeId: '',
    widthNodeId: '',
    heightNodeId: '',
    // 视频工作流专用
    videoSaveNodeId: '',
    maxSideNodeId: '',
    referenceImageNodeId: '',
    frameCountNodeId: '',  // 总帧数节点
    // 转场视频专用
    firstImageNodeId: '',  // 首帧图节点
    lastImageNodeId: ''   // 尾帧图节点
  });
  const [availableNodes, setAvailableNodes] = useState<{
    clipTextEncode: string[], 
    saveImage: string[],
    easyInt: string[],
    crPromptText: string[],  // CR Prompt Text 节点
    vhsVideoCombine: string[],  // VHS_VideoCombine 节点
    loadImage: string[]  // LoadImage 节点
  }>({ 
    clipTextEncode: [], 
    saveImage: [], 
    easyInt: [],
    crPromptText: [],
    vhsVideoCombine: [],
    loadImage: []
  });
  const [workflowData, setWorkflowData] = useState<Record<string, any>>({});
  const [savingMapping, setSavingMapping] = useState(false);

  // 加载工作流
  useEffect(() => {
    fetchWorkflows();
  }, []);

  // 当 config 加载后，同步到 formData（只执行一次）
  useEffect(() => {
    // 延迟执行，确保 config 已从 localStorage 加载
    const timer = setTimeout(() => {
      setFormData(getSafeConfig());
    }, 100);
    return () => clearTimeout(timer);
  }, []);  // 只在组件挂载时执行一次

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
    
    // 先更新前端本地存储
    config.setConfig(formData);
    
    // 再发送到后端 API
    try {
      const res = await fetch(`${API_BASE}/config/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          llm: {
            provider: formData.llmProvider,
            model: formData.llmModel,
            apiKey: formData.llmApiKey,
            apiUrl: formData.llmApiUrl,
          },
          proxy: formData.proxy,
          comfyUIHost: formData.comfyUIHost,
        }),
      });
      
      if (!res.ok) {
        const errorData = await res.json();
        console.error('保存配置到后端失败:', errorData);
      }
    } catch (error) {
      console.error('发送配置到后端失败:', error);
    }
    
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
      toast.warning('系统预设工作流不能删除');
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
      toast.warning('请选择工作流文件');
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
        toast.error(errorMsg);
      }
    } catch (error) {
      console.error('上传失败:', error);
      toast.error('上传失败: ' + (error instanceof Error ? error.message : '网络错误'));
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
        // 安全地格式化 JSON
        let formattedJson = '';
        if (wf.workflowJson) {
          try {
            const parsed = JSON.parse(wf.workflowJson);
            formattedJson = JSON.stringify(parsed, null, 2);
          } catch (parseError) {
            console.error('JSON parse error:', parseError);
            formattedJson = wf.workflowJson; // 使用原始字符串
          }
        }
        setEditForm({
          name: wf.name,
          description: wf.description || '',
          workflowJson: formattedJson
        });
      } else {
        toast.error(data.message || '加载工作流详情失败');
        setEditingWorkflow(null);
      }
    } catch (error) {
      console.error('加载工作流详情失败:', error);
      toast.error('加载工作流详情失败');
      setEditingWorkflow(null);
    } finally {
      setLoadingEdit(false);
    }
  };
  
  const handleOpenMapping = async (workflow: Workflow) => {
    setMappingWorkflow(workflow);
    try {
      const res = await fetch(`${API_BASE}/workflows/${workflow.id}/`);
      const data = await res.json();
      if (data.success) {
        const mapping = data.data.nodeMapping || {};
        
        // 解析工作流 JSON，提取可用节点和描述
        const workflowJson = data.data.workflowJson;
        const nodeDescriptions: Record<string, string> = {};
        
        if (workflowJson) {
          try {
            const workflowObj = typeof workflowJson === 'string' ? JSON.parse(workflowJson) : workflowJson;
            setWorkflowData(workflowObj);
            
            const clipTextEncode: string[] = [];
            const saveImage: string[] = [];
            const easyInt: string[] = [];
            const crPromptText: string[] = [];
            const vhsVideoCombine: string[] = [];
            const loadImage: string[] = [];
            
            for (const [nodeId, node] of Object.entries(workflowObj)) {
              if (typeof node === 'object' && node !== null) {
                const classType = (node as any).class_type || '';
                const metaTitle = (node as any)._meta?.title || '';
                
                if (classType === 'CLIPTextEncode' || classType === 'CR Text') {
                  clipTextEncode.push(`${nodeId} (${classType})`);
                  nodeDescriptions[nodeId] = classType;
                } else if (classType === 'SaveImage') {
                  saveImage.push(nodeId);
                } else if (classType === 'easy int' || classType === 'JWInteger') {
                  easyInt.push(`${nodeId} (${metaTitle || classType})`);
                  nodeDescriptions[nodeId] = metaTitle || classType;
                } else if (classType === 'CR Prompt Text') {
                  crPromptText.push(`${nodeId} (${metaTitle || classType})`);
                  nodeDescriptions[nodeId] = metaTitle || classType;
                } else if (classType === 'VHS_VideoCombine') {
                  vhsVideoCombine.push(`${nodeId} (${metaTitle || classType})`);
                  nodeDescriptions[nodeId] = metaTitle || classType;
                } else if (classType === 'LoadImage') {
                  loadImage.push(`${nodeId} (${metaTitle || classType})`);
                  nodeDescriptions[nodeId] = metaTitle || classType;
                }
              }
            }
            
            setAvailableNodes({ clipTextEncode, saveImage, easyInt, crPromptText, vhsVideoCombine, loadImage });
            
            // 根据工作流类型设置表单值
            if (workflow.type === 'video') {
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: mapping.video_save_node_id || '',
                maxSideNodeId: mapping.max_side_node_id || '',
                referenceImageNodeId: mapping.reference_image_node_id || '',
                frameCountNodeId: mapping.frame_count_node_id || ''
              });
            } else if (workflow.type === 'transition') {
              setMappingForm({
                promptNodeId: '',
                saveImageNodeId: '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: mapping.video_save_node_id || '',
                maxSideNodeId: '',
                referenceImageNodeId: '',
                frameCountNodeId: mapping.frame_count_node_id || '',
                firstImageNodeId: mapping.first_image_node_id || '',
                lastImageNodeId: mapping.last_image_node_id || ''
              });
            } else {
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: mapping.save_image_node_id || '',
                widthNodeId: mapping.width_node_id || '',
                heightNodeId: mapping.height_node_id || '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                referenceImageNodeId: '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: ''
              });
            }
          } catch (e) {
            console.error('解析工作流 JSON 失败:', e);
            setAvailableNodes({ clipTextEncode: [], saveImage: [], easyInt: [], crPromptText: [], vhsVideoCombine: [], loadImage: [] });
            setWorkflowData({});
          }
        }
      }
    } catch (error) {
      console.error('加载工作流映射失败:', error);
    }
  };
  
  const handleSaveMapping = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mappingWorkflow) return;
    
    setSavingMapping(true);
    try {
      // 根据工作流类型构建不同的 nodeMapping
      let nodeMapping: Record<string, string | null> = {};
      
      if (mappingWorkflow.type === 'video') {
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          video_save_node_id: mappingForm.videoSaveNodeId || null,
          max_side_node_id: mappingForm.maxSideNodeId || null,
          reference_image_node_id: mappingForm.referenceImageNodeId || null,
          frame_count_node_id: mappingForm.frameCountNodeId || null
        };
      } else if (mappingWorkflow.type === 'transition') {
        nodeMapping = {
          first_image_node_id: mappingForm.firstImageNodeId || null,
          last_image_node_id: mappingForm.lastImageNodeId || null,
          frame_count_node_id: mappingForm.frameCountNodeId || null,
          video_save_node_id: mappingForm.videoSaveNodeId || null
        };
      } else {
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null,
          width_node_id: mappingForm.widthNodeId || null,
          height_node_id: mappingForm.heightNodeId || null
        };
      }
      
      const res = await fetch(`${API_BASE}/workflows/${mappingWorkflow.id}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nodeMapping })
      });
      
      if (res.ok) {
        setMappingWorkflow(null);
        fetchWorkflows();
        toast.success('保存映射配置成功');
      } else {
        toast.error('保存映射配置失败');
      }
    } catch (error) {
      console.error('保存映射配置失败:', error);
      toast.error('保存失败');
    } finally {
      setSavingMapping(false);
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
      toast.error('下载失败');
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
          toast.error('JSON 格式错误，请检查工作流内容');
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
        toast.success('保存成功');
      } else {
        toast.error(data.detail || '保存失败');
      }
    } catch (error) {
      console.error('保存失败:', error);
      toast.error('保存失败');
    } finally {
      setSavingEdit(false);
    }
  };

  const getWorkflowsByType = (type: 'character' | 'shot' | 'video' | 'transition') => {
    return workflows.filter(w => w.type === type);
  };

  // 获取当前厂商预设
  const currentPreset = LLM_PROVIDER_PRESETS.find(p => p.id === formData.llmProvider);
  
  // 获取当前厂商的模型列表
  const availableModels = currentPreset?.models || [];
  
  // 处理厂商切换
  const handleProviderChange = (provider: LLMProvider) => {
    const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
    setFormData({
      ...formData,
      llmProvider: provider,
      llmModel: preset?.models[0]?.id || '',
      llmApiUrl: preset?.defaultApiUrl || '',
    });
  };
  
  // 处理代理配置更新
  const handleProxyChange = (updates: Partial<ProxyConfig>) => {
    setFormData({
      ...formData,
      proxy: { ...(formData.proxy || { enabled: false, httpProxy: '', httpsProxy: '' }), ...updates },
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">系统配置</h1>
        <p className="mt-1 text-sm text-gray-500">
          配置 AI 服务和输出参数
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* AI 服务配置 - 标签页 */}
        <div className="card">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-100 rounded-lg">
              <Bot className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">AI 服务配置</h2>
              <p className="text-sm text-gray-500">配置 LLM 提供商和代理设置</p>
            </div>
          </div>
          
          {/* 标签页导航 */}
          <div className="flex border-b border-gray-200 mb-6">
            <button
              type="button"
              onClick={() => setActiveTab('llm')}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'llm'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <div className="flex items-center gap-2">
                <Bot className="h-4 w-4" />
                LLM 配置
              </div>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('proxy')}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'proxy'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <div className="flex items-center gap-2">
                <Network className="h-4 w-4" />
                代理配置
              </div>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('comfyui')}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'comfyui'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4" />
                ComfyUI
              </div>
            </button>
          </div>

          {/* LLM 配置面板 */}
          {activeTab === 'llm' && (
            <div className="space-y-6">
              {/* 厂商选择 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  选择 LLM 厂商
                </label>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {LLM_PROVIDER_PRESETS.map((preset) => (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => handleProviderChange(preset.id)}
                      className={`flex items-center gap-3 p-3 rounded-lg border-2 transition-all ${
                        formData.llmProvider === preset.id
                          ? 'border-blue-500 bg-blue-50 text-blue-700'
                          : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                        formData.llmProvider === preset.id
                          ? 'bg-blue-500 text-white'
                          : 'bg-gray-200 text-gray-600'
                      }`}>
                        {preset.name.charAt(0)}
                      </div>
                      <div className="text-left">
                        <div className="text-sm font-medium">{preset.name}</div>
                        <div className="text-xs text-gray-500">
                          {preset.models.length} 个模型
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* 模型选择 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  选择模型
                </label>
                <select
                  value={formData.llmModel}
                  onChange={(e) => setFormData({ ...formData, llmModel: e.target.value })}
                  className="input-field"
                >
                  {availableModels.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name} {model.description ? `- ${model.description}` : ''}
                      {model.maxTokens ? ` (${(model.maxTokens / 1000).toFixed(0)}k tokens)` : ''}
                    </option>
                  ))}
                </select>
              </div>

              {/* API 地址 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  API 地址
                </label>
                <input
                  type="url"
                  value={formData.llmApiUrl}
                  onChange={(e) => setFormData({ ...formData, llmApiUrl: e.target.value })}
                  className="input-field"
                  placeholder={getDefaultApiUrl(formData.llmProvider)}
                />
                {formData.llmProvider === 'azure' && (
                  <p className="mt-1 text-xs text-amber-600">
                    Azure 需要填写完整的 Deployment URL
                  </p>
                )}
              </div>

              {/* API Key */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                  API Key
                  {getApiKeyHelp(formData.llmProvider) && (
                    <span className="text-xs text-gray-400 font-normal">
                      ({getApiKeyHelp(formData.llmProvider)})
                    </span>
                  )}
                </label>
                <div className="relative">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    value={formData.llmApiKey}
                    onChange={(e) => setFormData({ ...formData, llmApiKey: e.target.value })}
                    className="input-field pr-10"
                    placeholder={getApiKeyPlaceholder(formData.llmProvider)}
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
                  API Key 将加密存储到服务器数据库中，重启后仍然有效
                </p>
              </div>
            </div>
          )}

          {/* 代理配置面板 */}
          {activeTab === 'proxy' && (
            <div className="space-y-6">
              <div className="flex items-center gap-3 p-4 bg-blue-50 rounded-lg">
                <Network className="h-5 w-5 text-blue-600" />
                <div>
                  <h3 className="text-sm font-medium text-blue-900">代理设置</h3>
                  <p className="text-xs text-blue-700">
                    配置代理以访问需要翻墙的 API 服务（如 OpenAI、Anthropic 等）
                  </p>
                </div>
              </div>

              {/* 启用代理开关 */}
              <div className="flex items-center justify-between p-4 border border-gray-200 rounded-lg">
                <div>
                  <label className="text-sm font-medium text-gray-700">启用代理</label>
                  <p className="text-xs text-gray-500">开启后所有 LLM 请求将通过代理发送</p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formData.proxy?.enabled || false}
                    onChange={(e) => handleProxyChange({ enabled: e.target.checked })}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>

              {/* HTTP 代理 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  HTTP 代理地址
                </label>
                <input
                  type="text"
                  value={formData.proxy?.httpProxy || ''}
                  onChange={(e) => handleProxyChange({ httpProxy: e.target.value })}
                  className="input-field"
                  placeholder="http://127.0.0.1:7890"
                  disabled={!formData.proxy?.enabled}
                />
                <p className="mt-1 text-xs text-gray-500">
                  例如: http://127.0.0.1:7890 或 socks5://127.0.0.1:1080
                </p>
              </div>

              {/* HTTPS 代理 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  HTTPS 代理地址
                </label>
                <input
                  type="text"
                  value={formData.proxy?.httpsProxy || ''}
                  onChange={(e) => handleProxyChange({ httpsProxy: e.target.value })}
                  className="input-field"
                  placeholder="http://127.0.0.1:7890"
                  disabled={!formData.proxy?.enabled}
                />
                <p className="mt-1 text-xs text-gray-500">
                  通常与 HTTP 代理相同，留空则使用 HTTP 代理
                </p>
              </div>
            </div>
          )}

          {/* ComfyUI 配置面板 */}
          {activeTab === 'comfyui' && (
            <div className="space-y-6">
              <div>
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
            </div>
          )}
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

          {/* 工作流类型标签页 */}
          {(['character', 'shot', 'video', 'transition'] as const).map((type) => {
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
                            onClick={() => handleOpenMapping(workflow)}
                            className="p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-100 rounded transition-colors"
                            title="映射配置"
                          >
                            <Server className="h-4 w-4" />
                          </button>
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

      {/* 节点映射配置弹窗 */}
      {mappingWorkflow && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">
                映射配置
                <span className="ml-2 text-sm font-normal text-gray-500">{mappingWorkflow.name}</span>
              </h3>
              <button
                type="button"
                onClick={() => setMappingWorkflow(null)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <form onSubmit={handleSaveMapping} className="space-y-6">
              {/* 提示词输入节点 - 人设和分镜生图工作流显示 */}
              {(mappingWorkflow?.type === 'character' || mappingWorkflow?.type === 'shot') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    提示词输入节点
                  </label>
                  <select
                    value={mappingForm.promptNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, promptNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">自动查找 (Auto)</option>
                    {availableNodes.clipTextEncode.map((nodeInfo) => {
                      const nodeId = nodeInfo.split(' ')[0];
                      return (
                        <option key={nodeInfo} value={nodeId}>
                          Node#{nodeInfo}
                        </option>
                      );
                    })}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    选择用于注入角色提示词的 CLIPTextEncode 节点，留空则自动查找
                  </p>
                  
                  {/* Node JSON Preview */}
                  {mappingForm.promptNodeId && workflowData[mappingForm.promptNodeId] && (
                    <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                      <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.promptNodeId} JSON Preview:</p>
                      <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.promptNodeId]: workflowData[mappingForm.promptNodeId] }, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
              
              {/* 图片保存节点 - 人设和分镜生图工作流显示 */}
              {(mappingWorkflow?.type === 'character' || mappingWorkflow?.type === 'shot') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    图片保存节点
                  </label>
                  <select
                    value={mappingForm.saveImageNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, saveImageNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">自动查找 (Auto)</option>
                    {availableNodes.saveImage.map((nodeId) => (
                      <option key={nodeId} value={nodeId}>
                        Node#{nodeId}-SaveImage
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    选择用于保存生成图片的 SaveImage 节点，留空则自动查找
                  </p>
                  
                  {/* Node JSON Preview */}
                  {mappingForm.saveImageNodeId && workflowData[mappingForm.saveImageNodeId] && (
                    <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                      <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.saveImageNodeId} JSON Preview:</p>
                      <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.saveImageNodeId]: workflowData[mappingForm.saveImageNodeId] }, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* 宽度节点 - 仅分镜生图类型显示 */}
              {mappingWorkflow?.type === 'shot' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    宽度节点 (Width)
                  </label>
                  <select
                    value={mappingForm.widthNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, widthNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">自动查找 (Auto)</option>
                    {availableNodes.easyInt
                      .filter(node => node.includes('Width'))
                      .map((nodeInfo) => {
                        const nodeId = nodeInfo.split(' ')[0];
                        return (
                          <option key={nodeInfo} value={nodeId}>
                            Node#{nodeInfo}
                          </option>
                        );
                      })}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    选择用于设置生成图片宽度的 easy int 节点 (Width)
                  </p>
                  
                  {/* Node JSON Preview */}
                  {mappingForm.widthNodeId && workflowData[mappingForm.widthNodeId] && (
                    <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                      <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.widthNodeId} JSON Preview:</p>
                      <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.widthNodeId]: workflowData[mappingForm.widthNodeId] }, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* 高度节点 - 仅分镜生图类型显示 */}
              {mappingWorkflow?.type === 'shot' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    高度节点 (Height)
                  </label>
                  <select
                    value={mappingForm.heightNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, heightNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">自动查找 (Auto)</option>
                    {availableNodes.easyInt
                      .filter(node => node.includes('Height'))
                      .map((nodeInfo) => {
                        const nodeId = nodeInfo.split(' ')[0];
                        return (
                          <option key={nodeInfo} value={nodeId}>
                            Node#{nodeInfo}
                          </option>
                        );
                      })}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    选择用于设置生成图片高度的 easy int 节点 (Height)
                  </p>
                  
                  {/* Node JSON Preview */}
                  {mappingForm.heightNodeId && workflowData[mappingForm.heightNodeId] && (
                    <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                      <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.heightNodeId} JSON Preview:</p>
                      <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.heightNodeId]: workflowData[mappingForm.heightNodeId] }, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* 视频工作流特有配置 */}
              {mappingWorkflow?.type === 'video' && (
                <>
                  {/* 提示词输入节点 - 视频工作流显示 CR Prompt Text */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      提示词输入节点 (CR Prompt Text)
                    </label>
                    <select
                      value={mappingForm.promptNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, promptNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.crPromptText.map((nodeInfo) => {
                        const nodeId = nodeInfo.split(' ')[0];
                        return (
                          <option key={nodeInfo} value={nodeId}>
                            Node#{nodeInfo}
                          </option>
                        );
                      })}
                      {/* 也显示 CLIPTextEncode 作为备选 */}
                      {availableNodes.clipTextEncode.map((nodeInfo) => {
                        const nodeId = nodeInfo.split(' ')[0];
                        return (
                          <option key={nodeInfo} value={nodeId}>
                            Node#{nodeInfo}
                          </option>
                        );
                      })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于输入视频提示词的 CR Prompt Text 或 CLIPTextEncode 节点
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.promptNodeId && workflowData[mappingForm.promptNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.promptNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.promptNodeId]: workflowData[mappingForm.promptNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  {/* 视频保存节点 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      视频保存节点 (VHS_VideoCombine)
                    </label>
                    <select
                      value={mappingForm.videoSaveNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, videoSaveNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.vhsVideoCombine.map((nodeInfo) => {
                        const nodeId = nodeInfo.split(' ')[0];
                        return (
                          <option key={nodeInfo} value={nodeId}>
                            Node#{nodeInfo}
                          </option>
                        );
                      })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于保存生成视频的 VHS_VideoCombine 节点
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.videoSaveNodeId && workflowData[mappingForm.videoSaveNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.videoSaveNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.videoSaveNodeId]: workflowData[mappingForm.videoSaveNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  {/* 最长边节点 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      最长边节点 (easy int - 最长边)
                    </label>
                    <select
                      value={mappingForm.maxSideNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, maxSideNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.easyInt
                        .filter(node => node.includes('最长边'))
                        .map((nodeInfo) => {
                          const nodeId = nodeInfo.split(' ')[0];
                          return (
                            <option key={nodeInfo} value={nodeId}>
                              Node#{nodeInfo}
                            </option>
                          );
                        })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于设置视频最长边的 easy int 节点
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.maxSideNodeId && workflowData[mappingForm.maxSideNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.maxSideNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.maxSideNodeId]: workflowData[mappingForm.maxSideNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  {/* 参考图片节点 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      参考图片节点 (LoadImage)
                    </label>
                    <select
                      value={mappingForm.referenceImageNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, referenceImageNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.loadImage.map((nodeInfo) => {
                        const nodeId = nodeInfo.split(' ')[0];
                        return (
                          <option key={nodeInfo} value={nodeId}>
                            Node#{nodeInfo}
                          </option>
                        );
                      })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于加载参考图片（分镜图）的 LoadImage 节点
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.referenceImageNodeId && workflowData[mappingForm.referenceImageNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.referenceImageNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.referenceImageNodeId]: workflowData[mappingForm.referenceImageNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  {/* 总帧数节点 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      总帧数节点 (easy int - 总帧数)
                    </label>
                    <select
                      value={mappingForm.frameCountNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, frameCountNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.easyInt
                        .filter(node => node.includes('总帧数') || node.includes('frame') || node.includes('Frame'))
                        .map((nodeInfo) => {
                          const nodeId = nodeInfo.split(' ')[0];
                          return (
                            <option key={nodeInfo} value={nodeId}>
                              Node#{nodeInfo}
                            </option>
                          );
                        })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于设置视频总帧数的 easy int 节点（值应为 8 的倍数 + 1）
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.frameCountNodeId && workflowData[mappingForm.frameCountNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.frameCountNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.frameCountNodeId]: workflowData[mappingForm.frameCountNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* 转场视频工作流特有配置 */}
              {mappingWorkflow?.type === 'transition' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      首帧图节点 (LoadImage - First IMG)
                    </label>
                    <select
                      value={mappingForm.firstImageNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, firstImageNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.loadImage
                        .filter(node => node.includes('First') || node.includes('first') || node.includes('首帧'))
                        .map((nodeInfo) => {
                          const nodeId = nodeInfo.split(' ')[0];
                          return (
                            <option key={nodeInfo} value={nodeId}>
                              Node#{nodeInfo}
                            </option>
                          );
                        })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于输入首帧图片的 LoadImage 节点
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.firstImageNodeId && workflowData[mappingForm.firstImageNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.firstImageNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.firstImageNodeId]: workflowData[mappingForm.firstImageNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      尾帧图节点 (LoadImage - End IMG)
                    </label>
                    <select
                      value={mappingForm.lastImageNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, lastImageNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.loadImage
                        .filter(node => node.includes('End') || node.includes('end') || node.includes('尾帧'))
                        .map((nodeInfo) => {
                          const nodeId = nodeInfo.split(' ')[0];
                          return (
                            <option key={nodeInfo} value={nodeId}>
                              Node#{nodeInfo}
                            </option>
                          );
                        })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于输入尾帧图片的 LoadImage 节点
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.lastImageNodeId && workflowData[mappingForm.lastImageNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.lastImageNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.lastImageNodeId]: workflowData[mappingForm.lastImageNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      视频保存节点 (VHS_VideoCombine)
                    </label>
                    <select
                      value={mappingForm.videoSaveNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, videoSaveNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.vhsVideoCombine.map((nodeInfo) => {
                        const nodeId = nodeInfo.split(' ')[0];
                        return (
                          <option key={nodeInfo} value={nodeId}>
                            Node#{nodeInfo}
                          </option>
                        );
                      })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于保存生成视频的 VHS_VideoCombine 节点
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.videoSaveNodeId && workflowData[mappingForm.videoSaveNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.videoSaveNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.videoSaveNodeId]: workflowData[mappingForm.videoSaveNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      总帧数节点 (JWInteger)
                    </label>
                    <select
                      value={mappingForm.frameCountNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, frameCountNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">自动查找 (Auto)</option>
                      {availableNodes.easyInt
                        .filter(node => node.includes('总帧数') || node.includes('frame') || node.includes('Frame'))
                        .map((nodeInfo) => {
                          const nodeId = nodeInfo.split(' ')[0];
                          return (
                            <option key={nodeInfo} value={nodeId}>
                              Node#{nodeInfo}
                            </option>
                          );
                        })}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      选择用于设置视频总帧数的节点（值应为 8 的倍数 + 1）
                    </p>
                    
                    {/* Node JSON Preview */}
                    {mappingForm.frameCountNodeId && workflowData[mappingForm.frameCountNodeId] && (
                      <div className="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
                        <p className="text-xs text-gray-400 mb-1">Node #{mappingForm.frameCountNodeId} JSON Preview:</p>
                        <pre className="text-xs text-gray-600 overflow-x-auto">
{JSON.stringify({ [mappingForm.frameCountNodeId]: workflowData[mappingForm.frameCountNodeId] }, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </>
              )}
              
              <div className="flex justify-end gap-3 pt-4 border-t">
                <button
                  type="button"
                  onClick={() => setMappingWorkflow(null)}
                  className="btn-secondary"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={savingMapping}
                  className="btn-primary"
                >
                  {savingMapping ? (
                    <><Loader2 className="mr-2 h-4 w-4 animate-spin" />保存中...</>
                  ) : (
                    <><Save className="mr-2 h-4 w-4" />保存</>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
