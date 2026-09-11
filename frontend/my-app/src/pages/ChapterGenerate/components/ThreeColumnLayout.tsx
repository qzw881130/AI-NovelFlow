/**
 * ThreeColumnLayout - 三栏布局容器
 *
 * 支持：
 * - 侧边栏可拖动调整宽度
 * - 侧边栏可收起/展开
 * - 中间区域自适应
 */

import React, { useEffect, useState } from 'react';
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
  minRightWidth = 320,
  maxRightWidth = 440,
}: ThreeColumnLayoutProps) {
  const store = useChapterGenerateStore();
  const hasRightPanel = rightPanel !== null && rightPanel !== undefined;
  const [mobilePanel, setMobilePanel] = useState('editor');

  // Section changes only affect visibility, never editor drafts or saved desktop sizes.
  useEffect(() => setMobilePanel('editor'), [store.currentTab, store.currentShotId]);

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
    collapsedWidth: 0,
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
    if (!hasRightPanel) return 0;
    if (rightPanelCollapsed) return 0;
    return rightResizable.width;
  };

  return (
    <div className="generate-columns flex h-full w-full flex-wrap content-start gap-y-4 overflow-auto px-3" data-mobile-panel={mobilePanel}>
      <div className="generate-section-switch flex w-full gap-2 lg:hidden" role="group" aria-label="工作区">
        {[
          ['editor', hasRightPanel ? '编辑分镜' : '生成工作区'],
          ...(hasRightPanel ? [['list', '分镜列表']] : []),
          ['source', hasRightPanel ? '章节原文' : '分镜资源'],
        ].map(([key, label]) => (
          <button key={key} type="button" aria-pressed={mobilePanel === key} onClick={() => setMobilePanel(key)}
            className={`flex-1 rounded-lg border px-2 py-2 text-sm ${mobilePanel === key ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-gray-200 bg-white text-gray-600'}`}>
            {label}
          </button>
        ))}
      </div>
      {/* 左侧栏 */}
      <div
        className="generate-side-panel relative h-full max-w-full flex-shrink-0 transition-all duration-200 ease-in-out"
        data-panel="source"
        data-desktop-collapsed={leftPanelCollapsed}
        style={{
          width: leftPanelCollapsed ? 48 : getLeftWidth(),
        }}
      >
        <div className="h-full overflow-hidden bg-gray-50 border-r border-gray-200">
          {/* 左侧栏内容 */}
          <div className={`generate-panel-content h-full ${leftPanelCollapsed ? 'p-2' : 'px-2 py-4'}`}>
            {leftPanel}
          </div>
        </div>

        {/* 拖动把手 */}
        {!leftPanelCollapsed && (
          <div
            onMouseDown={leftResizable.handleMouseDown}
            className="hidden lg:block absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-blue-200 hover:opacity-50 transition-colors"
          />
        )}

        {/* 收起/展开按钮 */}
        <button
          onClick={toggleLeftPanel}
          className="hidden lg:flex absolute -right-3 top-4 z-10 w-6 h-6 bg-white border border-gray-200 rounded-full shadow-sm items-center justify-center hover:bg-gray-50 transition-colors"
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
      {/* Keep a usable center width; move side panels to another row when they do not fit. */}
      <div className="generate-center-panel h-full min-w-[min(20rem,100%)] flex-1 overflow-hidden" data-panel={hasRightPanel ? 'list' : 'editor'}>
        <div className="h-full overflow-hidden px-4">{centerContent}</div>
      </div>

      {/* 右侧栏 */}
      {hasRightPanel && (
        <div
          className="generate-side-panel relative h-full max-w-full flex-shrink-0 transition-all duration-200 ease-in-out"
          data-panel="editor"
          data-desktop-collapsed={rightPanelCollapsed}
          style={{
            width: getRightWidth(),
          }}
        >
          <div className={`h-full overflow-hidden bg-gray-50 ${rightPanelCollapsed ? '' : 'border-l border-gray-200'}`}>
            {/* 右侧栏内容 */}
            <div className="generate-panel-content h-full pl-4 pr-2 py-4">
              {rightPanel}
            </div>
          </div>

          {/* 拖动把手 */}
          {!rightPanelCollapsed && (
            <div
              onMouseDown={rightResizable.handleMouseDown}
              className="hidden lg:block absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-blue-200 hover:opacity-50 transition-colors"
            />
          )}

          {/* 收起/展开按钮 */}
          <button
            onClick={toggleRightPanel}
            className="hidden lg:flex absolute -left-3 top-12 z-10 w-6 h-6 bg-white border border-gray-200 rounded-full shadow-sm items-center justify-center hover:bg-gray-50 transition-colors"
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
      )}
    </div>
  );
}

export default ThreeColumnLayout;
