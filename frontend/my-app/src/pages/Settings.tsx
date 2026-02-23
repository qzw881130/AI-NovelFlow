import { useState, useEffect, useRef } from 'react';
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
import { useTranslation } from '../stores/i18nStore';
import JSONEditor from '../components/JSONEditor';
import { toast } from '../stores/toastStore';
import type { LLMProvider, ProxyConfig, LLMModel } from '../types';

// 获取 Provider 显示名称（使用翻译键）
const getProviderDisplayName = (providerId: string, t: any): string => {
  const providerKeyMap: Record<string, string> = {
    'deepseek': 'systemSettings.providers.deepseek',
    'openai': 'systemSettings.providers.openai',
    'gemini': 'systemSettings.providers.gemini',
    'anthropic': 'systemSettings.providers.anthropic',
    'azure': 'systemSettings.providers.azure',
    'aliyun-bailian': 'systemSettings.providers.aliyunBailian',
    'ollama': 'systemSettings.providers.ollama',
    'custom': 'systemSettings.providers.custom',
  };
  const key = providerKeyMap[providerId];
  if (key) {
    return t(key, { defaultValue: providerId });
  }
  return providerId;
};

// 获取模型名称（使用翻译键）
const getModelName = (modelId: string, t: any): string => {
  const nameKeyMap: Record<string, string> = {
    // Alibaba
    'qwen-max': 'systemSettings.modelNames.qwenMax',
    'qwen-plus': 'systemSettings.modelNames.qwenPlus',
    'qwen-turbo': 'systemSettings.modelNames.qwenTurbo',
    'qwen-coder-plus': 'systemSettings.modelNames.qwenCoderPlus',
    'qwen-2.5-72b-instruct': 'systemSettings.modelNames.qwen25',
    // Custom
    'custom-model': 'systemSettings.modelNames.customModel',
  };
  const key = nameKeyMap[modelId];
  if (key) {
    return t(key, { defaultValue: '' });
  }
  return '';
};

