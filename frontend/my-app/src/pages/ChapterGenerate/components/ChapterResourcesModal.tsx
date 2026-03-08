/**
 * ChapterResourcesModal - 章节资源管理弹窗
 *
 * 功能：
 * - 显示当前章节已选资源（角色/场景/道具）
 * - 支持下拉多选资源（搜索用于过滤列表）
 * - 移除已选资源
 * - 保存章节资源
 */

import { useState, useMemo, useRef, useEffect } from 'react';
import { X, ChevronDown, Check } from 'lucide-react';
import { useChapterGenerateStore } from '../stores';
import { useTranslation } from '../../../stores/i18nStore';

interface ChapterResourcesModalProps {
  isOpen: boolean;
  onClose: () => void;
  novelId?: string;
  chapterId?: string;
}

export function ChapterResourcesModal({
  isOpen,
  onClose,
  novelId,
  chapterId,
}: ChapterResourcesModalProps) {
  const { t } = useTranslation();
  const store = useChapterGenerateStore();

  // 从 store 获取数据
  const characters = useChapterGenerateStore((state) => state.characters);
  const scenes = useChapterGenerateStore((state) => state.scenes);
  const props = useChapterGenerateStore((state) => state.props);

  const chapterCharacters = useChapterGenerateStore((state) => state.chapterCharacters);
  const chapterScenes = useChapterGenerateStore((state) => state.chapterScenes);
  const chapterProps = useChapterGenerateStore((state) => state.chapterProps);

  const addResourceToChapter = useChapterGenerateStore((state) => state.addResourceToChapter);
  const removeResourceFromChapter = useChapterGenerateStore((state) => state.removeResourceFromChapter);
  const saveChapterResources = useChapterGenerateStore((state) => state.saveChapterResources);

  // 下拉框展开状态
  const [characterDropdownOpen, setCharacterDropdownOpen] = useState(false);
  const [sceneDropdownOpen, setSceneDropdownOpen] = useState(false);
  const [propDropdownOpen, setPropDropdownOpen] = useState(false);

  // 搜索状态（用于过滤下拉列表）
  const [characterSearch, setCharacterSearch] = useState('');
  const [sceneSearch, setSceneSearch] = useState('');
  const [propSearch, setPropSearch] = useState('');

  // Refs 用于点击外部关闭下拉
  const characterDropdownRef = useRef<HTMLDivElement>(null);
  const sceneDropdownRef = useRef<HTMLDivElement>(null);
  const propDropdownRef = useRef<HTMLDivElement>(null);

  // 保存状态
  const [isSaving, setIsSaving] = useState(false);

  // 点击外部关闭下拉
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (characterDropdownRef.current && !characterDropdownRef.current.contains(event.target as Node)) {
        setCharacterDropdownOpen(false);
      }
      if (sceneDropdownRef.current && !sceneDropdownRef.current.contains(event.target as Node)) {
        setSceneDropdownOpen(false);
      }
      if (propDropdownRef.current && !propDropdownRef.current.contains(event.target as Node)) {
        setPropDropdownOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // 过滤后的选项（排除已选的，支持搜索过滤）
  const availableCharacters = useMemo(() => {
    return characters.filter(
      (c) =>
        !chapterCharacters.includes(c.name) &&
        c.name.toLowerCase().includes(characterSearch.toLowerCase())
    );
  }, [characters, chapterCharacters, characterSearch]);

  const availableScenes = useMemo(() => {
    return scenes.filter(
      (s) =>
        !chapterScenes.includes(s.name) &&
        s.name.toLowerCase().includes(sceneSearch.toLowerCase())
    );
  }, [scenes, chapterScenes, sceneSearch]);

  const availableProps = useMemo(() => {
    return props.filter(
      (p) =>
        !chapterProps.includes(p.name) &&
        p.name.toLowerCase().includes(propSearch.toLowerCase())
    );
  }, [props, chapterProps, propSearch]);

  // 处理添加资源
  const handleAddResource = (type: 'character' | 'scene' | 'prop', name: string) => {
    addResourceToChapter(type, name);
    // 清空搜索以便继续选择
    if (type === 'character') setCharacterSearch('');
    else if (type === 'scene') setSceneSearch('');
    else setPropSearch('');
  };

  // 处理移除资源
  const handleRemoveResource = (type: 'character' | 'scene' | 'prop', name: string) => {
    removeResourceFromChapter(type, name);
  };

  // 处理保存
  const handleSave = async () => {
    if (!novelId || !chapterId) return;

    setIsSaving(true);
    try {
      await saveChapterResources(novelId, chapterId);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  // 切换下拉框
  const toggleDropdown = (type: 'character' | 'scene' | 'prop') => {
    if (type === 'character') {
      setCharacterDropdownOpen(!characterDropdownOpen);
      setCharacterSearch(''); // 打开时清空搜索
    } else if (type === 'scene') {
      setSceneDropdownOpen(!sceneDropdownOpen);
      setSceneSearch('');
    } else {
      setPropDropdownOpen(!propDropdownOpen);
      setPropSearch('');
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl h-[95vh] overflow-hidden flex flex-col">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 flex-shrink-0">
          <h2 className="text-lg font-semibold text-gray-900">{t('chapterGenerate.chapterResourceManagement')}</h2>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-3 gap-6">
            {/* 角色管理 */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <span className="w-2 h-2 bg-blue-500 rounded-full" />
                {t('chapterGenerate.characters')}
              </h3>

              {/* 已选角色 */}
              <div className="border border-gray-200 rounded-lg p-3 min-h-[200px] max-h-[300px] overflow-y-auto">
                <p className="text-xs text-gray-500 mb-2">{t('chapterGenerate.selectedCharacters', { count: chapterCharacters.length })}</p>
                <div className="flex flex-wrap gap-1">
                  {chapterCharacters.map((name) => (
                    <span
                      key={name}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-700 rounded text-xs"
                    >
                      {name}
                      <button
                        onClick={() => handleRemoveResource('character', name)}
                        className="text-blue-400 hover:text-blue-600 transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                  {chapterCharacters.length === 0 && (
                    <p className="text-sm text-gray-400 text-center py-4">{t('chapterGenerate.noCharacters')}</p>
                  )}
                </div>
              </div>

              {/* 下拉多选框 */}
              <div className="relative" ref={characterDropdownRef}>
                <button
                  onClick={() => toggleDropdown('character')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center justify-between"
                >
                  <span>{characterDropdownOpen ? t('chapterGenerate.clickToClose') : t('chapterGenerate.addCharacter')}</span>
                  <ChevronDown className={`w-4 h-4 transition-transform ${characterDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {/* 下拉选项 */}
                {characterDropdownOpen && (
                  <div className="absolute z-30 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-hidden flex flex-col">
                    {/* 搜索框 */}
                    <input
                      type="text"
                      value={characterSearch}
                      onChange={(e) => setCharacterSearch(e.target.value)}
                      className="w-full px-3 py-2 border-b border-gray-200 focus:outline-none text-sm sticky top-0 bg-white"
                      placeholder={t('chapterGenerate.searchCharacters')}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                    {/* 选项列表 */}
                    <div className="overflow-y-auto flex-1 p-1">
                      {availableCharacters.map((char) => (
                        <button
                          key={char.id}
                          onClick={() => handleAddResource('character', char.name)}
                          className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 rounded transition-colors flex items-center justify-between group"
                        >
                          <span>{char.name}</span>
                          <Check className="w-4 h-4 text-gray-400 opacity-0 group-hover:opacity-100" />
                        </button>
                      ))}
                      {availableCharacters.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-500">
                          {characterSearch ? t('chapterGenerate.noMatchingCharacters') : t('chapterGenerate.allCharactersAdded')}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* 场景管理 */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <span className="w-2 h-2 bg-green-500 rounded-full" />
                {t('chapterGenerate.scenes')}
              </h3>

              {/* 已选场景 */}
              <div className="border border-gray-200 rounded-lg p-3 min-h-[200px] max-h-[300px] overflow-y-auto">
                <p className="text-xs text-gray-500 mb-2">{t('chapterGenerate.selectedScenes', { count: chapterScenes.length })}</p>
                <div className="flex flex-wrap gap-1">
                  {chapterScenes.map((name) => (
                    <span
                      key={name}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 text-green-700 rounded text-xs"
                    >
                      {name}
                      <button
                        onClick={() => handleRemoveResource('scene', name)}
                        className="text-green-400 hover:text-green-600 transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                  {chapterScenes.length === 0 && (
                    <p className="text-sm text-gray-400 text-center py-4">{t('chapterGenerate.noScenes')}</p>
                  )}
                </div>
              </div>

              {/* 下拉多选框 */}
              <div className="relative" ref={sceneDropdownRef}>
                <button
                  onClick={() => toggleDropdown('scene')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center justify-between"
                >
                  <span>{sceneDropdownOpen ? t('chapterGenerate.clickToClose') : t('chapterGenerate.addScene')}</span>
                  <ChevronDown className={`w-4 h-4 transition-transform ${sceneDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {/* 下拉选项 */}
                {sceneDropdownOpen && (
                  <div className="absolute z-30 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-hidden flex flex-col">
                    {/* 搜索框 */}
                    <input
                      type="text"
                      value={sceneSearch}
                      onChange={(e) => setSceneSearch(e.target.value)}
                      className="w-full px-3 py-2 border-b border-gray-200 focus:outline-none text-sm sticky top-0 bg-white"
                      placeholder={t('chapterGenerate.searchScenes')}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                    {/* 选项列表 */}
                    <div className="overflow-y-auto flex-1 p-1">
                      {availableScenes.map((scene) => (
                        <button
                          key={scene.id}
                          onClick={() => handleAddResource('scene', scene.name)}
                          className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 rounded transition-colors flex items-center justify-between group"
                        >
                          <span>{scene.name}</span>
                        </button>
                      ))}
                      {availableScenes.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-500">
                          {sceneSearch ? t('chapterGenerate.noMatchingScenes') : t('chapterGenerate.allScenesAdded')}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* 道具管理 */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <span className="w-2 h-2 bg-purple-500 rounded-full" />
                {t('chapterGenerate.props')}
              </h3>

              {/* 已选道具 */}
              <div className="border border-gray-200 rounded-lg p-3 min-h-[200px] max-h-[300px] overflow-y-auto">
                <p className="text-xs text-gray-500 mb-2">{t('chapterGenerate.selectedProps', { count: chapterProps.length })}</p>
                <div className="flex flex-wrap gap-1">
                  {chapterProps.map((name) => (
                    <span
                      key={name}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-purple-100 text-purple-700 rounded text-xs"
                    >
                      {name}
                      <button
                        onClick={() => handleRemoveResource('prop', name)}
                        className="text-purple-400 hover:text-purple-600 transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                  {chapterProps.length === 0 && (
                    <p className="text-sm text-gray-400 text-center py-4">{t('chapterGenerate.noProps')}</p>
                  )}
                </div>
              </div>

              {/* 下拉多选框 */}
              <div className="relative" ref={propDropdownRef}>
                <button
                  onClick={() => toggleDropdown('prop')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center justify-between"
                >
                  <span>{propDropdownOpen ? t('chapterGenerate.clickToClose') : t('chapterGenerate.addProp')}</span>
                  <ChevronDown className={`w-4 h-4 transition-transform ${propDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {/* 下拉选项 */}
                {propDropdownOpen && (
                  <div className="absolute z-30 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-hidden flex flex-col">
                    {/* 搜索框 */}
                    <input
                      type="text"
                      value={propSearch}
                      onChange={(e) => setPropSearch(e.target.value)}
                      className="w-full px-3 py-2 border-b border-gray-200 focus:outline-none text-sm sticky top-0 bg-white"
                      placeholder={t('chapterGenerate.searchProps')}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                    {/* 选项列表 */}
                    <div className="overflow-y-auto flex-1 p-1">
                      {availableProps.map((prop) => (
                        <button
                          key={prop.id}
                          onClick={() => handleAddResource('prop', prop.name)}
                          className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 rounded transition-colors flex items-center justify-between group"
                        >
                          <span>{prop.name}</span>
                        </button>
                      ))}
                      {availableProps.length === 0 && (
                        <p className="px-3 py-2 text-sm text-gray-500">
                          {propSearch ? t('chapterGenerate.noMatchingProps') : t('chapterGenerate.allPropsAdded')}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-end gap-3 px-6 py-2 border-t border-gray-200 bg-gray-50 flex-shrink-0">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2 text-sm"
          >
            <span>💾</span>
            {isSaving ? t('common.saving') : t('common.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChapterResourcesModal;
