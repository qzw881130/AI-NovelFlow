import { useState } from 'react';
import { Image, Loader2, X } from 'lucide-react';

interface ImageEditModalLabels {
  title: string;
  optionsTitle: string;
  keepOriginalLayout: string;
  removeWeapons: string;
  makeFourView: string;
  other: string;
  otherPlaceholder: string;
  editButton: string;
  editing: string;
  replaceButton: string;
  originalImage: string;
  editResult: string;
  emptyResult: string;
}

interface ImageEditModalProps {
  isOpen: boolean;
  itemName: string;
  imageUrl: string;
  resultUrl: string | null;
  isEditing: boolean;
  isReplacing: boolean;
  labels: ImageEditModalLabels;
  onClose: () => void;
  onEdit: (prompt: string) => void;
  onReplace: () => void;
  onResultSizeChange?: (size: { width: number; height: number } | null) => void;
  resultSize?: { width: number; height: number } | null;
}

export function ImageEditModal({
  isOpen,
  itemName,
  imageUrl,
  resultUrl,
  isEditing,
  isReplacing,
  labels,
  onClose,
  onEdit,
  onReplace,
  onResultSizeChange,
  resultSize,
}: ImageEditModalProps) {
  const [selectedOptions, setSelectedOptions] = useState<string[]>([]);
  const [otherText, setOtherText] = useState('');

  if (!isOpen) return null;

  const toggleOption = (option: string) => {
    setSelectedOptions(prev => (
      prev.includes(option) ? prev.filter(item => item !== option) : [...prev, option]
    ));
  };

  const buildPrompt = () => {
    const selectedPrompts = selectedOptions
      .filter(option => option !== 'other')
      .map(option => {
        if (option === 'keepOriginalLayout') return labels.keepOriginalLayout;
        if (option === 'removeWeapons') return labels.removeWeapons;
        return labels.makeFourView;
      });
    const otherPrompt = selectedOptions.includes('other') ? otherText.trim() : '';
    return [...selectedPrompts, otherPrompt].filter(Boolean).join('\n');
  };

  const handleClose = () => {
    if (isEditing || isReplacing) return;
    setSelectedOptions([]);
    setOtherText('');
    onResultSizeChange?.(null);
    onClose();
  };

  const handleEdit = () => {
    onEdit(buildPrompt());
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{labels.title}</h2>
            <p className="mt-1 text-sm text-gray-500">{itemName}</p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={isEditing || isReplacing}
            className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="grid gap-6 p-6 lg:grid-cols-[280px_1fr]">
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">{labels.optionsTitle}</p>
              <div className="space-y-2">
                {[
                  { key: 'keepOriginalLayout', label: labels.keepOriginalLayout },
                  { key: 'removeWeapons', label: labels.removeWeapons },
                  { key: 'makeFourView', label: labels.makeFourView },
                  { key: 'other', label: labels.other },
                ].map(option => (
                  <label key={option.key} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm hover:bg-gray-50">
                    <input
                      type="checkbox"
                      checked={selectedOptions.includes(option.key)}
                      onChange={() => toggleOption(option.key)}
                      className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </div>
            {selectedOptions.includes('other') && (
              <textarea
                rows={4}
                value={otherText}
                onChange={(event) => setOtherText(event.target.value)}
                className="input-field"
                placeholder={labels.otherPlaceholder}
              />
            )}
            <button
              type="button"
              onClick={handleEdit}
              disabled={isEditing}
              className="btn-primary w-full justify-center disabled:opacity-70"
            >
              {isEditing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Image className="mr-2 h-4 w-4" />}
              {isEditing ? labels.editing : labels.editButton}
            </button>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">{labels.originalImage}</p>
              <div className="aspect-square overflow-hidden rounded-lg bg-gray-100">
                <img src={imageUrl} alt={itemName} className="h-full w-full object-contain" />
              </div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">{labels.editResult}</p>
              <div className="aspect-square overflow-hidden rounded-lg bg-gray-100 flex items-center justify-center">
                {isEditing ? (
                  <div className="text-center text-sm text-gray-500">
                    <Loader2 className="mx-auto mb-2 h-8 w-8 animate-spin text-primary-600" />
                    {labels.editing}
                  </div>
                ) : resultUrl ? (
                  <img
                    src={resultUrl}
                    alt={`${itemName} edited`}
                    className="h-full w-full object-contain"
                    onLoad={(event) => onResultSizeChange?.({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    })}
                  />
                ) : (
                  <span className="text-sm text-gray-400">{labels.emptyResult}</span>
                )}
              </div>
              {resultUrl && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <span className="text-sm text-gray-500">
                    {resultSize ? `${resultSize.width} x ${resultSize.height} px` : ''}
                  </span>
                  <button type="button" onClick={onReplace} disabled={isReplacing} className="btn-primary disabled:opacity-70">
                    {isReplacing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    {labels.replaceButton}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
