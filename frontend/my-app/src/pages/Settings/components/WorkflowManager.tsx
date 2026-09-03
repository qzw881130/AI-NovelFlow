// 工作流管理组件

import { useState, useEffect } from 'react';
import { Plus, User, Image as ImageIcon, Film, Mountain, Box, Mic, Music, Clapperboard, Download, Upload as UploadIcon, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { getWorkflowDisplayName, getTypeNames } from '../utils';
import type { Workflow } from '../types';
import { workflowApi, type WorkflowImportPreview } from '../../../api/workflows';

// 导入拆分后的组件
import { UploadModal } from './UploadModal';
import { EditModal } from './EditModal';
import { MappingModal } from './MappingModal';
import { WorkflowCard } from './WorkflowCard';

const typeIcons: Record<string, typeof User> = {
  character: User,
  scene: Mountain,
  shot_scene: ImageIcon,
  shot_character_scene: ImageIcon,
  shot_scene_prop: ImageIcon,
  shot: ImageIcon,
  video: Film,
  first_last_video: Film,
  three_frame_video: Film,
  four_frame_video: Film,
  transition: Film,
  prop: Box,
  voice_design: Mic,
  audio: Music,
  keyframe_image: Clapperboard,
  single_image_edit: ImageIcon,
};

const workflowTypeOrder = ['character', 'scene', 'prop', 'shot_scene', 'shot_character_scene', 'shot_scene_prop', 'shot', 'keyframe_image', 'single_image_edit', 'video', 'first_last_video', 'three_frame_video', 'four_frame_video', 'transition', 'voice_design', 'audio'] as const;

interface WorkflowManagerProps {
  onRefresh?: () => void;
}

export default function WorkflowManager({ onRefresh }: WorkflowManagerProps) {
  const { t } = useTranslation();
  
  // 工作流列表
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);
  const [exportingWorkflows, setExportingWorkflows] = useState(false);
  const [exportingActiveWorkflows, setExportingActiveWorkflows] = useState(false);
  const [importingWorkflows, setImportingWorkflows] = useState(false);
  
  // 弹窗状态
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [mappingWorkflow, setMappingWorkflow] = useState<Workflow | null>(null);
  const [selectedExportIds, setSelectedExportIds] = useState<string[]>([]);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<WorkflowImportPreview | null>(null);
  const [selectedImportIndexes, setSelectedImportIndexes] = useState<number[]>([]);
  
  // 扩展属性配置
  const [extensionConfigs, setExtensionConfigs] = useState<Record<string, any>>({});

  const typeNames = getTypeNames(t);

  useEffect(() => {
    fetchWorkflows();
    fetchExtensionConfigs();
  }, []);

  const fetchExtensionConfigs = async () => {
    try {
      const data = await workflowApi.fetchExtensionsConfig();
      if (data.success && data.data) {
        setExtensionConfigs(data.data as Record<string, any>);
      }
    } catch (error) {
      console.error('加载扩展属性配置失败:', error);
    }
  };

  const fetchWorkflows = async () => {
    try {
      const data = await workflowApi.fetchList();
      if (data.success && data.data) {
        setWorkflows(data.data as unknown as Workflow[]);
      }
    } catch (error) {
      console.error('加载工作流失败:', error);
    } finally {
      setLoadingWorkflows(false);
    }
  };

  const handleSetDefault = async (workflow: Workflow) => {
    try {
      const data = await workflowApi.setDefault(workflow.id);
      if (data.success) {
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
      await workflowApi.delete(workflow.id);
      fetchWorkflows();
    } catch (error) {
      console.error('删除失败:', error);
    }
  };

  const handleDownload = async (workflow: Workflow) => {
    try {
      const result = await workflowApi.fetch(workflow.id);
      if (result.success && result.data) {
        const wf = result.data as any;
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

  const getWorkflowsByType = (type: string) => {
    return workflows.filter(w => w.type === type);
  };

  const knownTypes = new Set<string>(workflowTypeOrder);
  const unknownTypes = Array.from(new Set(workflows.filter(workflow => !knownTypes.has(workflow.type)).map(workflow => workflow.type)));
  const groupedWorkflows = [
    ...workflowTypeOrder
      .map(type => ({ type, label: typeNames[type], workflows: getWorkflowsByType(type) }))
      .filter(group => group.workflows.length > 0),
    ...unknownTypes.map(type => ({ type, label: `其他 / ${type || '未分类'}`, workflows: getWorkflowsByType(type) })),
  ];

  const importGroups = importPreview
    ? Array.from(new Set(importPreview.workflows.map(item => item.type))).map(type => ({
        type,
        label: typeNames[type as keyof typeof typeNames] || importPreview.workflows.find(item => item.type === type)?.type_label || type,
        workflows: importPreview.workflows.filter(item => item.type === type),
      }))
    : [];

  const openExportModal = () => {
    setSelectedExportIds(workflows.map(workflow => workflow.id));
    setShowExportModal(true);
  };

  const toggleExportWorkflow = (workflowId: string) => {
    setSelectedExportIds(prev => prev.includes(workflowId) ? prev.filter(id => id !== workflowId) : [...prev, workflowId]);
  };

  const toggleImportWorkflow = (index: number) => {
    setSelectedImportIndexes(prev => prev.includes(index) ? prev.filter(item => item !== index) : [...prev, index]);
  };

  const handleExportActiveWorkflows = async () => {
    setExportingActiveWorkflows(true);
    try {
      await workflowApi.exportActive();
      toast.success('工作流已打包下载');
    } catch (error) {
      console.error('打包下载工作流失败:', error);
      toast.error(error instanceof Error ? error.message : '打包下载工作流失败');
    } finally {
      setExportingActiveWorkflows(false);
    }
  };

  const handleExportSelectedWorkflows = async () => {
    if (!selectedExportIds.length) {
      toast.warning('请选择要导出的工作流');
      return;
    }
    setExportingWorkflows(true);
    try {
      await workflowApi.exportSelected(selectedExportIds);
      setShowExportModal(false);
      toast.success('工作流已导出');
    } catch (error) {
      console.error('导出工作流失败:', error);
      toast.error(error instanceof Error ? error.message : '导出工作流失败');
    } finally {
      setExportingWorkflows(false);
    }
  };

  const handlePreviewImport = async (file: File) => {
    setImportFile(file);
    setImportPreview(null);
    setSelectedImportIndexes([]);
    try {
      const data = await workflowApi.previewImport(file);
      if (data.success && data.data) {
        setImportPreview(data.data);
        setSelectedImportIndexes(data.data.workflows.filter(item => item.valid).map(item => item.index));
        if (data.data.invalid_count > 0) toast.warning(`有 ${data.data.invalid_count} 个工作流不符合导入条件`);
      }
    } catch (error) {
      console.error('解析工作流 ZIP 失败:', error);
      toast.error(error instanceof Error ? error.message : '解析工作流 ZIP 失败');
    }
  };

  const handleExecuteImport = async () => {
    if (!importFile) {
      toast.warning('请先选择 ZIP 文件');
      return;
    }
    if (!selectedImportIndexes.length) {
      toast.warning('请选择要导入的工作流');
      return;
    }
    setImportingWorkflows(true);
    try {
      const data = await workflowApi.executeImport(importFile, selectedImportIndexes);
      toast.success(data.message || '工作流已导入');
      setShowImportModal(false);
      setImportFile(null);
      setImportPreview(null);
      setSelectedImportIndexes([]);
      fetchWorkflows();
    } catch (error) {
      console.error('导入工作流失败:', error);
      toast.error(error instanceof Error ? error.message : '导入工作流失败');
    } finally {
      setImportingWorkflows(false);
    }
  };

  if (loadingWorkflows) {
    return <div className="text-center py-8">{t('common.loading')}</div>;
  }

  return (
    <div className="space-y-6">
      {/* 导入导出按钮 */}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={handleExportActiveWorkflows}
          disabled={exportingActiveWorkflows}
          className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          {exportingActiveWorkflows ? '打包中...' : '打包下载当前工作流'}
        </button>
        <button
          type="button"
          onClick={openExportModal}
          disabled={exportingWorkflows}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          导出
        </button>
        <button
          type="button"
          onClick={() => setShowImportModal(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700"
        >
          <UploadIcon className="h-4 w-4" />
          导入
        </button>
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
      {workflowTypeOrder.map(type => {
        const typeWorkflows = getWorkflowsByType(type);
        if (typeWorkflows.length === 0) return null;
        
        const TypeIcon = typeIcons[type] || Clapperboard;
        
        return (
          <div key={type} className="space-y-3">
            <h3 className="text-lg font-medium text-gray-900 flex items-center gap-2">
              <TypeIcon className="h-5 w-5" />
              {typeNames[type]}
            </h3>
            
            <div className="grid gap-3">
              {typeWorkflows.map(workflow => (
                <WorkflowCard
                  key={workflow.id}
                  workflow={workflow}
                  extensionConfigs={extensionConfigs}
                  onSetDefault={handleSetDefault}
                  onOpenEdit={setEditingWorkflow}
                  onOpenMapping={setMappingWorkflow}
                  onDelete={handleDelete}
                  onDownload={handleDownload}
                />
              ))}
            </div>
          </div>
        );
      })}

      {/* 上传弹窗 */}
      <UploadModal
        isOpen={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        onSuccess={fetchWorkflows}
        extensionConfigs={extensionConfigs}
        typeNames={typeNames}
      />

      {showExportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4">
          <div className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-6 py-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">导出 ComfyUI 工作流</h3>
                <p className="text-sm text-gray-500">选择要导出的工作流，ZIP 会包含名称、分类、描述、节点映射、扩展配置和工作流 JSON。</p>
              </div>
              <button onClick={() => setShowExportModal(false)} className="p-1 text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
            </div>
            <div className="flex items-center justify-between border-b bg-gray-50 px-6 py-3 text-sm">
              <span className="text-gray-600">已选择 {selectedExportIds.length} / {workflows.length} 个</span>
              <button type="button" onClick={() => setSelectedExportIds(selectedExportIds.length === workflows.length ? [] : workflows.map(workflow => workflow.id))} className="text-blue-600 hover:text-blue-700">
                {selectedExportIds.length === workflows.length ? '取消全选' : '全选'}
              </button>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-6">
              {groupedWorkflows.map(group => (
                <div key={group.type} className="space-y-2">
                  <h4 className="text-sm font-semibold text-gray-800">{group.label}</h4>
                  {group.workflows.map(workflow => (
                    <label key={workflow.id} className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 p-3 hover:bg-blue-50">
                      <input type="checkbox" checked={selectedExportIds.includes(workflow.id)} onChange={() => toggleExportWorkflow(workflow.id)} className="mt-1" />
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-gray-900">{getWorkflowDisplayName(workflow, t)}</div>
                        <div className="text-xs text-gray-500">{workflow.description || '-'} · 映射 {workflow.nodeMapping ? '已配置' : '未配置'}</div>
                      </div>
                    </label>
                  ))}
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 border-t px-6 py-4">
              <button type="button" onClick={() => setShowExportModal(false)} className="btn-secondary">取消</button>
              <button type="button" onClick={handleExportSelectedWorkflows} disabled={exportingWorkflows || selectedExportIds.length === 0} className="btn-primary disabled:opacity-50">
                {exportingWorkflows ? '导出中...' : '导出'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showImportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4">
          <div className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-6 py-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">导入 ComfyUI 工作流</h3>
                <p className="text-sm text-gray-500">上传导出的 ZIP，先检查内容，再选择要导入的工作流。</p>
              </div>
              <button onClick={() => setShowImportModal(false)} className="p-1 text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
            </div>
            <div className="border-b bg-gray-50 px-6 py-4">
              <input type="file" accept=".zip,application/zip" onChange={(e) => e.target.files?.[0] && handlePreviewImport(e.target.files[0])} className="block w-full text-sm text-gray-700" />
              {importPreview && <div className="mt-2 text-sm text-gray-600">可导入 {importPreview.valid_count} 个，不符合条件 {importPreview.invalid_count} 个，已选择 {selectedImportIndexes.length} 个。</div>}
            </div>
            <div className="flex items-center justify-end border-b px-6 py-3 text-sm">
              <button type="button" disabled={!importPreview || importPreview.valid_count === 0} onClick={() => importPreview && setSelectedImportIndexes(selectedImportIndexes.length === importPreview.valid_count ? [] : importPreview.workflows.filter(item => item.valid).map(item => item.index))} className="text-blue-600 hover:text-blue-700 disabled:text-gray-400">
                {importPreview && selectedImportIndexes.length === importPreview.valid_count ? '取消全选' : '全选'}
              </button>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-6">
              {!importPreview && <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">请选择 ZIP 文件后预览可导入工作流。</div>}
              {importGroups.map(group => (
                <div key={group.type} className="space-y-2">
                  <h4 className="text-sm font-semibold text-gray-800">{group.label}</h4>
                  {group.workflows.map(item => (
                    <label key={item.index} className={`flex items-start gap-3 rounded-lg border p-3 ${item.valid ? 'cursor-pointer border-gray-200 hover:bg-blue-50' : 'border-red-200 bg-red-50'}`}>
                      <input type="checkbox" disabled={!item.valid} checked={selectedImportIndexes.includes(item.index)} onChange={() => toggleImportWorkflow(item.index)} className="mt-1" />
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-gray-900">{item.name || '-'}</div>
                        <div className="text-xs text-gray-500">{item.description || '-'} · 映射 {Object.keys(item.node_mapping || {}).length ? '已包含' : '未包含'}</div>
                        {!item.valid && <div className="mt-1 text-xs text-red-600">{item.errors.join('；')}</div>}
                      </div>
                    </label>
                  ))}
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 border-t px-6 py-4">
              <button type="button" onClick={() => setShowImportModal(false)} className="btn-secondary">取消</button>
              <button type="button" onClick={handleExecuteImport} disabled={importingWorkflows || selectedImportIndexes.length === 0} className="btn-primary disabled:opacity-50">
                {importingWorkflows ? '导入中...' : '导入'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 编辑弹窗 */}
      <EditModal
        workflow={editingWorkflow}
        onClose={() => setEditingWorkflow(null)}
        onSuccess={fetchWorkflows}
        extensionConfigs={extensionConfigs}
      />

      {/* 节点映射弹窗 */}
      <MappingModal
        workflow={mappingWorkflow}
        onClose={() => setMappingWorkflow(null)}
        onSuccess={fetchWorkflows}
      />
    </div>
  );
}
