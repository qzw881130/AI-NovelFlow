import { Loader2, X } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { PromptTemplate } from '../../../types';
import type { TemplateType, PromptForm } from '../types';

interface EditModalProps {
  show: boolean;
  onClose: () => void;
  onSave: (e: React.FormEvent) => void;
  modalType: TemplateType;
  editingPrompt: PromptTemplate | null;
  form: PromptForm;
  setForm: React.Dispatch<React.SetStateAction<PromptForm>>;
  saving: boolean;
}

export function EditModal({ show, onClose, onSave, modalType, editingPrompt, form, setForm, saving }: EditModalProps) {
  const { t } = useTranslation();
  if (!show) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">
            {editingPrompt ? (editingPrompt.isSystem ? t('promptConfig.viewPrompt') : t('promptConfig.editPrompt')) : t('promptConfig.createPrompt')}
            {editingPrompt?.isSystem && (
              <span className="ml-2 text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">{t('promptConfig.systemPresetReadonly')}</span>
            )}
          </h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
        </div>
        <form onSubmit={onSave} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">{t('common.name')}</label>
            <input type="text" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="input-field mt-1" placeholder={t('promptConfig.namePlaceholder')} readOnly={editingPrompt?.isSystem} />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">{t('common.description')}</label>
            <textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="input-field mt-1" placeholder={t('promptConfig.descPlaceholder')} readOnly={editingPrompt?.isSystem} />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('promptConfig.promptTemplate')}
              <span className="text-xs text-gray-500 ml-2">
                {modalType === 'character' ? t('promptConfig.placeholderTip') : t('promptConfig.placeholderTipChapter')}
              </span>
            </label>
            {/* 仅对返回 JSON 结构的模板类型显示警告 */}
            {!['style', 'character', 'scene'].includes(modalType) && (
              <div className="mb-2 p-2 bg-red-50 border border-red-200 rounded-md">
                <p className="text-xs text-red-600 font-medium flex items-center gap-1">
                  <svg className="h-4 w-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  {t('promptConfig.jsonStructureWarning')}
                </p>
              </div>
            )}
            <textarea rows={modalType === 'chapter_split' ? 12 : 6} required value={form.template}
              onChange={(e) => setForm({ ...form, template: e.target.value })} className="input-field font-mono text-sm"
              placeholder={modalType === 'character' ? t('promptConfig.templatePlaceholderCharacter') : t('promptConfig.templatePlaceholderChapter')}
              readOnly={editingPrompt?.isSystem} />
            <div className="flex justify-between items-center mt-1">
              <p className="text-xs text-gray-500">{modalType === 'character' ? t('promptConfig.tipCharacter') : t('promptConfig.tipChapter')}</p>
              <p className="text-xs text-gray-500">{t('promptConfig.charCount')}: {form.template.length}</p>
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-4">
            <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
            {!editingPrompt?.isSystem && (
              <button type="submit" disabled={saving} className="btn-primary">
                {saving ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t('common.saving')}</> : t('common.save')}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
