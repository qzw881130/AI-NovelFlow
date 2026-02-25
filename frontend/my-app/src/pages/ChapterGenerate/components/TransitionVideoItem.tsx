import { Loader2 } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { TransitionVideoItemProps } from '../types';

export default function TransitionVideoItem({
  fromIndex,
  toIndex,
  fromVideo,
  toVideo,
  fromImage,
  toImage,
  transitionVideo,
  isGenerating,
  onGenerate,
  onRegenerate,
  onClick,
  isActive
}: TransitionVideoItemProps) {
  const { t } = useTranslation();
  const hasVideos = !!fromVideo && !!toVideo;
  const hasTransition = !!transitionVideo;
  
  return (
    <div 
      className={`relative flex-shrink-0 flex flex-col items-center gap-1 ${isActive ? 'opacity-100' : 'opacity-80 hover:opacity-100'}`}
    >
      {/* 转场缩略图 */}
      <div
        onClick={hasTransition ? onClick : undefined}
        className={`relative w-16 h-16 rounded-lg overflow-hidden cursor-pointer transition-all ${
          isActive ? 'ring-2 ring-offset-2 ring-orange-500' : ''
        } ${!hasTransition ? 'grayscale' : ''}`}
      >
        {/* 两张图片拼接 */}
        <div className="flex h-full">
          <div className="w-1/2 relative">
            {fromImage ? (
              <img src={fromImage} alt={`镜${fromIndex}`} className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full bg-gray-200" />
            )}
            <div className="absolute bottom-0 left-0 bg-black/60 text-white text-[8px] px-1">
              {fromIndex}
            </div>
          </div>
          <div className="w-1/2 relative">
            {toImage ? (
              <img src={toImage} alt={`镜${toIndex}`} className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full bg-gray-200" />
            )}
            <div className="absolute bottom-0 right-0 bg-black/60 text-white text-[8px] px-1">
              {toIndex}
            </div>
          </div>
        </div>
        
        {/* 箭头覆盖层 */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className={`rounded-full p-1 ${hasTransition ? 'bg-orange-500' : 'bg-gray-400'}`}>
            <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </div>
        </div>
        
        {/* 生成中状态 */}
        {isGenerating && (
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
            <Loader2 className="h-5 w-5 text-white animate-spin" />
          </div>
        )}
      </div>
      
      {/* 状态标签 */}
      <div className="flex flex-col items-center gap-0.5">
        {hasTransition ? (
          <div className="flex flex-col items-center gap-0.5">
            <span className="text-[9px] text-green-600 font-medium">{t('chapterGenerate.generated')}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRegenerate?.();
              }}
              disabled={isGenerating}
              className="text-[9px] bg-orange-500 text-white px-2 py-0.5 rounded hover:bg-orange-600 disabled:opacity-50 transition-colors"
              title={t('chapterGenerate.regenerateTransition')}
            >
              {t('chapterGenerate.regenerate')}
            </button>
          </div>
        ) : isGenerating ? (
          <span className="text-[9px] text-orange-600">{t('chapterGenerate.generating')}</span>
        ) : (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onGenerate();
            }}
            disabled={!hasVideos || isGenerating}
            className="text-[9px] bg-orange-500 text-white px-2 py-0.5 rounded hover:bg-orange-600 disabled:opacity-50 disabled:bg-gray-300 transition-colors"
            title={!hasVideos ? t('chapterGenerate.generateVideoFirst') : t('chapterGenerate.generateTransitionVideo')}
          >
            {t('chapterGenerate.generate')}
          </button>
        )}
      </div>
    </div>
  );
}
