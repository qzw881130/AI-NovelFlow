// 工作流管理组件

import { useState, useEffect } from 'react';
import { 
  Upload, Edit2, Star, Trash2, Download, Plus, Check, 
  User, Image as ImageIcon, Film, Mountain, CheckCircle,
  Settings as SettingsIcon
} from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { toast } from '../../stores/toastStore';
import JSONEditor from '../../components/JSONEditor';
import { 
  getWorkflowDisplayName, 
  getWorkflowDisplayDescription, 
  getTypeNames,
  checkWorkflowMappingComplete 
} from './utils';
import type { Workflow, MappingForm, AvailableNodes } from './types';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

const typeIcons = {
  character: User,
  scene: Mountain,
  shot: ImageIcon,
  video: Film,
  transition: Film
};

const typeColors = {
  character: 'bg-blue-100 text-blue-600',
  scene: 'bg-green-100 text-green-600',
  shot: 'bg-amber-100 text-amber-600',
  video: 'bg-pink-100 text-pink-600',
  transition: 'bg-purple-100 text-purple-600'
};

interface WorkflowManagerProps {
  onRefresh?: () => void;
}

export default function WorkflowManager({ onRefresh }: WorkflowManagerProps) {
  const { t } = useTranslation();
  
  // 工作流列表
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);
  
  // 上传弹窗
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadType, setUploadType] = useState<'character' | 'scene' | 'shot' | 'video' | 'transition'>('character');
  const [uploadForm, setUploadForm] = useState({ name: '', description: '', file: null as File | null });
  const [uploading, setUploading] = useState(false);
  
  // 编辑弹窗
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [editForm, setEditForm] = useState({ name: '', description: '', workflowJson: '' });
  const [loadingEdit, setLoadingEdit] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  
  // 映射配置弹窗
  const [mappingWorkflow, setMappingWorkflow] = useState<Workflow | null>(null);
  const [mappingForm, setMappingForm] = useState<MappingForm>({
    promptNodeId: '', 
    saveImageNodeId: '',
    widthNodeId: '',
    heightNodeId: '',
    videoSaveNodeId: '',
    maxSideNodeId: '',
    referenceImageNodeId: '',
    frameCountNodeId: '',
    firstImageNodeId: '',
    lastImageNodeId: '',
    characterReferenceImageNodeId: '',
    sceneReferenceImageNodeId: ''
  });
  const [availableNodes, setAvailableNodes] = useState<AvailableNodes>({ 
    clipTextEncode: [], 
    saveImage: [], 
    easyInt: [],
    crPromptText: [],
    vhsVideoCombine: [],
    loadImage: []
  });
  const [workflowJsonData, setWorkflowJsonData] = useState<Record<string, any>>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string>('');
  const [savingMapping, setSavingMapping] = useState(false);

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

  const handleSetDefault = async (workflow: Workflow) => {
    try {
      const res = await fetch(`${API_BASE}/workflows/${workflow.id}/set-default/`, {
        method: 'POST'
      });
      if (res.ok) {
        fetchWorkflows();
        toast.success(t('systemSettings.workflow.setDefaultSuccess', { name: getWorkflowDisplayName(workflow, t) }));
      } else {
        toast.error(t('systemSettings.workflow.setDefaultFailed'));
      }
    } catch (error) {
      console.error('设置默认工作流失败:', error);
      toast.error(t('systemSettings.workflow.setDefaultFailed'));
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
    e.stopPropagation(); // 防止触发外部表单提交
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
        let errorMsg = t('systemSettings.workflow.upload') + t('common.failed');
        if (data.detail) {
          if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          } else if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map((e: any) => e.msg || e).join(', ');
          }
        }
        toast.error(errorMsg);
      }
    } catch (error) {
      console.error('上传失败:', error);
      toast.error(t('systemSettings.workflow.upload') + t('common.failed'));
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
        let formattedJson = '';
        if (wf.workflowJson) {
          try {
            const parsed = JSON.parse(wf.workflowJson);
            formattedJson = JSON.stringify(parsed, null, 2);
          } catch {
            formattedJson = wf.workflowJson;
          }
        }
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

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    e.stopPropagation(); // 防止触发外部表单提交
    if (!editingWorkflow) return;
    
    setSavingEdit(true);
    
    try {
      let payload: any = {
        name: editForm.name,
        description: editForm.description
      };
      
      if (!editingWorkflow.isSystem && editForm.workflowJson) {
        try {
          JSON.parse(editForm.workflowJson);
          payload.workflowJson = editForm.workflowJson;
        } catch {
          toast.error('JSON ' + t('common.error'));
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

  const handleOpenMapping = async (workflow: Workflow) => {
    setMappingWorkflow(workflow);
    try {
      const res = await fetch(`${API_BASE}/workflows/${workflow.id}/`);
      const data = await res.json();
      if (data.success) {
        const mapping = data.data.nodeMapping || {};
        const workflowJson = data.data.workflowJson;
        
        if (workflowJson) {
          try {
            const workflowObj = typeof workflowJson === 'string' ? JSON.parse(workflowJson) : workflowJson;
            
            // 存储工作流JSON数据用于显示
            setWorkflowJsonData(workflowObj);
            
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
                  clipTextEncode.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'SaveImage') {
                  saveImage.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'easy int' || classType === 'JWInteger') {
                  easyInt.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'CR Prompt Text') {
                  crPromptText.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'VHS_VideoCombine') {
                  vhsVideoCombine.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'LoadImage') {
                  loadImage.push(`${nodeId} (${metaTitle || classType})`);
                }
              }
            }
            
            setAvailableNodes({ clipTextEncode, saveImage, easyInt, crPromptText, vhsVideoCombine, loadImage });
            
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
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: ''
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
                lastImageNodeId: mapping.last_image_node_id || '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: ''
              });
            } else if (workflow.type === 'shot') {
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
                lastImageNodeId: '',
                characterReferenceImageNodeId: mapping.character_reference_image_node_id || '',
                sceneReferenceImageNodeId: mapping.scene_reference_image_node_id || ''
              });
            } else {
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
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: ''
              });
            }
          } catch (e) {
            console.error('解析工作流 JSON 失败:', e);
          }
        }
      }
    } catch (error) {
      console.error('加载工作流映射失败:', error);
    }
  };

  const handleSaveMapping = async (e: React.FormEvent) => {
    e.preventDefault();
    e.stopPropagation(); // 防止触发外部表单提交
    if (!mappingWorkflow) return;
    
    setSavingMapping(true);
    try {
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
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null,
          width_node_id: mappingForm.widthNodeId || null,
          height_node_id: mappingForm.heightNodeId || null,
          reference_image_node_id: mappingForm.referenceImageNodeId || null,
          character_reference_image_node_id: mappingForm.characterReferenceImageNodeId || null,
          scene_reference_image_node_id: mappingForm.sceneReferenceImageNodeId || null
        };
      } else {
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
        const errorData = await res.json().catch(() => ({}));
        const errorMsg = errorData?.detail || t('systemSettings.configSaveFailed');
        console.error('保存映射配置失败:', errorData);
        toast.error(errorMsg);
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

  const getWorkflowsByType = (type: 'character' | 'scene' | 'shot' | 'video' | 'transition') => {
    return workflows.filter(w => w.type === type);
  };

  const typeNames = getTypeNames(t);

  if (loadingWorkflows) {
    return <div className="text-center py-8">{t('common.loading')}</div>;
  }

  return (
    <div className="space-y-6">
      {/* 上传按钮 */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setShowUploadModal(true)}
          className="btn-primary flex items-center gap-2"
        >
          <Plus className="h-4 w-4" />
          {t('systemSettings.workflow.upload')}
        </button>
      </div>

      {/* 按类型分组显示工作流 */}
      {(['character', 'scene', 'shot', 'video', 'transition'] as const).map(type => {
        const typeWorkflows = getWorkflowsByType(type);
        if (typeWorkflows.length === 0) return null;
        
        const TypeIcon = typeIcons[type];
        
        return (
          <div key={type} className="space-y-3">
            <h3 className="text-lg font-medium text-gray-900 flex items-center gap-2">
              <TypeIcon className="h-5 w-5" />
              {typeNames[type]}
            </h3>
            
            <div className="grid gap-3">
              {typeWorkflows.map(workflow => {
                const isMappingComplete = checkWorkflowMappingComplete(workflow);
                const TypeIcon = typeIcons[type];
                const typeColor = typeColors[type];
                
                return (
                  <div 
                    key={workflow.id} 
                    className={`p-4 border rounded-lg ${workflow.isActive ? 'border-blue-500 bg-blue-50' : 'border-gray-200 bg-white'}`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 flex items-start gap-3">
                        {/* 类型图标 */}
                        <div className={`p-2 rounded-lg ${typeColor}`}>
                          <TypeIcon className="h-5 w-5" />
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{getWorkflowDisplayName(workflow, t)}</span>
                            {workflow.isSystem && (
                              <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                                {t('promptConfig.systemDefault')}
                              </span>
                            )}
                            {workflow.isActive && (
                              <Star className="h-4 w-4 text-yellow-500 fill-yellow-500" />
                            )}
                            {!isMappingComplete && (
                              <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded">
                                {t('systemSettings.workflow.mappingConfigIncomplete')}
                              </span>
                            )}
                          </div>
                          {workflow.description && (
                            <p className="text-sm text-gray-500 mt-1">
                              {getWorkflowDisplayDescription(workflow, t)}
                            </p>
                          )}
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        {!workflow.isActive && (
                          <button
                            type="button"
                            onClick={() => handleSetDefault(workflow)}
                            className="p-2 text-gray-400 hover:text-blue-600"
                            title={t('systemSettings.workflow.setDefault')}
                          >
                            <Star className="h-4 w-4" />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleOpenMapping(workflow)}
                          className={`p-2 ${isMappingComplete ? 'text-green-500' : 'text-red-400'} hover:text-blue-600`}
                          title={t('systemSettings.workflow.nodeMapping')}
                        >
                          <SettingsIcon className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleOpenEdit(workflow)}
                          className="p-2 text-gray-400 hover:text-blue-600"
                          title={t('common.edit')}
                        >
                          <Edit2 className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDownload(workflow)}
                          className="p-2 text-gray-400 hover:text-blue-600"
                          title={t('common.download')}
                        >
                          <Download className="h-4 w-4" />
                        </button>
                        {!workflow.isSystem && (
                          <button
                            type="button"
                            onClick={() => handleDelete(workflow)}
                            className="p-2 text-gray-400 hover:text-red-600"
                            title={t('common.delete')}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {/* 上传弹窗 */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-medium mb-4">{t('systemSettings.workflow.upload')}</h3>
            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.workflow.type')}
                </label>
                <select
                  value={uploadType}
                  onChange={(e) => setUploadType(e.target.value as any)}
                  className="input-field"
                >
                  <option value="character">{typeNames.character}</option>
                  <option value="scene">{typeNames.scene}</option>
                  <option value="shot">{typeNames.shot}</option>
                  <option value="video">{typeNames.video}</option>
                  <option value="transition">{typeNames.transition}</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.workflow.name')}
                </label>
                <input
                  type="text"
                  value={uploadForm.name}
                  onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })}
                  className="input-field"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.workflow.description')}
                </label>
                <textarea
                  value={uploadForm.description}
                  onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
                  className="input-field"
                  rows={2}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('systemSettings.workflow.file')}
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={uploadForm.file?.name || ''}
                    className="input-field flex-1 bg-gray-50"
                    placeholder={t('systemSettings.workflow.selectFile')}
                    readOnly
                  />
                  <label className="btn-secondary cursor-pointer flex items-center gap-2 whitespace-nowrap">
                    <Upload className="h-4 w-4" />
                    {t('systemSettings.workflow.selectFile')}
                    <input
                      type="file"
                      accept=".json"
                      onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files?.[0] || null })}
                      className="hidden"
                      required
                    />
                  </label>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {t('systemSettings.workflow.comfyUIJsonTip')}
                </p>
              </div>
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowUploadModal(false)}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  disabled={uploading}
                  className="btn-primary"
                >
                  {uploading ? t('common.loading') : t('common.upload')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 编辑弹窗 */}
      {editingWorkflow && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-medium mb-4">{t('common.edit')}</h3>
            {loadingEdit ? (
              <div className="text-center py-8">{t('common.loading')}</div>
            ) : (
              <form onSubmit={handleSaveEdit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('systemSettings.workflow.name')}
                  </label>
                  <input
                    type="text"
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    className="input-field"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('systemSettings.workflow.description')}
                  </label>
                  <textarea
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    className="input-field"
                    rows={2}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Workflow JSON
                  </label>
                  <JSONEditor
                    value={editForm.workflowJson}
                    onChange={(value) => setEditForm({ ...editForm, workflowJson: value })}
                    readOnly={editingWorkflow.isSystem}
                    height={"300px"}
                  />
                </div>
                <div className="flex justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => setEditingWorkflow(null)}
                    className="btn-secondary"
                  >
                    {editingWorkflow.isSystem ? t('common.close') : t('common.cancel')}
                  </button>
                  {!editingWorkflow.isSystem && (
                    <button
                      type="submit"
                      disabled={savingEdit}
                      className="btn-primary"
                    >
                      {savingEdit ? t('common.loading') : t('common.save')}
                    </button>
                  )}
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* 节点映射弹窗 */}
      {mappingWorkflow && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
            <h3 className="text-lg font-medium mb-4">
              {t('systemSettings.workflow.nodeMapping')} - {getWorkflowDisplayName(mappingWorkflow, t)}
            </h3>
            <div className="flex gap-4 flex-1 min-h-0">
              {/* 左侧: 选中节点的 JSON 数据显示 */}
              <div className="w-1/2 border rounded-lg overflow-hidden flex flex-col">
                <div className="bg-gray-50 px-3 py-2 border-b text-sm font-medium text-gray-700">
                  {selectedNodeId ? `Node: ${selectedNodeId}` : t('systemSettings.workflow.selectNodeToView')}
                </div>
                <div className="flex-1 overflow-auto p-2 bg-gray-900">
                  <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono">
                    {selectedNodeId && workflowJsonData[selectedNodeId]
                      ? JSON.stringify({ [selectedNodeId]: workflowJsonData[selectedNodeId] }, null, 2)
                      : selectedNodeId 
                        ? t('systemSettings.workflow.nodeNotFound')
                        : t('systemSettings.workflow.selectNodeToView')}
                  </pre>
                </div>
              </div>
              
              {/* 右侧: 映射表单 */}
              <div className="w-1/2 overflow-y-auto">
                <form onSubmit={handleSaveMapping} className="space-y-4">
                  {/* 根据工作流类型显示不同的映射字段 */}
                  {(mappingWorkflow.type === 'character' || mappingWorkflow.type === 'scene') && (
                    <>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.promptInputNode')}
                        </label>
                        <select
                          value={mappingForm.promptNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, promptNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {[...availableNodes.clipTextEncode, ...availableNodes.crPromptText].map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.imageSaveNode')}
                        </label>
                        <select
                          value={mappingForm.saveImageNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, saveImageNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.saveImage.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                    </>
                  )}

                  {mappingWorkflow.type === 'shot' && (
                    <>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.promptInputNode')}
                        </label>
                        <select
                          value={mappingForm.promptNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, promptNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {[...availableNodes.clipTextEncode, ...availableNodes.crPromptText].map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.imageSaveNode')}
                        </label>
                        <select
                          value={mappingForm.saveImageNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, saveImageNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.saveImage.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">{t('systemSettings.workflow.widthNode')}</label>
                          <select
                            value={mappingForm.widthNodeId}
                            onChange={(e) => {
                              const value = e.target.value;
                              setMappingForm({ ...mappingForm, widthNodeId: value });
                              if (value) setSelectedNodeId(value);
                            }}
                            onFocus={(e) => {
                              if (e.target.value) setSelectedNodeId(e.target.value);
                            }}
                            className="input-field"
                          >
                            <option value="">-- {t('common.select')} --</option>
                            {availableNodes.easyInt.map(node => (
                              <option key={node} value={node.split(' ')[0]}>{node}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">{t('systemSettings.workflow.heightNode')}</label>
                          <select
                            value={mappingForm.heightNodeId}
                            onChange={(e) => {
                              const value = e.target.value;
                              setMappingForm({ ...mappingForm, heightNodeId: value });
                              if (value) setSelectedNodeId(value);
                            }}
                            onFocus={(e) => {
                              if (e.target.value) setSelectedNodeId(e.target.value);
                            }}
                            className="input-field"
                          >
                            <option value="">-- {t('common.select')} --</option>
                            {availableNodes.easyInt.map(node => (
                              <option key={node} value={node.split(' ')[0]}>{node}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.referenceImageNode')} ({t('common.optional')})
                        </label>
                        <select
                          value={mappingForm.referenceImageNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, referenceImageNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.loadImage.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">{t('systemSettings.workflow.characterReferenceNode')}</label>
                          <select
                            value={mappingForm.characterReferenceImageNodeId}
                            onChange={(e) => {
                              const value = e.target.value;
                              setMappingForm({ ...mappingForm, characterReferenceImageNodeId: value });
                              if (value) setSelectedNodeId(value);
                            }}
                            onFocus={(e) => {
                              if (e.target.value) setSelectedNodeId(e.target.value);
                            }}
                            className="input-field"
                          >
                            <option value="">-- {t('common.select')} --</option>
                            {availableNodes.loadImage.map(node => (
                              <option key={node} value={node.split(' ')[0]}>{node}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">{t('systemSettings.workflow.sceneReferenceNode')}</label>
                          <select
                            value={mappingForm.sceneReferenceImageNodeId}
                            onChange={(e) => {
                              const value = e.target.value;
                              setMappingForm({ ...mappingForm, sceneReferenceImageNodeId: value });
                              if (value) setSelectedNodeId(value);
                            }}
                            onFocus={(e) => {
                              if (e.target.value) setSelectedNodeId(e.target.value);
                            }}
                            className="input-field"
                          >
                            <option value="">-- {t('common.select')} --</option>
                            {availableNodes.loadImage.map(node => (
                              <option key={node} value={node.split(' ')[0]}>{node}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    </>
                  )}

                  {mappingWorkflow.type === 'video' && (
                    <>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.promptInputNode')}
                        </label>
                        <select
                          value={mappingForm.promptNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, promptNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {[...availableNodes.clipTextEncode, ...availableNodes.crPromptText].map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.videoSaveNode')}
                        </label>
                        <select
                          value={mappingForm.videoSaveNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, videoSaveNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.vhsVideoCombine.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.maxSideNode')}
                        </label>
                        <select
                          value={mappingForm.maxSideNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, maxSideNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.easyInt.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.referenceImageNode')}
                        </label>
                        <select
                          value={mappingForm.referenceImageNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, referenceImageNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.loadImage.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.frameCountNode')}
                        </label>
                        <select
                          value={mappingForm.frameCountNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, frameCountNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.easyInt.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                    </>
                  )}

                  {mappingWorkflow.type === 'transition' && (
                    <>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.firstImageNode')}
                        </label>
                        <select
                          value={mappingForm.firstImageNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, firstImageNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.loadImage.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.lastImageNode')}
                        </label>
                        <select
                          value={mappingForm.lastImageNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, lastImageNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.loadImage.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.videoSaveNode')}
                        </label>
                        <select
                          value={mappingForm.videoSaveNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, videoSaveNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.vhsVideoCombine.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {t('systemSettings.workflow.frameCountNode')}
                        </label>
                        <select
                          value={mappingForm.frameCountNodeId}
                          onChange={(e) => {
                            const value = e.target.value;
                            setMappingForm({ ...mappingForm, frameCountNodeId: value });
                            if (value) setSelectedNodeId(value);
                          }}
                          onFocus={(e) => {
                            if (e.target.value) setSelectedNodeId(e.target.value);
                          }}
                          className="input-field"
                        >
                          <option value="">-- {t('common.select')} --</option>
                          {availableNodes.easyInt.map(node => (
                            <option key={node} value={node.split(' ')[0]}>{node}</option>
                          ))}
                        </select>
                      </div>
                    </>
                  )}

                  <div className="flex justify-end gap-3 pt-4">
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
                      {savingMapping ? t('common.loading') : t('common.save')}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
