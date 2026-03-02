// 工作流管理组件

import { useState, useEffect } from 'react';
import { Plus, User, Image as ImageIcon, Film, Mountain, Box, Mic, Music } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { getWorkflowDisplayName, getTypeNames } from '../utils';
import type { Workflow } from '../types';
import { workflowApi } from '../../../api/workflows';

// 导入拆分后的组件
import { UploadModal } from './UploadModal';
import { EditModal } from './EditModal';
import { MappingModal } from './MappingModal';
import { WorkflowCard } from './WorkflowCard';

const typeIcons = {
  character: User,
  scene: Mountain,
  shot: ImageIcon,
  video: Film,
  transition: Film,
  prop: Box,
  voice_design: Mic,
  audio: Music
};

interface WorkflowManagerProps {
  onRefresh?: () => void;
}

export default function WorkflowManager({ onRefresh }: WorkflowManagerProps) {
  const { t } = useTranslation();
  
  // 工作流列表
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);
  
  // 弹窗状态
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [mappingWorkflow, setMappingWorkflow] = useState<Workflow | null>(null);
  
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

  const getWorkflowsByType = (type: 'character' | 'scene' | 'shot' | 'video' | 'transition' | 'prop' | 'voice_design' | 'audio') => {
    return workflows.filter(w => w.type === type);
  };

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
      {(['character', 'scene', 'prop', 'shot', 'video', 'transition', 'voice_design', 'audio'] as const).map(type => {
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
