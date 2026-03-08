import { CheckCircle, Package, Eye } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from '../../../stores/i18nStore';
import type { ParsedData } from '../types';

interface PropImagesProps {
  parsedData: ParsedData | null;
  currentShot: number;
  novelAspectRatio: string;
  novelId: string | undefined;
  getPropImage: (name: string) => string | null;
  onRegenerateProp: (name: string) => void;
  aspectStyle: React.CSSProperties;
  activeShotWorkflow?: any;
  onImageClick?: (url: string) => void;
}

/**
 * 道具图片组件
 */
export function PropImages({
  parsedData,
  currentShot,
  novelAspectRatio,
  novelId,
  getPropImage,
  onRegenerateProp,
  aspectStyle,
  activeShotWorkflow,
  onImageClick,
}: PropImagesProps) {
  const { t } = useTranslation();

  // 检查工作流是否配置了道具参考图节点或自定义参考图节点
  const hasPropNode = !!activeShotWorkflow?.nodeMapping?.prop_reference_image_node_id;
  const hasCustomReferenceNode = Object.keys(activeShotWorkflow?.nodeMapping || {}).some(
    key => key.startsWith('custom_reference_image_node_') && activeShotWorkflow?.nodeMapping?.[key]
  );

  // 如果工作流没有配置道具参考图节点或自定义参考图节点，不显示组件
  if (!hasPropNode && !hasCustomReferenceNode) {
    return null;
  }

  const currentShotData = parsedData?.shots?.[currentShot - 1];
  const currentShotProps = currentShotData?.props || [];

  const sortedProps = [...(parsedData?.props || [])].sort((a: string, b: string) => {
    const aInShot = currentShotProps.includes(a);
    const bInShot = currentShotProps.includes(b);
    if (aInShot && !bInShot) return -1;
    if (!aInShot && bInShot) return 1;
    return 0;
  });

  return (
    <div className="card">
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-semibold text-gray-900">
          {t('chapterGenerate.propImages')}
          <span className="text-xs font-normal text-gray-500 ml-2">
            ({novelAspectRatio || '1:1'})
          </span>
        </h3>
        <Link
          to={`/props?novel=${novelId}`}
          className="text-sm text-amber-600 hover:text-amber-700 hover:underline flex items-center gap-1"
        >
          {t('chapterGenerate.aiGenerateProp')}
        </Link>
      </div>
      <div className="flex gap-4 flex-wrap">
        {sortedProps.length > 0 ? (
          sortedProps.map((name: string, idx: number) => {
            const imageUrl = getPropImage(name);
            const isInCurrentShot = currentShotProps.includes(name);

            return (
              <div key={idx} className={`text-center relative ${isInCurrentShot ? 'order-first' : ''}`}>
                <div
                  className={`rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center mb-2 overflow-hidden relative ${
                    isInCurrentShot ? 'ring-2 ring-amber-500 ring-offset-2' : ''
                  }`}
                  style={aspectStyle}
                >
                  {imageUrl ? (
                    <>
                      <img src={imageUrl} alt={name} className="w-full h-full object-cover" />
                      {/* 查看大图按钮 */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onImageClick?.(imageUrl);
                        }}
                        className="absolute top-2 right-2 p-1.5 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all"
                        title={t('common.viewLargeImage')}
                      >
                        <Eye className="h-4 w-4" />
                      </button>
                    </>
                  ) : (
                    <Package className="h-10 w-10 text-white" />
                  )}
                  {isInCurrentShot && (
                    <div className="absolute top-1 right-1 w-5 h-5 bg-amber-500 rounded-full flex items-center justify-center shadow-sm">
                      <CheckCircle className="h-3.5 w-3.5 text-white" />
                    </div>
                  )}
                </div>
                <p className="text-sm font-medium">{name}</p>
                <button
                  onClick={() => onRegenerateProp(name)}
                  className="text-xs text-amber-600 hover:underline mt-1"
                >
                  {t('chapterGenerate.regenerate')}
                </button>
              </div>
            );
          })
        ) : (
          <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noPropImages')}</p>
        )}
      </div>
    </div>
  );
}
