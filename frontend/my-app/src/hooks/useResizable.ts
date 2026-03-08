/**
 * useResizable Hook - 可拖动调整宽度的 Hook
 *
 * 处理侧边栏拖动逻辑，支持：
 * - 鼠标按下开始拖动
 * - 鼠标移动调整宽度
 * - 鼠标释放结束拖动
 * - 限制最小/最大宽度
 */

import { useState, useCallback, useEffect } from 'react';

export interface UseResizableOptions {
  /** 初始宽度 */
  initialWidth: number;
  /** 最小宽度 */
  minWidth: number;
  /** 最大宽度 */
  maxWidth: number;
  /** 收起时的宽度 */
  collapsedWidth?: number;
  /** 是否收起 */
  collapsed?: boolean;
  /** 宽度变化回调 */
  onWidthChange?: (width: number) => void;
  /** localStorage key */
  storageKey?: string;
  /** 拖动方向：right 表示向右拖动增加宽度（左侧栏），left 表示向左拖动增加宽度（右侧栏） */
  direction?: 'left' | 'right';
}

export interface UseResizableReturn {
  /** 当前宽度 */
  width: number;
  /** 是否正在拖动 */
  isDragging: boolean;
  /** 开始拖动处理函数 */
  handleMouseDown: (e: React.MouseEvent) => void;
  /** 设置宽度 */
  setWidth: (width: number) => void;
  /** 停止拖动（供外部调用） */
  stopDragging: () => void;
}

/**
 * useResizable Hook
 */
export function useResizable({
  initialWidth,
  minWidth,
  maxWidth,
  collapsedWidth = 48,
  collapsed: externalCollapsed = false,
  onWidthChange,
  storageKey,
  direction = 'right', // 默认向右拖动增加宽度
}: UseResizableOptions): UseResizableReturn {
  // 尝试从 localStorage 恢复宽度
  const getStoredWidth = (): number => {
    if (!storageKey) return initialWidth;
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        const parsed = JSON.parse(stored);
        return Math.max(minWidth, Math.min(maxWidth, parsed));
      }
    } catch (e) {
      console.warn('Failed to restore width from localStorage:', e);
    }
    return initialWidth;
  };

  const [width, setWidthState] = useState<number>(getStoredWidth);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [startX, setStartX] = useState<number>(0);
  const [startWidth, setStartWidth] = useState<number>(0);

  // 设置宽度并保存到 localStorage
  const setWidth = useCallback(
    (newWidth: number) => {
      const clampedWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));
      setWidthState(clampedWidth);
      if (storageKey) {
        try {
          localStorage.setItem(storageKey, JSON.stringify(clampedWidth));
        } catch (e) {
          console.warn('Failed to save width to localStorage:', e);
        }
      }
      onWidthChange?.(clampedWidth);
    },
    [minWidth, maxWidth, storageKey, onWidthChange]
  );

  // 处理外部收起状态变化
  useEffect(() => {
    if (externalCollapsed) {
      setWidthState(collapsedWidth);
    } else {
      setWidthState(width); // 恢复到最后记录的宽度
    }
  }, [externalCollapsed, collapsedWidth]);

  // 鼠标按下开始拖动
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      setStartX(e.clientX);
      setStartWidth(width);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    [width]
  );

  // 鼠标移动调整宽度
  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - startX;
      // 右侧栏时，向左拖动应该增加宽度，所以需要反向计算
      const newWidth = direction === 'right' ? startWidth + deltaX : startWidth - deltaX;
      setWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, startX, startWidth, setWidth]);

  // 停止拖动
  const stopDragging = useCallback(() => {
    setIsDragging(false);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  return {
    width: externalCollapsed ? collapsedWidth : width,
    isDragging,
    handleMouseDown,
    setWidth: externalCollapsed ? () => {} : setWidth,
    stopDragging,
  };
}

export default useResizable;
