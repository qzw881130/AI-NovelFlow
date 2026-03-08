import { CheckCircle, MapPin, Eye } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from '../../../stores/i18nStore';
import type { ParsedData } from '../types';

interface SceneImagesProps {
  parsedData: ParsedData | null;
  currentShot: number;
  novelAspectRatio: string;
  novelId: string | undefined;
  getSceneImage: (name: string) => string | null;
  onRegenerateScene: (name: string) => void;
  onImageClick?: (url: string) => void;
  aspectStyle: React.CSSProperties;
  activeShotWorkflow?: any;
}

/**
 * 场景图片组件
 */
export function SceneImages({
  parsedData,
  currentShot,
  novelAspectRatio,
  novelId,
  getSceneImage,
  onRegenerateScene,
  onImageClick,
  aspectStyle,
  activeShotWorkflow,
}: SceneImagesProps) {
  const { t } = useTranslation();

  // 检查工作流是否配置了场景参考图节点
  const hasSceneNode = !!activeShotWorkflow?.nodeMapping?.scene_reference_image_node_id;

  // 如果工作流没有配置场景参考图节点，不显示组件
  if (!hasSceneNode) {
    return null;
  }

  const currentShotData = parsedData?.shots?.[currentShot - 1];
  const currentShotScene = currentShotData?.scene || '';

  const sortedScenes = [...(parsedData?.scenes || [])].sort((a: string, b: string) => {
    const aInShot = a === currentShotScene;
    const bInShot = b === currentShotScene;
    if (aInShot && !bInShot) return -1;
    if (!aInShot && bInShot) return 1;
    return 0;
  });

  return (
    <div className="card">
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-semibold text-gray-900">
          {t('chapterGenerate.sceneImages')}
          <span className="text-xs font-normal text-gray-500 ml-2">
            ({novelAspectRatio || '16:9'})
          </span>
        </h3>
        <Link
          to={`/scenes?novel_id=${novelId}`}
          className="text-sm text-green-600 hover:text-green-700 hover:underline flex items-center gap-1"
        >
          {t('chapterGenerate.aiGenerateScene')}
        </Link>
      </div>

      <div className="flex gap-4 flex-wrap">
        {sortedScenes.length > 0 ? (
          sortedScenes.map((name: string, idx: number) => {
            const imageUrl = getSceneImage(name);
            const isInCurrentShot = name === currentShotScene;

            return (
              <div key={idx} className={`text-center relative ${isInCurrentShot ? 'order-first' : ''}`}>
                <div
                  className={`rounded-xl bg-gradient-to-br from-green-400 to-teal-500 flex items-center justify-center mb-2 overflow-hidden relative cursor-pointer ${
                    isInCurrentShot ? 'ring-2 ring-green-500 ring-offset-2' : ''
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
                    <MapPin className="h-10 w-10 text-white" />
                  )}
                  {isInCurrentShot && (
                    <div className="absolute top-1 right-1 w-5 h-5 bg-green-500 rounded-full flex items-center justify-center shadow-sm">
                      <CheckCircle className="h-3.5 w-3.5 text-white" />
                    </div>
                  )}
                </div>
                <p className="text-sm font-medium">{name}</p>
                <button
                  onClick={() => onRegenerateScene(name)}
                  className="text-xs text-green-600 hover:underline mt-1"
                >
                  {t('chapterGenerate.regenerate')}
                </button>
              </div>
            );
          })
        ) : (
          <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noSceneImages')}</p>
        )}
      </div>
    </div>
  );
}
