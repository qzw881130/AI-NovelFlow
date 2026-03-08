/**
 * ShotThumbnail - 分镜缩略图组件
 *
 * 支持：
 * - 显示预览图或占位符
 * - 显示分镜编号和状态
 * - 支持点击/双击/右键
 */

import { useState } from 'react';
import { Film, Loader2, AlertCircle, CheckCircle, Eye } from 'lucide-react';

export type ShotStatus = 'pending' | 'generating' | 'completed' | 'failed' | 'current';

export interface ShotThumbnailProps {
  /** 分镜 ID */
  shotId: string;
  /** 分镜索引 */
  index: number;
  /** 缩略图 URL */
  thumbnailUrl?: string | null;
  /** 分镜状态 */
  status: ShotStatus;
  /** 是否被选中（批量模式） */
  isSelected?: boolean;
  /** 点击回调 */
  onClick?: () => void;
  /** 双击回调 */
  onDoubleClick?: () => void;
  /** 右键回调 */
  onContextMenu?: () => void;
  /** 查看大图回调 */
  onViewLarge?: () => void;
}

export function ShotThumbnail({
  shotId,
  index,
  thumbnailUrl,
  status,
  isSelected = false,
  onClick,
  onDoubleClick,
  onContextMenu,
  onViewLarge,
}: ShotThumbnailProps) {
  const [imageError, setImageError] = useState(false);

  // 状态配置
  const statusConfig: Record<ShotStatus, { color: string; icon: React.ReactNode; label: string }> = {
    pending: {
      color: 'border-gray-300 bg-gray-100',
      icon: <Film className="w-6 h-6 text-gray-400" />,
      label: '待生成',
    },
    generating: {
      color: 'border-blue-400 bg-blue-50',
      icon: <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />,
      label: '生成中',
    },
    completed: {
      color: 'border-green-400 bg-green-50',
      icon: <CheckCircle className="w-6 h-6 text-green-500" />,
      label: '已完成',
    },
    failed: {
      color: 'border-red-400 bg-red-50',
      icon: <AlertCircle className="w-6 h-6 text-red-500" />,
      label: '失败',
    },
    current: {
      color: 'border-blue-500 bg-blue-100',
      icon: <Film className="w-6 h-6 text-blue-600" />,
      label: '当前',
    },
  };

  const config = statusConfig[status];

  // 处理右键菜单
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    onContextMenu?.();
  };

  return (
    <div
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={handleContextMenu}
      className={`
        relative flex-shrink-0 w-32 h-24 rounded-lg border-2 cursor-pointer
        transition-all duration-200 overflow-hidden
        ${config.color}
        ${isSelected ? 'ring-2 ring-blue-500 ring-offset-2' : 'hover:shadow-md'}
      `}
    >
      {/* 图片显示 */}
      {thumbnailUrl && !imageError ? (
        <>
          <img
            src={thumbnailUrl}
            alt={`分镜${index}`}
            className="w-full h-full object-cover"
            onError={() => setImageError(true)}
          />
          {/* 查看大图按钮 - 右上角眼睛图标 */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onViewLarge?.();
            }}
            className="absolute top-1 right-1 p-1.5 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all"
            title="查看大图"
          >
            <Eye className="h-4 w-4" />
          </button>
        </>
      ) : (
        /* 占位符 */
        <div className="w-full h-full flex flex-col items-center justify-center">
          {config.icon}
          <span className="text-xs text-gray-500 mt-1">{config.label}</span>
        </div>
      )}

      {/* 分镜编号 */}
      <div className="absolute top-1 left-1 px-2 py-0.5 bg-black/60 text-white text-xs rounded">
        #{index}
      </div>

      {/* 选中状态标记 */}
      {isSelected && (
        <div className="absolute top-1 right-1 w-5 h-5 bg-blue-500 rounded-full flex items-center justify-center">
          <CheckCircle className="w-4 h-4 text-white" />
        </div>
      )}

      {/* 状态指示器（底部） */}
      <div className={`absolute bottom-0 left-0 right-0 h-1 ${status === 'completed' ? 'bg-green-500' : status === 'generating' ? 'bg-blue-500' : 'bg-gray-300'}`} />
    </div>
  );
}

export default ShotThumbnail;
