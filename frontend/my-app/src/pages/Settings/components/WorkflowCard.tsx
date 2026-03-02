import { Star, Edit2, Download, Trash2, Settings as SettingsIcon, User, Image as ImageIcon, Film, Mountain, Box, Music } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { getWorkflowDisplayName, getWorkflowDisplayDescription, checkWorkflowMappingComplete } from '../utils';
import type { Workflow } from '../types';
import { workflowApi } from '../../../api/workflows';

const typeIcons = {
  character: User,
  scene: Mountain,
  shot: ImageIcon,
  video: Film,
  transition: Film,
  prop: Box,
  voice_design: SettingsIcon,
  audio: Music
};

const typeColors = {
  character: 'bg-blue-100 text-blue-600',
  scene: 'bg-green-100 text-green-600',
  shot: 'bg-amber-100 text-amber-600',
  video: 'bg-pink-100 text-pink-600',
  transition: 'bg-purple-100 text-purple-600',
  prop: 'bg-orange-100 text-orange-600',
  voice_design: 'bg-cyan-100 text-cyan-600',
  audio: 'bg-indigo-100 text-indigo-600'
};

interface WorkflowCardProps {
  workflow: Workflow;
  extensionConfigs: Record<string, any>;
  onSetDefault: (workflow: Workflow) => void;
  onOpenEdit: (workflow: Workflow) => void;
  onOpenMapping: (workflow: Workflow) => void;
  onDelete: (workflow: Workflow) => void;
  onDownload: (workflow: Workflow) => void;
}

export function WorkflowCard({ 
  workflow, 
  extensionConfigs, 
  onSetDefault, 
  onOpenEdit, 
  onOpenMapping, 
  onDelete,
  onDownload 
}: WorkflowCardProps) {
  const { t } = useTranslation();
  const isMappingComplete = checkWorkflowMappingComplete(workflow);
  const TypeIcon = typeIcons[workflow.type];
  const typeColor = typeColors[workflow.type];

  return (
    <div 
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
            {/* 扩展属性显示 */}
            {workflow.extension && extensionConfigs[workflow.type] && (
              <div className="mt-2 flex items-center gap-2">
                <span className="text-xs text-gray-400">
                  {t(extensionConfigs[workflow.type].labelKey, { defaultValue: extensionConfigs[workflow.type].label })}:
                </span>
                <span className={`text-xs px-2 py-0.5 rounded ${getExtensionColor(workflow, extensionConfigs)}`}>
                  {getExtensionValue(workflow, extensionConfigs, t)}
                </span>
              </div>
            )}
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {!workflow.isActive && (
            <button
              type="button"
              onClick={() => onSetDefault(workflow)}
              className="p-2 text-gray-400 hover:text-blue-600"
              title={t('systemSettings.workflow.setDefault')}
            >
              <Star className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={() => onOpenMapping(workflow)}
            className={`p-2 ${isMappingComplete ? 'text-green-500' : 'text-red-400'} hover:text-blue-600`}
            title={t('systemSettings.workflow.nodeMapping')}
          >
            <SettingsIcon className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onOpenEdit(workflow)}
            className="p-2 text-gray-400 hover:text-blue-600"
            title={t('common.edit')}
          >
            <Edit2 className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onDownload(workflow)}
            className="p-2 text-gray-400 hover:text-blue-600"
            title={t('common.download')}
          >
            <Download className="h-4 w-4" />
          </button>
          {!workflow.isSystem && (
            <button
              type="button"
              onClick={() => onDelete(workflow)}
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
}

// 获取扩展属性颜色
function getExtensionColor(workflow: Workflow, extensionConfigs: Record<string, any>): string {
  const config = extensionConfigs[workflow.type];
  const propName = config?.name;
  const value = workflow.extension?.[propName];
  
  switch (value) {
    case 'single':
      return 'bg-green-50 text-green-600';
    case 'dual':
      return 'bg-blue-50 text-blue-600';
    case 'triple':
      return 'bg-amber-50 text-amber-600';
    default:
      return 'bg-gray-50 text-gray-600';
  }
}

// 获取扩展属性值显示文本
function getExtensionValue(workflow: Workflow, extensionConfigs: Record<string, any>, t: any): string {
  const config = extensionConfigs[workflow.type];
  const propName = config?.name;
  const value = workflow.extension?.[propName];
  const option = config?.options?.find((opt: any) => opt.value === value);
  return option ? t(option.labelKey, { defaultValue: option.label }) : value;
}
