/**
 * ThreeColumnLayout - 三栏布局容器
 *
 * 支持：
 * - 侧边栏可拖动调整宽度
 * - 侧边栏可收起/展开
 * - 中间区域自适应
 */

import React from 'react';
import { useChapterGenerateStore } from '../stores';
import { useResizable } from '../../../hooks/useResizable';

interface ThreeColumnLayoutProps {
  /** 左侧栏内容 */
  leftPanel: React.ReactNode;
  /** 中间内容 */
  centerContent: React.ReactNode;
  /** 右侧栏内容 */
  rightPanel: React.ReactNode;
  /** 左侧栏最小宽度 */
  minLeftWidth?: number;
  /** 左侧栏最大宽度 */
  maxLeftWidth?: number;
  /** 右侧栏最小宽度 */
  minRightWidth?: number;
  /** 右侧栏最大宽度 */
  maxRightWidth?: number;
}

export function ThreeColumnLayout({
  leftPanel,
  centerContent,
  rightPanel,
  minLeftWidth = 200,
  maxLeftWidth = 400,
  minRightWidth = 200,
  maxRightWidth = 350, // 调小右侧栏最大宽度，给中间更多空间
}: ThreeColumnLayoutProps) {
  const store = useChapterGenerateStore();

  const {
    leftPanelWidth,
    rightPanelWidth,
    leftPanelCollapsed,
    rightPanelCollapsed,
    setLeftPanelWidth,
    setRightPanelWidth,
    toggleLeftPanel,
    toggleRightPanel,
  } = store;

  // 左侧栏可拖动
  const leftResizable = useResizable({
    initialWidth: leftPanelWidth,
    minWidth: minLeftWidth,
    maxWidth: maxLeftWidth,
    collapsedWidth: 48,
    collapsed: leftPanelCollapsed,
    onWidthChange: setLeftPanelWidth,
    storageKey: 'chapterGenerate_leftPanelWidth',
  });

  // 右侧栏可拖动
  const rightResizable = useResizable({
    initialWidth: rightPanelWidth,
    minWidth: minRightWidth,
    maxWidth: maxRightWidth,
    collapsedWidth: 48,
    collapsed: rightPanelCollapsed,
    onWidthChange: setRightPanelWidth,
    storageKey: 'chapterGenerate_rightPanelWidth',
    direction: 'left', // 右侧栏：向左拖动增加宽度
  });

  // 获取面板实际显示宽度
  const getLeftWidth = () => {
    if (leftPanelCollapsed) return 48;
    return leftResizable.width;
  };

  const getRightWidth = () => {
    if (rightPanelCollapsed) return 48;
    return rightResizable.width;
  };

  return (
    <div className="flex h-full w-full">
      {/* 左侧栏 */}
      <div
        className="relative flex-shrink-0 transition-all duration-200 ease-in-out"
        style={{
          width: leftPanelCollapsed ? 48 : getLeftWidth(),
        }}
      >
        <div className="h-full overflow-hidden bg-gray-50 border-r border-gray-200">
          {/* 左侧栏内容 */}
          <div className={`h-full ${leftPanelCollapsed ? 'p-2' : 'p-4'}`}>
            {!leftPanelCollapsed && leftPanel}
          </div>
        </div>

        {/* 拖动把手 */}
        {!leftPanelCollapsed && (
          <div
            onMouseDown={leftResizable.handleMouseDown}
            className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-blue-200 hover:opacity-50 transition-colors"
          />
        )}

        {/* 收起/展开按钮 */}
        <button
          onClick={toggleLeftPanel}
          className="absolute -right-3 top-4 z-10 w-6 h-6 bg-white border border-gray-200 rounded-full shadow-sm flex items-center justify-center hover:bg-gray-50 transition-colors"
          title={leftPanelCollapsed ? '展开' : '收起'}
        >
          {leftPanelCollapsed ? (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          )}
        </button>
      </div>

      {/* 中间内容区域 */}
      <div className="flex-1 min-w-0 overflow-hidden" style={{ maxWidth: 'calc(100% - 96px)' }}>
        <div className="h-full overflow-auto">{centerContent}</div>
      </div>

      {/* 右侧栏 */}
      <div
        className="relative flex-shrink-0 transition-all duration-200 ease-in-out"
        style={{
          width: rightPanelCollapsed ? 48 : getRightWidth(),
        }}
      >
        <div className="h-full overflow-hidden bg-gray-50 border-l border-gray-200">
          {/* 右侧栏内容 */}
          <div className={`h-full ${rightPanelCollapsed ? 'p-2' : 'p-4'}`}>
            {!rightPanelCollapsed && rightPanel}
          </div>
        </div>

        {/* 拖动把手 */}
        {!rightPanelCollapsed && (
          <div
            onMouseDown={rightResizable.handleMouseDown}
            className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-blue-200 hover:opacity-50 transition-colors"
          />
        )}

        {/* 收起/展开按钮 */}
        <button
          onClick={toggleRightPanel}
          className="absolute -left-3 top-4 z-10 w-6 h-6 bg-white border border-gray-200 rounded-full shadow-sm flex items-center justify-center hover:bg-gray-50 transition-colors"
          title={rightPanelCollapsed ? '展开' : '收起'}
        >
          {rightPanelCollapsed ? (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}

export default ThreeColumnLayout;
