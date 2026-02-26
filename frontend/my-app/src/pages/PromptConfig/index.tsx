import { useState } from 'react';
import { Loader2, Plus, FileText, BookOpen, Palette, Users, MapPin, Image } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import type { PromptTemplate } from '../../types';
import type { TemplateType } from './types';
import { usePromptConfigState, TEMPLATE_TYPE_CONFIG } from './hooks/usePromptConfigState';
import { TemplateCard } from './components/TemplateCard';
import { EditModal } from './components/EditModal';
import { ViewModal } from './components/ViewModal';

// 图标映射
const TYPE_ICONS: Record<TemplateType, React.ReactNode> = {
  style: <Palette className="h-4 w-4" />,
  character_parse: <Users className="h-4 w-4" />,
  scene_parse: <MapPin className="h-4 w-4" />,
  character: <FileText className="h-4 w-4" />,
  scene: <Image className="h-4 w-4" />,
  chapter_split: <BookOpen className="h-4 w-4" />,
};

// Tab 标签页颜色映射
const TAB_COLORS: Record<TemplateType, { active: string; inactive: string; border: string }> = {
  style: { active: 'text-pink-600 bg-pink-50 border-pink-200', inactive: 'text-gray-500 hover:text-pink-600', border: 'border-pink-200' },
  character_parse: { active: 'text-blue-600 bg-blue-50 border-blue-200', inactive: 'text-gray-500 hover:text-blue-600', border: 'border-blue-200' },
  scene_parse: { active: 'text-green-600 bg-green-50 border-green-200', inactive: 'text-gray-500 hover:text-green-600', border: 'border-green-200' },
  character: { active: 'text-purple-600 bg-purple-50 border-purple-200', inactive: 'text-gray-500 hover:text-purple-600', border: 'border-purple-200' },
  scene: { active: 'text-orange-600 bg-orange-50 border-orange-200', inactive: 'text-gray-500 hover:text-orange-600', border: 'border-orange-200' },
  chapter_split: { active: 'text-cyan-600 bg-cyan-50 border-cyan-200', inactive: 'text-gray-500 hover:text-cyan-600', border: 'border-cyan-200' },
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
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">{t(config.descKey)}</p>
        <button onClick={() => onEdit(type)}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors">
          <Plus className="h-4 w-4" />{t('promptConfig.newPrompt')}
        </button>
      </div>
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

  // 当前选中的 Tab
  const [activeTab, setActiveTab] = useState<TemplateType>('character');

  // 模板类型顺序
  const templateTypes: TemplateType[] = ['style', 'character_parse', 'scene_parse', 'character', 'scene', 'chapter_split'];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('promptConfig.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">{t('promptConfig.subtitle')}</p>
      </div>

      {/* Tab 标签页 */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-1 overflow-x-auto" role="tablist">
          {templateTypes.map(type => {
            const isActive = activeTab === type;
            const colors = TAB_COLORS[type];
            return (
              <button
                key={type}
                role="tab"
                aria-selected={isActive}
                onClick={() => setActiveTab(type)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-all whitespace-nowrap
                  ${isActive 
                    ? `${colors.active} border-current` 
                    : `border-transparent ${colors.inactive}`}
                `}
              >
                {TYPE_ICONS[type]}
                {t(TEMPLATE_TYPE_CONFIG[type].nameKey)}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Tab 内容区 */}
      <div role="tabpanel" className="card">
        <TemplateSection
          type={activeTab}
          templates={state.templatesByType[activeTab]}
          loading={state.loadingByType[activeTab]}
          onView={state.openViewModal}
          onEdit={state.openModal}
          onCopy={state.handleCopy}
          onDelete={state.handleDelete}
          getDisplayName={displayName}
          getDisplayDescription={displayDesc}
        />
      </div>

      <EditModal show={state.showModal} onClose={() => state.setShowModal(false)} onSave={state.handleSave}
        modalType={state.modalType} editingPrompt={state.editingPrompt} form={state.form} setForm={state.setForm} saving={state.saving} />

      <ViewModal show={state.showViewModal} template={state.viewingPrompt} onClose={() => state.setShowViewModal(false)}
        onCopy={state.handleCopy} getDisplayName={displayName} getDisplayDescription={displayDesc} />
    </div>
  );
}
