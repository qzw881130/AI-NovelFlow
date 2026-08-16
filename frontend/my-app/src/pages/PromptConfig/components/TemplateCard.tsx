import { Eye, Edit2, Trash2, Copy, Download } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { PromptTemplate } from '../../../types';
import type { TemplateType } from '../types';

interface TemplateCardProps {
  template: PromptTemplate;
  type: TemplateType;
  onView: (template: PromptTemplate) => void;
  onEdit: (type: TemplateType, template: PromptTemplate) => void;
  onCopy: (template: PromptTemplate) => void;
  onDelete: (template: PromptTemplate) => void;
  getDisplayName: (template: PromptTemplate) => string;
  getDisplayDescription: (template: PromptTemplate) => string;
}

export function TemplateCard({
  template, type, onView, onEdit, onCopy, onDelete, getDisplayName, getDisplayDescription
}: TemplateCardProps) {
  const { t } = useTranslation();

  const handleDownload = () => {
    const blob = new Blob([template.template], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safeName = getDisplayName(template).replace(/[\\/:*?"<>|\s]+/g, '_');
    link.href = url;
    link.download = `${safeName || template.id}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex items-center justify-between p-4 rounded-lg border border-gray-200 hover:border-gray-300 bg-white transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h4 className="font-medium text-gray-900">{getDisplayName(template)}</h4>
          {template.isSystem ? (
            <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-600 rounded-full">{t('promptConfig.systemDefault')}</span>
          ) : (
            <span className="text-xs px-2 py-0.5 bg-green-100 text-green-600 rounded-full">{t('promptConfig.userCustom')}</span>
          )}
        </div>
        <p className="text-sm text-gray-500 truncate">{getDisplayDescription(template)}</p>
        <p className="text-xs text-gray-400 mt-1 truncate font-mono">
          {template.template.substring(0, type === 'chapter_split' ? 120 : 80)}...
        </p>
      </div>
      <div className="flex items-center gap-1 ml-4">
        {template.isSystem ? (
          <>
            <button onClick={() => onView(template)} className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors" title={t('common.view')}>
              <Eye className="h-4 w-4" />
            </button>
            <button onClick={handleDownload} className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors" title={t('common.download')}>
              <Download className="h-4 w-4" />
            </button>
            <button onClick={() => onCopy(template)} className="p-1.5 text-gray-400 hover:text-green-600 hover:bg-green-100 rounded transition-colors" title={t('promptConfig.copyAsUser')}>
              <Copy className="h-4 w-4" />
            </button>
          </>
        ) : (
          <>
            <button onClick={() => onView(template)} className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors" title={t('common.view')}>
              <Eye className="h-4 w-4" />
            </button>
            <button onClick={handleDownload} className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors" title={t('common.download')}>
              <Download className="h-4 w-4" />
            </button>
            <button onClick={() => onEdit(type, template)} className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors" title={t('common.edit')}>
              <Edit2 className="h-4 w-4" />
            </button>
            <button onClick={() => onDelete(template)} className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-100 rounded transition-colors" title={t('common.delete')}>
              <Trash2 className="h-4 w-4" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
