/**
 * TabNavigation - 四阶段工作流 Tab 导航
 *
 * 显示四个阶段的标签，支持：
 * - 显示阶段标签和图标
 * - 显示各阶段完成状态
 * - 点击切换 Tab
 * - 键盘导航 (1/2/3/4 键，不显示提示)
 */

import React from 'react';
import { Check, Image, Film, Mic, FileText } from 'lucide-react';
import { useChapterGenerateStore } from '../stores';
import { useTranslation } from '../../../stores/i18nStore';

export type StageTab = 'shot_split' | 'shot_image' | 'audio_gen' | 'video_gen';

interface TabConfig {
  key: StageTab;
  labelKey: string;
  icon: React.ReactNode;
  index: number;
}

const tabs: TabConfig[] = [
  {
    key: 'shot_split',
    labelKey: 'chapterGenerate.tabShotSplit',
    icon: <FileText className="w-4 h-4" />,
    index: 0,
  },
  {
    key: 'shot_image',
    labelKey: 'chapterGenerate.tabShotImage',
    icon: <Image className="w-4 h-4" />,
    index: 1,
  },
  {
    key: 'audio_gen',
    labelKey: 'chapterGenerate.tabAudioGen',
    icon: <Mic className="w-4 h-4" />,
    index: 2,
  },
  {
    key: 'video_gen',
    labelKey: 'chapterGenerate.tabVideoGen',
    icon: <Film className="w-4 h-4" />,
    index: 3,
  },
];

export function TabNavigation() {
  const { t } = useTranslation();
  const store = useChapterGenerateStore();

  const { currentTab, tabProgress, setCurrentTab, markTabComplete } = store;

  // 键盘导航
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
      return;
    }

    switch (e.key) {
      case '1':
        e.preventDefault();
        setCurrentTab(0);
        break;
      case '2':
        e.preventDefault();
        setCurrentTab(1);
        break;
      case '3':
        e.preventDefault();
        setCurrentTab(2);
        break;
      case '4':
        e.preventDefault();
        setCurrentTab(3);
        break;
    }
  };

  return (
    <div onKeyDown={handleKeyDown} tabIndex={0} className="outline-none">
      <div className="flex gap-2 mb-2 border-b border-gray-200">
        {tabs.map((tab) => {
          const isActive = currentTab === tab.index;
          const isCompleted = tabProgress[tab.index];

          return (
            <button
              key={tab.key}
              onClick={() => setCurrentTab(tab.index)}
              className={`
                flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-all relative
                ${
                  isActive
                    ? 'text-blue-600 bg-blue-50'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                }
                rounded-t-lg
              `}
            >
              {/* 图标 */}
              <span className={isActive ? 'text-blue-600' : 'text-gray-400'}>
                {React.cloneElement(tab.icon as React.ReactElement, { className: 'w-3.5 h-3.5' })}
              </span>

              {/* 标签 */}
              <span>{t(tab.labelKey)}</span>

              {/* 完成状态标记 */}
              {isCompleted && (
                <Check className="w-3.5 h-3.5 text-green-500 ml-0.5" />
              )}

              {/* 激活指示器 */}
              {isActive && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default TabNavigation;
