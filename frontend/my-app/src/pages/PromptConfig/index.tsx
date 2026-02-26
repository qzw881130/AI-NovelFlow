import { Loader2, Plus, FileText, BookOpen, Palette, Users, MapPin, Image, Sparkles } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { PromptTemplate } from '../../types';
import type { TemplateType } from './types';
import { usePromptConfigState, TEMPLATE_TYPE_CONFIG } from './hooks/usePromptConfigState';
import { TemplateCard } from './components/TemplateCard';
import { EditModal } from './components/EditModal';
import { ViewModal } from './components/ViewModal';

// 图标映射
const TYPE_ICONS: Record<TemplateType, React.ReactNode> = {
  style: <Palette className="h-5 w-5 text-pink-600" />,
  character_parse: <Users className="h-5 w-5 text-blue-600" />,
  scene_parse: <MapPin className="h-5 w-5 text-green-600" />,
  character: <FileText className="h-5 w-5 text-purple-600" />,
  scene: <Image className="h-5 w-5 text-orange-600" />,
  chapter_split: <BookOpen className="h-5 w-5 text-cyan-600" />,
};

// 获取模板显示名称
const getTemplateDisplayName = (template: PromptTemplate, t: any): string => {
  if (template.isSystem && template.nameKey) return t(template.nameKey, { defaultValue: template.name });
  return template.name;
};

// 获取模板显示描述
const getTemplateDisplayDescription = (template: PromptTemplate, t: any): string => {
  if (template.isSystem && template.descriptionKey) return t(template.descriptionKey, { defaultValue: template.description });
  return template.description;
};

// 渲染模板列表
function TemplateList({
  templates, loading, type, onView, onEdit, onCopy, onDelete, getDisplayName, getDisplayDescription
}: {
  templates: PromptTemplate[];
  loading: boolean;
  type: TemplateType;
  onView: (t: PromptTemplate) => void;
  onEdit: (type: TemplateType, t?: PromptTemplate) => void;
  onCopy: (t: PromptTemplate) => void;
  onDelete: (t: PromptTemplate) => void;
  getDisplayName: (t: PromptTemplate) => string;
  getDisplayDescription: (t: PromptTemplate) => string;
}) {
  const { t } = useTranslation();
  if (loading) return <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>;
  if (templates.length === 0) return <p className="text-sm text-gray-500 py-4">{t('promptConfig.noTemplates')}</p>;
  return (
    <div className="space-y-3">
      {templates.map((template) => (
        <TemplateCard key={template.id} template={template} type={type} onView={onView} onEdit={onEdit}
          onCopy={onCopy} onDelete={onDelete} getDisplayName={getDisplayName} getDisplayDescription={getDisplayDescription} />
      ))}
    </div>
  );
}

// 模板类型区块组件
function TemplateSection({
  type,
  templates,
  loading,
  icon,
  onView,
  onEdit,
  onCopy,
  onDelete,
  getDisplayName,
  getDisplayDescription,
}: {
  type: TemplateType;
  templates: PromptTemplate[];
  loading: boolean;
  icon: React.ReactNode;
  onView: (t: PromptTemplate) => void;
  onEdit: (type: TemplateType, t?: PromptTemplate) => void;
  onCopy: (t: PromptTemplate) => void;
  onDelete: (t: PromptTemplate) => void;
  getDisplayName: (t: PromptTemplate) => string;
  getDisplayDescription: (t: PromptTemplate) => string;
}) {
  const { t } = useTranslation();
  const config = TEMPLATE_TYPE_CONFIG[type];

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-lg font-semibold text-gray-900">{t(config.nameKey)}</h2>
        </div>
        <button onClick={() => onEdit(type)}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors">
          <Plus className="h-4 w-4" />{t('promptConfig.newPrompt')}
        </button>
      </div>
      <p className="text-sm text-gray-500 mb-4">{t(config.descKey)}</p>
      <TemplateList templates={templates} loading={loading} type={type}
        onView={onView} onEdit={onEdit} onCopy={onCopy} onDelete={onDelete}
        getDisplayName={getDisplayName} getDisplayDescription={getDisplayDescription} />
    </div>
  );
}

export default function PromptConfig() {
  const { t } = useTranslation();
  const state = usePromptConfigState();
  const displayName = (tp: PromptTemplate) => getTemplateDisplayName(tp, t);
  const displayDesc = (tp: PromptTemplate) => getTemplateDisplayDescription(tp, t);

  // 模板类型顺序
  const templateTypes: TemplateType[] = ['style', 'character_parse', 'scene_parse', 'character', 'scene', 'chapter_split'];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('promptConfig.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">{t('promptConfig.subtitle')}</p>
      </div>

      {/* 各类型模板管理 */}
      {templateTypes.map(type => (
        <TemplateSection
          key={type}
          type={type}
          templates={state.templatesByType[type]}
          loading={state.loadingByType[type]}
          icon={TYPE_ICONS[type]}
          onView={state.openViewModal}
          onEdit={state.openModal}
          onCopy={state.handleCopy}
          onDelete={state.handleDelete}
          getDisplayName={displayName}
          getDisplayDescription={displayDesc}
        />
      ))}

      <EditModal show={state.showModal} onClose={() => state.setShowModal(false)} onSave={state.handleSave}
        modalType={state.modalType} editingPrompt={state.editingPrompt} form={state.form} setForm={state.setForm} saving={state.saving} />

      <ViewModal show={state.showViewModal} template={state.viewingPrompt} onClose={() => state.setShowViewModal(false)}
        onCopy={state.handleCopy} getDisplayName={displayName} getDisplayDescription={displayDesc} />
    </div>
  );
}
