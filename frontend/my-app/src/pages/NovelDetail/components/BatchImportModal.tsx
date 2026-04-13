import { useState, useRef, useCallback } from 'react';
import { X, Upload, Loader2, FileText, AlertCircle, CheckCircle } from 'lucide-react';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import { chapterApi } from '../../../api/chapters';

interface BatchImportModalProps {
  show: boolean;
  novelId: string;
  onClose: () => void;
  onImportComplete: () => void;
}

interface PreviewChapter {
  number: number;
  title: string;
  content_length: number;
  action: 'new' | 'replace';
}

interface PreviewError {
  segment: number;
  title: string;
  reason: string;
}

interface PreviewData {
  chapters: PreviewChapter[];
  summary: { total: number; new: number; replace: number };
  errors: PreviewError[];
}

type ModalState = 'idle' | 'previewing' | 'preview_done' | 'importing' | 'import_done' | 'import_partial' | 'import_failed';

export function BatchImportModal({ show, novelId, onClose, onImportComplete }: BatchImportModalProps) {
  const { t } = useTranslation();
  const [modalState, setModalState] = useState<ModalState>('idle');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewData, setPreviewData] = useState<PreviewData | null>(null);
  const [importResult, setImportResult] = useState<{
    total: number; created: number; updated: number; failed: number;
    errors: { number?: number; title: string; reason: string }[];
  } | null>(null);
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleClose = useCallback(() => {
    setModalState('idle');
    setSelectedFile(null);
    setPreviewData(null);
    setImportResult(null);
    setShowErrorDetails(false);
    onClose();
  }, [onClose]);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // 校验文件类型
    if (!file.name.toLowerCase().endsWith('.txt')) {
      toast.error(t('novelDetail.batchImport.invalidFileType'));
      return;
    }

    // 校验文件大小 (10MB)
    if (file.size > 10 * 1024 * 1024) {
      toast.error(t('novelDetail.batchImport.fileTooLarge'));
      return;
    }

    setSelectedFile(file);
    setModalState('previewing');

    try {
      const response = await chapterApi.batchImportPreview(novelId, file);
      if (response.success && response.data) {
        setPreviewData(response.data);
        setModalState('preview_done');
      } else {
        toast.error(response.message || t('novelDetail.batchImport.previewFailed'));
        setModalState('idle');
      }
    } catch (error) {
      console.error('预览失败:', error);
      toast.error(t('novelDetail.batchImport.networkError'));
      setModalState('idle');
    }
  };

  const handleImport = async () => {
    if (!selectedFile) return;
    setModalState('importing');

    try {
      const response = await chapterApi.batchImport(novelId, selectedFile);
      if (response.success && response.data) {
        const { failed } = response.data;
        if (failed > 0) {
          setImportResult(response.data);
          setModalState('import_partial');
        } else {
          setImportResult(response.data);
          setModalState('import_done');
          toast.success(response.message || t('novelDetail.batchImport.importComplete'));
          setTimeout(() => {
            handleClose();
            onImportComplete();
          }, 1000);
        }
      } else {
        setModalState('import_failed');
        toast.error(response.message || t('novelDetail.batchImport.importFailed'));
      }
    } catch (error) {
      console.error('导入失败:', error);
      setModalState('import_failed');
      toast.error(t('novelDetail.batchImport.networkError'));
    }
  };

  if (!show) return null;

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-2xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b">
          <h2 className="text-lg font-semibold text-gray-900">{t('novelDetail.batchImport.title')}</h2>
          <button onClick={handleClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* File Selection */}
          {modalState === 'idle' && (
            <div className="flex flex-col items-center justify-center py-8 border-2 border-dashed border-gray-300 rounded-lg hover:border-primary-400 transition-colors">
              <Upload className="h-10 w-10 text-gray-400 mb-3" />
              <label className="cursor-pointer">
                <span className="btn-primary inline-flex items-center">
                  <FileText className="h-4 w-4 mr-2" />
                  {t('novelDetail.batchImport.selectFile')}
                </span>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".txt"
                  className="hidden"
                  onChange={handleFileSelect}
                />
              </label>
              <p className="text-xs text-gray-500 mt-2">{t('novelDetail.batchImport.fileHint')}</p>
            </div>
          )}

          {/* Previewing */}
          {modalState === 'previewing' && (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary-600 mb-3" />
              <p className="text-gray-600">{t('novelDetail.batchImport.parsing')}</p>
            </div>
          )}

          {/* Preview Done */}
          {(modalState === 'preview_done' || modalState === 'importing') && previewData && (
            <>
              {selectedFile && (
                <div className="flex items-center gap-2 text-sm text-gray-600 bg-gray-50 rounded-lg p-3">
                  <FileText className="h-4 w-4" />
                  <span>{selectedFile.name}</span>
                  <span className="text-gray-400">({formatFileSize(selectedFile.size)})</span>
                </div>
              )}
              <div className="text-sm font-medium text-gray-700">
                {t('novelDetail.batchImport.previewTitle', {
                  total: previewData.summary.total,
                  newCount: previewData.summary.new,
                  replaceCount: previewData.summary.replace,
                })}
              </div>
              <div className="border rounded-lg max-h-64 overflow-y-auto">
                {previewData.chapters.map((ch, idx) => (
                  <div key={idx} className="flex items-center justify-between px-4 py-2 border-b last:border-b-0 hover:bg-gray-50">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-gray-500 w-8">{ch.number}</span>
                      <span className="text-sm text-gray-900">{ch.title}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-gray-500">{ch.content_length}{t('novelDetail.batchImport.chars')}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        ch.action === 'new'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-orange-100 text-orange-700'
                      }`}>
                        {ch.action === 'new'
                          ? t('novelDetail.batchImport.newLabel')
                          : t('novelDetail.batchImport.replaceLabel')}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              {previewData.errors.length > 0 && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-sm text-red-700 font-medium mb-1">
                    <AlertCircle className="h-4 w-4" />
                    {t('novelDetail.batchImport.parseErrors', { count: previewData.errors.length })}
                  </div>
                  <ul className="text-xs text-red-600 space-y-1 max-h-24 overflow-y-auto">
                    {previewData.errors.map((err, idx) => (
                      <li key={idx}>- {err.title}: {err.reason}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}

          {/* Importing */}
          {modalState === 'importing' && (
            <div className="flex flex-col items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-primary-600 mb-3" />
              <p className="text-gray-600">{t('novelDetail.batchImport.importing')}</p>
            </div>
          )}

          {/* Import Done */}
          {modalState === 'import_done' && importResult && (
            <div className="flex flex-col items-center justify-center py-6">
              <CheckCircle className="h-12 w-12 text-green-500 mb-3" />
              <p className="text-lg font-medium text-gray-900">{t('novelDetail.batchImport.importComplete')}</p>
              <p className="text-sm text-gray-600 mt-1">
                {t('novelDetail.batchImport.importSummary', {
                  created: importResult.created,
                  updated: importResult.updated,
                })}
              </p>
            </div>
          )}

          {/* Import Partial */}
          {modalState === 'import_partial' && importResult && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <AlertCircle className="h-5 w-5 text-orange-500" />
                <p className="font-medium text-gray-900">{t('novelDetail.batchImport.partialSuccess')}</p>
              </div>
              <p className="text-sm text-gray-600 mb-3">
                {t('novelDetail.batchImport.importPartialSummary', {
                  created: importResult.created,
                  updated: importResult.updated,
                  failed: importResult.failed,
                })}
              </p>
              <button
                onClick={() => setShowErrorDetails(!showErrorDetails)}
                className="text-sm text-primary-600 hover:underline"
              >
                {showErrorDetails ? t('novelDetail.batchImport.hideErrors') : t('novelDetail.batchImport.errorDetails')}
              </button>
              {showErrorDetails && importResult.errors.length > 0 && (
                <ul className="mt-2 text-xs text-red-600 bg-red-50 rounded-lg p-3 max-h-32 overflow-y-auto space-y-1">
                  {importResult.errors.map((err, idx) => (
                    <li key={idx}>- {err.title || `#${err.number}`}: {err.reason}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Import Failed */}
          {modalState === 'import_failed' && (
            <div className="flex flex-col items-center justify-center py-8">
              <AlertCircle className="h-12 w-12 text-red-500 mb-3" />
              <p className="text-lg font-medium text-gray-900">{t('novelDetail.batchImport.importFailed')}</p>
              <p className="text-sm text-gray-600 mt-1">{t('novelDetail.batchImport.networkError')}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-6 border-t">
          {(modalState === 'idle' || modalState === 'import_failed') && (
            <>
              <button onClick={handleClose} className="btn-secondary">{t('common.cancel')}</button>
            </>
          )}
          {modalState === 'preview_done' && (
            <>
              <button onClick={handleClose} className="btn-secondary">{t('common.cancel')}</button>
              <button
                onClick={handleImport}
                className="btn-primary"
                disabled={previewData?.chapters.length === 0}
              >
                {t('novelDetail.batchImport.confirmImport')}
              </button>
            </>
          )}
          {modalState === 'import_partial' && (
            <button onClick={handleClose} className="btn-primary">{t('common.close')}</button>
          )}
        </div>
      </div>
    </div>
  );
}