// 获取模型描述（使用翻译键）
const getModelDescription = (modelId: string, t: any): string => {
  const descKeyMap: Record<string, string> = {
    // DeepSeek
    'deepseek-chat': 'systemSettings.modelDescriptions.deepseekDesc',
    'deepseek-coder': 'systemSettings.modelDescriptions.deepseekCoderDesc',
    'deepseek-reasoner': 'systemSettings.modelDescriptions.deepseekReasonerDesc',
    // OpenAI
    'gpt-4o': 'systemSettings.modelDescriptions.gpt4oDesc',
    'gpt-4o-mini': 'systemSettings.modelDescriptions.gpt4oMiniDesc',
    'gpt-4-turbo': 'systemSettings.modelDescriptions.gpt4TurboDesc',
    'gpt-3.5-turbo': 'systemSettings.modelDescriptions.gpt35TurboDesc',
    // Gemini
    'gemini-2.5-flash-preview-05-20': 'systemSettings.modelDescriptions.gemini25FlashPreviewDesc',
    'gemini-2.5-pro-preview-05-20': 'systemSettings.modelDescriptions.gemini25ProPreviewDesc',
    'gemini-2.0-flash': 'systemSettings.modelDescriptions.gemini20FlashDesc',
    'gemini-2.0-flash-lite': 'systemSettings.modelDescriptions.gemini20FlashLiteDesc',
    'gemini-2.0-pro-exp-02-05': 'systemSettings.modelDescriptions.gemini20ProExpDesc',
    // Claude
    'claude-3-5-sonnet-20241022': 'systemSettings.modelDescriptions.claude35SonnetDesc',
    'claude-3-opus-20240229': 'systemSettings.modelDescriptions.claude3OpusDesc',
    'claude-3-sonnet-20240229': 'systemSettings.modelDescriptions.claude3SonnetDesc',
    'claude-3-haiku-20240307': 'systemSettings.modelDescriptions.claude3HaikuDesc',
    // Azure
    'azure-gpt-4o': 'systemSettings.modelDescriptions.azureGpt4oDesc',
    'azure-gpt-4': 'systemSettings.modelDescriptions.azureGpt4Desc',
    'azure-gpt-35-turbo': 'systemSettings.modelDescriptions.azureGpt35TurboDesc',
    // Alibaba
    'qwen-max': 'systemSettings.modelDescriptions.qwenMaxDesc',
    'qwen-plus': 'systemSettings.modelDescriptions.qwenPlusDesc',
    'qwen-turbo': 'systemSettings.modelDescriptions.qwenTurboDesc',
    'qwen-coder-plus': 'systemSettings.modelDescriptions.qwenCoderPlusDesc',
    'qwen-2.5-72b-instruct': 'systemSettings.modelDescriptions.qwen25Desc',
    'deepseek-v3': 'systemSettings.modelDescriptions.deepseekV3AliDesc',
    'deepseek-r1': 'systemSettings.modelDescriptions.deepseekR1AliDesc',
    // Custom
    'custom-model': 'systemSettings.modelDescriptions.customModelDesc',
  };
  const key = descKeyMap[modelId];
  if (key) {
    return t(key, { defaultValue: '' });
  }
  return '';
};

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface Workflow {
  id: string;
  name: string;
  nameKey?: string;
  description?: string;
  descriptionKey?: string;
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

// 获取工作流类型名称
const getTypeNames = (t: any) => ({
  character: t('systemSettings.workflow.character'),
  shot: t('systemSettings.workflow.shot'),
  video: t('systemSettings.workflow.video'),
  transition: t('systemSettings.workflow.transition')
});

// 获取工作流显示名称（系统预设的使用翻译键）
const getWorkflowDisplayName = (workflow: Workflow, t: any): string => {
  if (workflow.isSystem && workflow.nameKey) {
    return t(workflow.nameKey, { defaultValue: workflow.name });
  }
  return workflow.name;
};

// 获取工作流显示描述（系统预设的使用翻译键）
const getWorkflowDisplayDescription = (workflow: Workflow, t: any): string => {
  if (workflow.isSystem && workflow.descriptionKey) {
    return t(workflow.descriptionKey, { defaultValue: workflow.description || '' });
  }
  return workflow.description || '';
};

// 检查工作流映射配置是否完整
const checkWorkflowMappingComplete = (workflow: Workflow): boolean => {
  if (!workflow.nodeMapping) return false;
  
  const mapping = workflow.nodeMapping;
  
  switch (workflow.type) {
    case 'character':
      return !!(
        mapping.prompt_node_id &&
        mapping.prompt_node_id !== 'auto' &&
        mapping.save_image_node_id &&
        mapping.save_image_node_id !== 'auto'
      );
    case 'shot':
      // 分镜生图类型需要特殊字段
      const shotMapping = mapping as any;
      return !!(
        mapping.prompt_node_id &&
        mapping.prompt_node_id !== 'auto' &&
        mapping.save_image_node_id &&
        mapping.save_image_node_id !== 'auto' &&
        mapping.width_node_id &&
        mapping.width_node_id !== 'auto' &&
        mapping.height_node_id &&
        mapping.height_node_id !== 'auto' &&
        shotMapping.reference_image_node_id &&
        shotMapping.reference_image_node_id !== 'auto'
      );
    case 'video':
      // 视频类型需要特殊字段
      const videoMapping = mapping as any;
      return !!(
        mapping.prompt_node_id &&
        mapping.prompt_node_id !== 'auto' &&
        videoMapping.video_save_node_id &&
        videoMapping.video_save_node_id !== 'auto' &&
        videoMapping.reference_image_node_id &&
        videoMapping.reference_image_node_id !== 'auto'
      );
    case 'transition':
      // 转场类型需要特殊字段
      const transitionMapping = mapping as any;
      return !!(
        transitionMapping.first_image_node_id &&
        transitionMapping.first_image_node_id !== 'auto' &&
        transitionMapping.last_image_node_id &&
        transitionMapping.last_image_node_id !== 'auto' &&
        transitionMapping.video_save_node_id &&
        transitionMapping.video_save_node_id !== 'auto' &&
        transitionMapping.frame_count_node_id &&
        transitionMapping.frame_count_node_id !== 'auto'
      );
    default:
      return false;
  }
};

export default function Settings() {
  const { t } = useTranslation();
  const config = useConfigStore();
  
  // 安全获取 config 值的辅助函数
  const getSafeConfig = () => ({
    llmProvider: config.llmProvider || 'deepseek',
    llmModel: config.llmModel || 'deepseek-chat',
    llmApiKey: config.llmApiKey || '',
    llmApiUrl: config.llmApiUrl || 'https://api.deepseek.com',
    llmMaxTokens: config.llmMaxTokens,
    llmTemperature: config.llmTemperature,
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
  const [uploadType, setUploadType] = useState<'character' | 'shot' | 'video' | 'transition'>('character');
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
  
  // 跟踪用户是否手动修改过表单
  const isUserModifiedRef = useRef(false);
  
  // 自定义 API 模型列表
  const [customModels, setCustomModels] = useState<LLMModel[]>([]);
  const [loadingCustomModels, setLoadingCustomModels] = useState(false);
  const [customModelsError, setCustomModelsError] = useState<string | null>(null);


  // 加载工作流
  useEffect(() => {
    fetchWorkflows();
  }, []);

  // 组件挂载时从后端加载配置
  useEffect(() => {
    const loadConfig = async () => {
      const backendConfig = await config.loadConfig();
      // 只有当用户未手动修改时才更新表单，避免覆盖用户输入
      if (!isUserModifiedRef.current && backendConfig) {
        // 直接使用后端返回的配置，而不是通过 config store
        setFormData({
          llmProvider: backendConfig.llmProvider || 'deepseek',
          llmModel: backendConfig.llmModel || 'deepseek-chat',
          llmApiKey: backendConfig.llmApiKey || '',
          llmApiUrl: backendConfig.llmApiUrl || 'https://api.deepseek.com',
          llmMaxTokens: backendConfig.llmMaxTokens,
          llmTemperature: backendConfig.llmTemperature,
          proxy: backendConfig.proxy || { enabled: false, httpProxy: '', httpsProxy: '' },
          comfyUIHost: backendConfig.comfyUIHost || 'http://localhost:8188',
        });
        
        // 如果是自定义 API 或 Ollama，尝试恢复模型列表
        if ((backendConfig.llmProvider === 'custom' || backendConfig.llmProvider === 'ollama') && backendConfig.llmModel) {
          // 将已保存的模型添加到 customModels 中
          setCustomModels([{
            id: backendConfig.llmModel,
            name: backendConfig.llmModel,
            description: '已保存的模型',
          }]);

        }
      }
    };
    loadConfig();
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
    
    // 先更新前端本地存储
    config.setConfig(formData);
    
    // 再发送到后端 API
    let success = false;
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
            maxTokens: formData.llmMaxTokens,
            temperature: formData.llmTemperature,
          },
          proxy: formData.proxy,
          comfyUIHost: formData.comfyUIHost,
        }),
      });
      
      if (res.ok) {
        success = true;
        // 保存成功后重置用户修改标记
        isUserModifiedRef.current = false;
      } else {
        const errorData = await res.json();
        console.error('保存配置到后端失败:', errorData);
        toast.error(t('systemSettings.configSaveFailed'));
      }
    } catch (error) {
      console.error('发送配置到后端失败:', error);
      toast.error(t('systemSettings.configSaveFailed'));
    }
    
    await new Promise(resolve => setTimeout(resolve, 500));
    setSaving(false);
    if (success) {
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    }
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
      toast.warning(t('promptConfig.systemDefault') + ' ' + t('common.delete') + t('common.failed'));
      return;
    }
    if (!confirm(t('promptConfig.confirmDelete', { name: t('systemSettings.workflow.title') }))) return;
    
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
      toast.warning(t('systemSettings.workflow.selectFile'));
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
        let errorMsg = t('systemSettings.workflow.upload') + t('common.failed');
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
      toast.error(t('systemSettings.workflow.upload') + t('common.failed') + ': ' + (error instanceof Error ? error.message : t('http.networkError')));
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
        // 如果是系统预设工作流且有翻译键，使用翻译后的值
        const displayName = wf.isSystem && wf.nameKey 
          ? t(wf.nameKey, { defaultValue: wf.name })
          : wf.name;
        const displayDescription = wf.isSystem && wf.descriptionKey
          ? t(wf.descriptionKey, { defaultValue: wf.description || '' })
          : wf.description || '';
        
        setEditForm({
          name: displayName,
          description: displayDescription,
          workflowJson: formattedJson
        });
      } else {
        toast.error(data.message || t('systemSettings.workflow.loadingFailed'));
        setEditingWorkflow(null);
      }
    } catch (error) {
      console.error('加载工作流详情失败:', error);
      toast.error(t('systemSettings.workflow.loadingFailed'));
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
                frameCountNodeId: mapping.frame_count_node_id || '',
                firstImageNodeId: '',
                lastImageNodeId: ''
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
            } else if (workflow.type === 'shot') {
              // 分镜生图类型 - 包含参考图片节点
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: mapping.save_image_node_id || '',
                widthNodeId: mapping.width_node_id || '',
                heightNodeId: mapping.height_node_id || '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                referenceImageNodeId: mapping.reference_image_node_id || '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: ''
              });
            } else {
              // 人设生图类型
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: mapping.save_image_node_id || '',
                widthNodeId: '',
                heightNodeId: '',
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
      } else if (mappingWorkflow.type === 'shot') {
        // 分镜生图类型 - 包含参考图片节点
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null,
          width_node_id: mappingForm.widthNodeId || null,
          height_node_id: mappingForm.heightNodeId || null,
          reference_image_node_id: mappingForm.referenceImageNodeId || null
        };
      } else {
        // 人设生图类型
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null
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
        toast.success(t('systemSettings.configSaved'));
      } else {
        toast.error(t('systemSettings.configSaveFailed'));
      }
    } catch (error) {
      console.error('保存映射配置失败:', error);
      toast.error(t('systemSettings.configSaveFailed'));
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
      toast.error(t('common.download') + t('common.failed'));
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
          toast.error('JSON ' + t('common.error') + ', ' + t('systemSettings.workflow.jsonEditableTip'));
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
        toast.success(t('systemSettings.configSaved'));
      } else {
        toast.error(data.detail || t('systemSettings.configSaveFailed'));
      }
    } catch (error) {
      console.error('保存失败:', error);
      toast.error(t('systemSettings.configSaveFailed'));
    } finally {
      setSavingEdit(false);
    }
  };

  const getWorkflowsByType = (type: 'character' | 'shot' | 'video' | 'transition') => {
    return workflows.filter(w => w.type === type);
  };

  // 获取当前厂商预设
  const currentPreset = LLM_PROVIDER_PRESETS.find(p => p.id === formData.llmProvider);
  
  // 获取当前厂商的模型列表（自定义 API 和 Ollama 使用动态获取的列表）
  const availableModels = (formData.llmProvider === 'custom' || formData.llmProvider === 'ollama') && customModels.length > 0
    ? customModels
    : currentPreset?.models || [];
  
  // 自动获取自定义 API 的模型列表（支持 Ollama 等）
  const fetchCustomModels = async () => {
    if (!formData.llmApiUrl) {
      setCustomModelsError('请先填写 API URL');
      return;
    }
    
    setLoadingCustomModels(true);
    setCustomModelsError(null);
    
    try {
      // 尝试 Ollama API 格式
      const ollamaUrl = formData.llmApiUrl.replace(/\/v1$/, '').replace(/\/$/, '') + '/api/tags';
      const res = await fetch(ollamaUrl, { 
        method: 'GET',
        headers: formData.llmApiKey ? { 'Authorization': `Bearer ${formData.llmApiKey}` } : {}
      });
      
      if (res.ok) {
        const data = await res.json();
        if (data.models && Array.isArray(data.models)) {
          const models: LLMModel[] = data.models.map((m: any) => ({
            id: m.name || m.model,
            name: m.name || m.model,
            description: `${m.details?.family || ''} ${m.details?.parameter_size || ''}`.trim() || '本地模型',
          }));
          setCustomModels(models);
          
          // 如果当前选中的模型不在列表中，自动选择第一个
          if (models.length > 0 && !models.find(m => m.id === formData.llmModel)) {
            setFormData(prev => ({ ...prev, llmModel: models[0].id }));
          }
          
          toast.success(`成功获取 ${models.length} 个模型`);
          return;
        }
      }
      
      // 尝试 OpenAI 兼容格式 /v1/models
      const openaiUrl = formData.llmApiUrl.replace(/\/$/, '') + '/models';
      const openaiRes = await fetch(openaiUrl, {
        headers: formData.llmApiKey ? { 'Authorization': `Bearer ${formData.llmApiKey}` } : {}
      });
      
      if (openaiRes.ok) {
        const data = await openaiRes.json();
        if (data.data && Array.isArray(data.data)) {
          const models: LLMModel[] = data.data.map((m: any) => ({
            id: m.id,
            name: m.id,
            description: m.object || 'API 模型',
          }));
          setCustomModels(models);
          
          if (models.length > 0 && !models.find(m => m.id === formData.llmModel)) {
            setFormData(prev => ({ ...prev, llmModel: models[0].id }));
          }
          
          toast.success(`成功获取 ${models.length} 个模型`);
          return;
        }
      }
      
      setCustomModelsError('无法自动获取模型列表，请检查 API URL 是否正确');
    } catch (error) {
      console.error('获取模型列表失败:', error);
      setCustomModelsError('获取模型列表失败：' + (error instanceof Error ? error.message : '网络错误'));
    } finally {
      setLoadingCustomModels(false);
    }
  };
  
  // 处理厂商切换
  const handleProviderChange = (provider: LLMProvider) => {
    isUserModifiedRef.current = true;
    const preset = LLM_PROVIDER_PRESETS.find(p => p.id === provider);
    setFormData({
      ...formData,
      llmProvider: provider,
      llmModel: preset?.models[0]?.id || '',
      llmApiUrl: preset?.defaultApiUrl || '',
    });
    // 清空自定义模型列表和手动输入状态
    if (provider !== 'custom' && provider !== 'ollama') {
      setCustomModels([]);
    }

  };
  
  // 处理代理配置更新
  const handleProxyChange = (updates: Partial<ProxyConfig>) => {
    isUserModifiedRef.current = true;
    setFormData({
      ...formData,
      proxy: { ...(formData.proxy || { enabled: false, httpProxy: '', httpsProxy: '' }), ...updates },
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('systemSettings.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {t('systemSettings.subtitle')}
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
              <h2 className="text-lg font-semibold text-gray-900">{t('systemSettings.llmConfig')}</h2>
              <p className="text-sm text-gray-500">{t('systemSettings.subtitle')}</p>
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
                {t('systemSettings.llmConfig')}
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
                {t('systemSettings.proxySettings')}
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
                {t('systemSettings.comfyUISettings')}
              </div>
            </button>
          </div>

          {/* LLM 配置面板 */}
          {activeTab === 'llm' && (
            <div className="space-y-6">
              {/* 厂商选择 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  {t('systemSettings.selectProvider')}
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
                        {getProviderDisplayName(preset.id, t).charAt(0)}
                      </div>
                      <div className="text-left">
                        <div className="text-sm font-medium">{getProviderDisplayName(preset.id, t)}</div>
                        <div className="text-xs text-gray-500">
                          {preset.models.length} {t('systemSettings.selectModel')}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* API 地址 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.apiUrl')}
                </label>
                <input
                  type="url"
                  value={formData.llmApiUrl}
                  onChange={(e) => { isUserModifiedRef.current = true; setFormData({ ...formData, llmApiUrl: e.target.value }); }}
                  className="input-field"
                  placeholder={getDefaultApiUrl(formData.llmProvider)}
                />
                {formData.llmProvider === 'azure' && (
                  <p className="mt-1 text-xs text-amber-600">
                    {t('systemSettings.apiUrl')}
                  </p>
                )}
              </div>

              {/* API Key */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                  {t('systemSettings.apiKey')}
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
                    onChange={(e) => { isUserModifiedRef.current = true; setFormData({ ...formData, llmApiKey: e.target.value }); }}
                    className="input-field pr-10"
                    placeholder={t('systemSettings.enterApiKey')}
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
                  {t('systemSettings.enterApiKey')}
                </p>
              </div>

              {/* 模型选择 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.selectModel')}
                  {/* 只有 Ollama 显示自动获取按钮 */}
                  {formData.llmProvider === 'ollama' && (
                    <button
                      type="button"
                      onClick={fetchCustomModels}
                      disabled={loadingCustomModels}
                      className="ml-2 text-xs text-blue-600 hover:text-blue-700 disabled:opacity-50"
                    >
                      {loadingCustomModels ? '获取中...' : '自动获取'}
                    </button>
                  )}
                </label>
                
                {/* 自定义 API 固定使用手动输入模型 */}
                {formData.llmProvider === 'custom' ? (
                  <input
                    type="text"
                    value={formData.llmModel}
                    onChange={(e) => {
                      isUserModifiedRef.current = true;
                      setFormData({ ...formData, llmModel: e.target.value });
                    }}
                    placeholder="输入模型名称，例如：glm-5:cloud"
                    className="input-field"
                  />
                ) : (
                  <select
                    value={formData.llmModel}
                    onChange={(e) => { isUserModifiedRef.current = true; setFormData({ ...formData, llmModel: e.target.value }); }}
                    className="input-field"
                  >
                    {availableModels.map((model) => {
                      const name = getModelName(model.id, t) || model.name;
                      const desc = getModelDescription(model.id, t);
                      return (
                        <option key={model.id} value={model.id}>
                          {name} {desc ? `- ${desc}` : ''}
                          {model.maxTokens ? ` (${(model.maxTokens / 1000).toFixed(0)}k tokens)` : ''}
                        </option>
                      );
                    })}
                  </select>
                )}
                {customModelsError && (
                  <p className="mt-1 text-xs text-red-600">{customModelsError}</p>
                )}
              </div>

              {/* 最大Token数配置 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.maxTokens')}
                </label>
                <input
                  type="number"
                  value={formData.llmMaxTokens || ''}
                  onChange={(e) => {
                    isUserModifiedRef.current = true;
                    const value = e.target.value ? parseInt(e.target.value) : undefined;
                    setFormData({ ...formData, llmMaxTokens: value });
                  }}
                  className="input-field"
                  placeholder="4000"
                  min="1"
                  max="128000"
                />
                <p className="mt-1 text-xs text-gray-500">
                  {t('systemSettings.maxTokensDesc')}
                </p>
              </div>

              {/* Temperature配置 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.temperature')}
                </label>
                <input
                  type="number"
                  step="0.1"
                  value={formData.llmTemperature || ''}
                  onChange={(e) => {
                    isUserModifiedRef.current = true;
                    setFormData({ ...formData, llmTemperature: e.target.value });
                  }}
                  className="input-field"
                  placeholder="0.7"
                  min="0"
                  max="2"
                />
                <p className="mt-1 text-xs text-gray-500">
                  {t('systemSettings.temperatureDesc')}
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
                  <h3 className="text-sm font-medium text-blue-900">{t('systemSettings.proxySettings')}</h3>
                  <p className="text-xs text-blue-700">
                    {t('systemSettings.subtitle')}
                  </p>
                </div>
              </div>

              {/* 启用代理开关 */}
              <div className="flex items-center justify-between p-4 border border-gray-200 rounded-lg">
                <div>
                  <label className="text-sm font-medium text-gray-700">{t('systemSettings.enableProxy')}</label>
                  <p className="text-xs text-gray-500">{t('systemSettings.proxySettings')}</p>
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
                  {t('systemSettings.httpProxy')}
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
                  {t('systemSettings.httpProxy')}
                </p>
              </div>

              {/* HTTPS 代理 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.httpsProxy')}
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
                  {t('systemSettings.httpsProxy')}
                </p>
              </div>
            </div>
          )}

          {/* ComfyUI 配置面板 */}
          {activeTab === 'comfyui' && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.comfyUIHost')}
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={formData.comfyUIHost}
                    onChange={(e) => { isUserModifiedRef.current = true; setFormData({ ...formData, comfyUIHost: e.target.value }); }}
                    className="input-field flex-1"
                    placeholder="http://localhost:8188"
                  />
                  <span className="inline-flex items-center px-3 py-2 rounded-lg text-sm font-medium bg-green-100 text-green-700">
                    <CheckCircle className="h-4 w-4 mr-1" />
                    {t('systemSettings.connectionSuccess')}
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
                <h2 className="text-lg font-semibold text-gray-900">{t('systemSettings.workflow.title')}</h2>
                <p className="text-sm text-gray-500">{t('systemSettings.workflow.subtitle')}</p>
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
                    <h3 className="font-medium text-gray-900">{getTypeNames(t)[type]}</h3>
                    {activeWorkflow && (
                      <span className="text-xs text-gray-500">
                        {t('systemSettings.workflow.current')}: {getWorkflowDisplayName(activeWorkflow, t)} {activeWorkflow.isSystem ? `(${t('systemSettings.workflow.system')})` : `(${t('systemSettings.workflow.custom')})`}
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
                    {t('systemSettings.workflow.uploadWorkflow')}
                  </button>
                </div>
                
                {loadingWorkflows ? (
                  <div className="flex justify-center py-4">
                    <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                  </div>
                ) : typeWorkflows.length === 0 ? (
                  <p className="text-sm text-gray-500 py-2">{t('systemSettings.workflow.noWorkflows')}</p>
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
                            title={workflow.isActive ? t('systemSettings.workflow.currentDefault') : t('systemSettings.workflow.setAsDefault')}
                          >
                            {workflow.isActive && <div className="w-2 h-2 bg-white rounded-full" />}
                          </button>
                          
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="font-medium text-sm text-gray-900">{getWorkflowDisplayName(workflow, t)}</p>
                              {workflow.isActive && (
                                <span className="text-xs px-1.5 py-0.5 rounded-full bg-primary-100 text-primary-700 font-medium">
                                  {t('systemSettings.workflow.default')}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500">
                              {workflow.isSystem ? t('systemSettings.workflow.systemPreset') : t('systemSettings.workflow.custom')} 
                              {workflow.description && ` · ${getWorkflowDisplayDescription(workflow, t)}`}
                            </p>
                          </div>
                        </div>
                        
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => handleOpenMapping(workflow)}
                            className={`p-1.5 rounded transition-colors relative ${
                              checkWorkflowMappingComplete(workflow)
                                ? 'text-gray-400 hover:text-purple-600 hover:bg-purple-100'
                                : 'text-amber-500 hover:text-amber-600 hover:bg-amber-100'
                            }`}
                            title={checkWorkflowMappingComplete(workflow) ? t('systemSettings.workflow.mappingConfig') : t('systemSettings.workflow.mappingConfigIncomplete')}
                          >
                            <Server className="h-4 w-4" />
                            {!checkWorkflowMappingComplete(workflow) && (
                              <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                                <span className="relative inline-flex rounded-full h-3 w-3 bg-amber-500 text-[8px] text-white items-center justify-center font-bold">!</span>
                              </span>
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownload(workflow)}
                            className="p-1.5 text-gray-400 hover:text-green-600 hover:bg-green-100 rounded transition-colors"
                            title={t('systemSettings.workflow.downloadWorkflow')}
                          >
                            <Download className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(workflow)}
                            className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                            title={workflow.isSystem ? t('systemSettings.workflow.view') : t('systemSettings.workflow.edit')}
                          >
                            <Edit2 className="h-4 w-4" />
                          </button>
                          {!workflow.isSystem && (
                            <button
                              type="button"
                              onClick={() => handleDelete(workflow)}
                              className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-100 rounded transition-colors"
                              title={t('common.delete')}
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
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t('systemSettings.saveConfig')}</>
            ) : saved ? (
              <><Save className="mr-2 h-4 w-4" />{t('systemSettings.configSaved')}</>
            ) : (
              <><Save className="mr-2 h-4 w-4" />{t('systemSettings.saveConfig')}</>
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
                {t('systemSettings.workflow.uploadTitle', { type: getTypeNames(t)[uploadType] })}
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
                <label className="block text-sm font-medium text-gray-700">{t('systemSettings.workflow.workflowName')}</label>
                <input
                  type="text"
                  required
                  value={uploadForm.name}
                  onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('systemSettings.workflow.workflowNamePlaceholder')}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('systemSettings.workflow.descriptionOptional')}</label>
                <textarea
                  rows={2}
                  value={uploadForm.description}
                  onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('systemSettings.workflow.descriptionPlaceholder')}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('systemSettings.workflow.workflowJsonFile')}</label>
                <div className="mt-1">
                  <label className="flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-md hover:border-primary-500 cursor-pointer">
                    <div className="space-y-1 text-center">
                      <Upload className="mx-auto h-8 w-8 text-gray-400" />
                      <div className="flex text-sm text-gray-600">
                        <span className="relative cursor-pointer bg-white rounded-md font-medium text-primary-600 hover:text-primary-500">
                          {uploadForm.file ? uploadForm.file.name : t('systemSettings.workflow.selectFile')}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500">{t('systemSettings.workflow.comfyUIJsonTip')}</p>
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
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  disabled={uploading || !uploadForm.file}
                  className="btn-primary"
                >
                  {uploading ? (
                    <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t('systemSettings.workflow.uploading')}</>
                  ) : (
                    <><Upload className="mr-2 h-4 w-4" />{t('systemSettings.workflow.upload')}</>
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
                {editingWorkflow.isSystem ? t('systemSettings.workflow.viewWorkflow') : t('systemSettings.workflow.editWorkflow')}
                {editingWorkflow.isSystem && (
                  <span className="ml-2 text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">{t('systemSettings.workflow.systemPresetReadonly')}</span>
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
                  <label className="block text-sm font-medium text-gray-700">{t('systemSettings.workflow.workflowName')}</label>
                  <input
                    type="text"
                    required
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    className="input-field mt-1"
                    placeholder={t('systemSettings.workflow.workflowName')}
                    readOnly={editingWorkflow.isSystem}
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700">{t('systemSettings.workflow.description')}</label>
                  <textarea
                    rows={2}
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    className="input-field mt-1"
                    placeholder={t('systemSettings.workflow.descriptionPlaceholder')}
                    readOnly={editingWorkflow.isSystem}
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('systemSettings.workflow.workflowJson')}
                    {!editingWorkflow.isSystem && (
                      <span className="text-xs text-gray-500 ml-2">{t('systemSettings.workflow.jsonEditableTip')}</span>
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
                    {editingWorkflow.isSystem ? t('systemSettings.workflow.close') : t('common.cancel')}
                  </button>
                  {!editingWorkflow.isSystem && (
                    <button
                      type="submit"
                      disabled={savingEdit}
                      className="btn-primary"
                    >
                      {savingEdit ? (
                        <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t('systemSettings.workflow.saving')}</>
                      ) : (
                        <><Save className="mr-2 h-4 w-4" />{t('common.save')}</>
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
                {t('systemSettings.workflow.mappingConfig')}
                <span className="ml-2 text-sm font-normal text-gray-500">{getWorkflowDisplayName(mappingWorkflow, t)}</span>
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
                    {t('systemSettings.workflow.promptInputNode')}
                  </label>
                  <select
                    value={mappingForm.promptNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, promptNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                    {t('systemSettings.workflow.promptInputNodeTip')}
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
                    {t('systemSettings.workflow.imageSaveNode')}
                  </label>
                  <select
                    value={mappingForm.saveImageNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, saveImageNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">{t('systemSettings.workflow.autoFind')}</option>
                    {availableNodes.saveImage.map((nodeId) => (
                      <option key={nodeId} value={nodeId}>
                        Node#{nodeId}-SaveImage
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    {t('systemSettings.workflow.imageSaveNodeTip')}
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
                    {t('systemSettings.workflow.widthNode')}
                  </label>
                  <select
                    value={mappingForm.widthNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, widthNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                    {t('systemSettings.workflow.widthNodeTip')}
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
                    {t('systemSettings.workflow.heightNode')}
                  </label>
                  <select
                    value={mappingForm.heightNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, heightNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                    {t('systemSettings.workflow.heightNodeTip')}
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

              {/* 参考图片节点 - 分镜生图和视频类型显示 */}
              {(mappingWorkflow?.type === 'shot' || mappingWorkflow?.type === 'video') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('systemSettings.workflow.referenceImageNode')}
                  </label>
                  <select
                    value={mappingForm.referenceImageNodeId}
                    onChange={(e) => setMappingForm({ ...mappingForm, referenceImageNodeId: e.target.value })}
                    className="input-field"
                  >
                    <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                    {t('systemSettings.workflow.referenceImageNodeTip')}
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
              )}

              {/* 视频工作流特有配置 */}
              {mappingWorkflow?.type === 'video' && (
                <>
                  {/* 提示词输入节点 - 视频工作流显示 CR Prompt Text */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      {t('systemSettings.workflow.promptInputNode')} (CR Prompt Text)
                    </label>
                    <select
                      value={mappingForm.promptNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, promptNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.promptInputNodeVideoTip')}
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
                      {t('systemSettings.workflow.videoSaveNode')}
                    </label>
                    <select
                      value={mappingForm.videoSaveNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, videoSaveNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.videoSaveNodeTip')}
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
                      {t('systemSettings.workflow.maxSideNode')}
                    </label>
                    <select
                      value={mappingForm.maxSideNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, maxSideNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.maxSideNodeTip')}
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

                  {/* 总帧数节点 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      {t('systemSettings.workflow.frameCountNode')}
                    </label>
                    <select
                      value={mappingForm.frameCountNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, frameCountNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.frameCountNodeTip')}
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
                      {t('systemSettings.workflow.firstImageNode')}
                    </label>
                    <select
                      value={mappingForm.firstImageNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, firstImageNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.firstImageNodeTip')}
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
                      {t('systemSettings.workflow.lastImageNode')}
                    </label>
                    <select
                      value={mappingForm.lastImageNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, lastImageNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.lastImageNodeTip')}
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
                      {t('systemSettings.workflow.videoSaveNode')}
                    </label>
                    <select
                      value={mappingForm.videoSaveNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, videoSaveNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.videoSaveNodeTip')}
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
                      {t('systemSettings.workflow.frameCountNode')}
                    </label>
                    <select
                      value={mappingForm.frameCountNodeId}
                      onChange={(e) => setMappingForm({ ...mappingForm, frameCountNodeId: e.target.value })}
                      className="input-field"
                    >
                      <option value="">{t('systemSettings.workflow.autoFind')}</option>
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
                      {t('systemSettings.workflow.frameCountNodeTip')}
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
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  disabled={savingMapping}
                  className="btn-primary"
                >
                  {savingMapping ? (
                    <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t('systemSettings.workflow.saving')}</>
                  ) : (
                    <><Save className="mr-2 h-4 w-4" />{t('common.save')}</>
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
