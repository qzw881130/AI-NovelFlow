/**
 * ResourcePanel - 资源面板组件（用于分镜图生成 Tab 左侧）
 *
 * 显示：
 * - 当前分镜的角色、场景、道具
 * - 重新生成按钮跳转到对应的资源库页面
 */

import { Users, MapPin, Package, RefreshCw, Eye } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useParams } from 'react-router-dom';
import { useTranslation } from '../../../stores/i18nStore';

interface ResourceItem {
  id: string;
  name: string;
  imageUrl?: string | null;
  type: 'character' | 'scene' | 'prop';
}

interface ResourcePanelProps {
  /** 当前分镜数据 */
  currentShot?: any;
  /** 获取角色图片方法 */
  getCharacterImage?: (name: string) => string | undefined;
  /** 获取场景图片方法 */
  getSceneImage?: (name: string) => string | null;
  /** 获取道具图片方法 */
  getPropImage?: (name: string) => string | null;
  /** 图片点击查看大图回调 */
  onImageClick?: (url: string) => void;
}

export function ResourcePanel({
  currentShot,
  getCharacterImage,
  getSceneImage,
  getPropImage,
  onImageClick,
}: ResourcePanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();

  // 获取当前分镜使用的资源
  // 注意：分镜数据结构中字段在根级别，不在 parsed_data 中
  const currentShotCharacters = currentShot?.characters || [];
  const currentShotScene = currentShot?.scene;
  const currentShotProps = currentShot?.props || [];

  // 跳转到资源库页面重新生成
  const handleRegenerate = (type: 'character' | 'scene' | 'prop') => {
    switch (type) {
      case 'character':
        navigate(`/characters`);
        break;
      case 'scene':
        navigate(`/scenes`);
        break;
      case 'prop':
        navigate(`/props`);
        break;
    }
  };

  // 渲染资源项
  const renderResourceItem = (item: ResourceItem) => {
    const imageUrl =
      item.type === 'character'
        ? getCharacterImage?.(item.name)
        : item.type === 'scene'
        ? getSceneImage?.(item.name)
        : getPropImage?.(item.name);

    return (
      <div
        key={item.id}
        className="p-3 rounded-lg border border-gray-200 bg-white hover:border-blue-300 transition-all"
      >
        <div className="flex items-center gap-3">
          {/* 缩略图 */}
          <div className="relative w-20 h-20 rounded bg-gray-100 overflow-hidden flex-shrink-0">
            {imageUrl ? (
              <>
                <img src={imageUrl} alt={item.name} className="w-full h-full object-cover" />
                {/* 查看大图按钮 - 始终显示 */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onImageClick?.(imageUrl);
                  }}
                  className="absolute top-1 right-1 p-1.5 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all"
                  title={t('common.viewLargeImage')}
                >
                  <Eye className="h-4 w-4" />
                </button>
              </>
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-400">
                {item.type === 'character' && <Users className="w-8 h-8" />}
                {item.type === 'scene' && <MapPin className="w-8 h-8" />}
                {item.type === 'prop' && <Package className="w-8 h-8" />}
              </div>
            )}
          </div>

          {/* 名称 */}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-700 truncate">
              {item.name}
            </p>
          </div>
        </div>
      </div>
    );
  };

  // 构建资源列表
  const characterItems: ResourceItem[] = currentShotCharacters.map((name: string) => ({
    id: name,
    name,
    type: 'character',
  }));

  const sceneItems: ResourceItem[] = currentShotScene
    ? [{ id: currentShotScene, name: currentShotScene, type: 'scene' }]
    : [];

  const propItems: ResourceItem[] = currentShotProps.map((name: string) => ({
    id: name,
    name,
    type: 'prop',
  }));

  const hasResources = characterItems.length > 0 || sceneItems.length > 0 || propItems.length > 0;

  return (
    <div className="h-full flex flex-col">
      {/* 标题 */}
      <div className="flex-shrink-0 pb-3 border-b border-gray-200">
        <h3 className="text-sm font-semibold text-gray-700">{t('chapterGenerate.shotResources')}</h3>
      </div>

      {/* 资源列表 */}
      <div className="flex-1 overflow-y-auto space-y-4">
        {!hasResources ? (
          <div className="text-center text-gray-400 text-sm py-8">
            {t('chapterGenerate.noResourcesInShot')}
          </div>
        ) : (
          <>
            {/* 角色列表 */}
            {characterItems.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2 text-sm font-medium text-gray-700">
                  <div className="flex items-center gap-2">
                    <Users className="w-4 h-4 text-blue-500" />
                    {t('chapterGenerate.characters')} ({characterItems.length})
                  </div>
                  <button
                    onClick={() => handleRegenerate('character')}
                    className="text-xs text-gray-500 hover:text-blue-600 flex items-center gap-1"
                    title={t('chapterGenerate.goToCharacterLibrary')}
                  >
                    <RefreshCw className="w-3 h-3" />
                    {t('common.regenerate')}
                  </button>
                </div>
                <div className="space-y-2">
                  {characterItems.map((item) => renderResourceItem(item))}
                </div>
              </div>
            )}

            {/* 场景列表 */}
            {sceneItems.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2 text-sm font-medium text-gray-700">
                  <div className="flex items-center gap-2">
                    <MapPin className="w-4 h-4 text-green-500" />
                    {t('chapterGenerate.scene')} ({sceneItems.length})
                  </div>
                  <button
                    onClick={() => handleRegenerate('scene')}
                    className="text-xs text-gray-500 hover:text-blue-600 flex items-center gap-1"
                    title={t('chapterGenerate.goToSceneLibrary')}
                  >
                    <RefreshCw className="w-3 h-3" />
                    {t('common.regenerate')}
                  </button>
                </div>
                <div className="space-y-2">
                  {sceneItems.map((item) => renderResourceItem(item))}
                </div>
              </div>
            )}

            {/* 道具列表 */}
            {propItems.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2 text-sm font-medium text-gray-700">
                  <div className="flex items-center gap-2">
                    <Package className="w-4 h-4 text-purple-500" />
                    {t('chapterGenerate.props')} ({propItems.length})
                  </div>
                  <button
                    onClick={() => handleRegenerate('prop')}
                    className="text-xs text-gray-500 hover:text-blue-600 flex items-center gap-1"
                    title={t('chapterGenerate.goToPropLibrary')}
                  >
                    <RefreshCw className="w-3 h-3" />
                    {t('common.regenerate')}
                  </button>
                </div>
                <div className="space-y-2">
                  {propItems.map((item) => renderResourceItem(item))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default ResourcePanel;
