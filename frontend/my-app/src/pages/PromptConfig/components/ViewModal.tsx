import { X, Copy } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import type { PromptTemplate } from '../../../types';

interface ViewModalProps {
  show: boolean;
  template: PromptTemplate | null;
  onClose: () => void;
  onCopy: (template: PromptTemplate) => void;
  getDisplayName: (template: PromptTemplate) => string;
  getDisplayDescription: (template: PromptTemplate) => string;
}

export function ViewModal({ show, template, onClose, onCopy, getDisplayName, getDisplayDescription }: ViewModalProps) {
  const { t } = useTranslation();
  if (!show || !template) return null;

  const handleCopyPrompt = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(template.template);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = template.template;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      toast.success(t('common.copied'));
    } catch (error) {
      console.error('复制提示词失败:', error);
      toast.error(t('common.copyFailed'));
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between mb-4 flex-shrink-0">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{getDisplayName(template)}</h3>
            <p className="text-sm text-gray-500">{getDisplayDescription(template)}</p>
            <p className="text-xs text-gray-400 mt-1">{t('promptConfig.charCount')}: {template.template.length}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopyPrompt}
              className="p-1 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
              title={t('common.copy')}
            >
              <Copy className="h-5 w-5" />
            </button>
            <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 overflow-x-auto overflow-y-auto flex-1 min-h-0">
          <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono">{template.template}</pre>
        </div>
        <div className="flex justify-end gap-3 mt-4 pt-4 border-t border-gray-200 flex-shrink-0">
          <button onClick={onClose} className="btn-secondary">{t('common.close')}</button>
          {template.isSystem && (
            <button onClick={() => { onClose(); onCopy(template); }} className="btn-primary">
              <Copy className="mr-2 h-4 w-4" />{t('promptConfig.copyAsUser')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
