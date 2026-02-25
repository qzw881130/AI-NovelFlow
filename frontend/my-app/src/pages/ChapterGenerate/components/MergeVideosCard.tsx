import { useState } from 'react';
import { Loader2, Film } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { API_BASE } from '../constants';
import type { MergeVideosCardProps } from '../types';

export default function MergeVideosCard({
  novelId,
  chapterId,
  shotVideos,
  transitionVideos,
  chapter,
  aspectRatio = '16:9'
}: MergeVideosCardProps) {
  const { t } = useTranslation();
  const [isMerging, setIsMerging] = useState(false);
  const [mergedVideoUrl, setMergedVideoUrl] = useState<string | null>(null);
  const [includeTransitions, setIncludeTransitions] = useState(true);

  const videoList = Object.values(shotVideos).filter(Boolean);
  const hasVideos = videoList.length > 0;
  const hasTransitions = Object.keys(transitionVideos).length > 0;

  const handleMerge = async () => {
    if (!novelId || !chapterId || videoList.length === 0) {
      toast.error(t('chapterGenerate.noVideosToMerge'));
      return;
    }

    setIsMerging(true);
    try {
      const response = await fetch(
        `${API_BASE}/novels/${novelId}/chapters/${chapterId}/merge-videos/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ include_transitions: includeTransitions })
        }
      );

      const data = await response.json();
      
      if (data.success) {
        setMergedVideoUrl(data.video_url);
        toast.success(t('chapterGenerate.mergeSuccess'));
      } else {
        toast.error(data.message || t('chapterGenerate.mergeFailed'));
      }
    } catch (error) {
      console.error('Merge error:', error);
      toast.error(t('chapterGenerate.mergeFailed'));
    } finally {
      setIsMerging(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="p-4 border-b border-gray-100 bg-gradient-to-r from-purple-50 to-pink-50">
        <div className="flex items-center gap-2">
          <Film className="h-5 w-5 text-purple-600" />
          <h3 className="font-semibold text-gray-900">{t('chapterGenerate.mergeVideo')}</h3>
        </div>
      </div>
      <div className="p-4">
        {!hasVideos ? (
          <p className="text-sm text-gray-500">{t('chapterGenerate.noShotVideos')}</p>
        ) : (
          <>
            <p className="text-sm text-gray-500 mb-3">
              {t('chapterGenerate.generatedVideoCount', { count: videoList.length })}
              {hasTransitions && t('chapterGenerate.generatedTransitionCount', { count: Object.keys(transitionVideos).length })}
            </p>
            
            {/* 选项 */}
            <div className="space-y-2 mb-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={!includeTransitions}
                  onChange={() => setIncludeTransitions(false)}
                  className="w-4 h-4 text-purple-600"
                />
                <span className="text-sm text-gray-700">{t('chapterGenerate.mergeShotsOnly')}</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={includeTransitions}
                  onChange={() => setIncludeTransitions(true)}
                  disabled={!hasTransitions}
                  className="w-4 h-4 text-purple-600 disabled:opacity-50"
                />
                <span className={`text-sm ${hasTransitions ? 'text-gray-700' : 'text-gray-400'}`}>
                  {t('chapterGenerate.mergeShotsAndTransitions')}
                </span>
              </label>
            </div>

            {/* 合并按钮 */}
            <button
              onClick={handleMerge}
              disabled={isMerging}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isMerging ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('chapterGenerate.merging')}
                </>
              ) : (
                <>
                  <Film className="h-4 w-4" />
                  {includeTransitions ? t('chapterGenerate.mergeShotsAndTransitions') : t('chapterGenerate.mergeShotsOnly')}
                </>
              )}
            </button>

            {/* 合并后的视频播放器 */}
            {mergedVideoUrl && (
              <div className="mt-4 pt-4 border-t border-gray-100">
                <p className="text-sm font-medium text-gray-700 mb-2">{t('chapterGenerate.mergeResult')}</p>
                <video
                  src={mergedVideoUrl}
                  controls
                  className="w-full rounded-lg bg-gray-900"
                  style={{ aspectRatio: aspectRatio === '9:16' ? '9/16' : '16/9' }}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
