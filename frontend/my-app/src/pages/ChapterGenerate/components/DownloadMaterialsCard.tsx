import { useState } from 'react';
import { Loader2, Download, Package } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { API_BASE } from '../constants';
import type { DownloadMaterialsCardProps } from '../types';

export default function DownloadMaterialsCard({ 
  novelId, 
  chapterId, 
  chapterTitle 
}: DownloadMaterialsCardProps) {
  const { t } = useTranslation();
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownload = async () => {
    if (!novelId || !chapterId) {
      toast.error(t('chapterGenerate.chapterInfoIncomplete'));
      return;
    }

    setIsDownloading(true);
    try {
      const response = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/download-materials/`
      );

      if (!response.ok) {
        if (response.status === 404) {
          toast.error(t('chapterGenerate.materialsNotExist'));
        } else {
          toast.error(t('chapterGenerate.downloadFailed'));
        }
        return;
      }

      // 获取文件名
      const contentDisposition = response.headers.get('content-disposition');
      let filename = `${chapterTitle}_materials.zip`;
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?(.+?)"?$/);
        if (match) {
          filename = match[1];
        }
      }

      // 下载文件
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      toast.success(t('chapterGenerate.materialsDownloadSuccess'));
    } catch (error) {
      console.error('Download error:', error);
      toast.error(t('chapterGenerate.downloadFailed'));
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="p-4 border-b border-gray-100 bg-gradient-to-r from-blue-50 to-purple-50">
        <div className="flex items-center gap-2">
          <Package className="h-5 w-5 text-blue-600" />
          <h3 className="font-semibold text-gray-900">{t('chapterGenerate.chapterMaterials')}</h3>
        </div>
      </div>
      <div className="p-4">
        <p className="text-sm text-gray-500 mb-4">
          {t('chapterGenerate.downloadMaterialsDesc')}
        </p>
        <ul className="text-sm text-gray-600 space-y-1 mb-4">
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
            {t('chapterGenerate.characterImages')}
          </li>
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            {t('chapterGenerate.mergedCharacterImage')}
          </li>
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
            {t('chapterGenerate.shotImages')}
          </li>
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-purple-400" />
            {t('chapterGenerate.shotVideos')}
          </li>
          <li className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-orange-400" />
            {t('chapterGenerate.transitionVideos')}
          </li>
        </ul>
        <button
          onClick={handleDownload}
          disabled={isDownloading}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isDownloading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('chapterGenerate.packing')}
            </>
          ) : (
            <>
              <Download className="h-4 w-4" />
              {t('chapterGenerate.downloadMaterials')}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
