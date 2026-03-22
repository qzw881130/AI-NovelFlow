/**
 * ShotSplitTab - 分镜拆分 Tab（阶段 1）
 *
 * 功能：
 * - 左侧：原文内容
 * - 中间：AI 拆分结果预览 + 分镜编辑
 * - 右侧：ComfyUI 状态
 */

import { useState } from 'react';
import { useChapterGenerateStore, useDataSlice } from '../stores';
import { ShotForm } from './ShotForm';
import { chapterApi } from '../../../api/chapters';
import { shotsApi } from '../../../api/shots';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';

interface ShotSplitTabProps {
  chapter?: any;
  parsedData?: any;
  currentShot?: number;
  novelId?: string;
  chapterId?: string;
}

export function ShotSplitTab({
  chapter,
  parsedData,
  currentShot,
  novelId,
  chapterId,
}: ShotSplitTabProps) {
  const { t } = useTranslation();
  // 使用选择器模式订阅状态变化
  const currentShotIndex = useChapterGenerateStore((state) => state.currentShotIndex);
  const setCurrentShot = useChapterGenerateStore((state) => state.setCurrentShot);
  const markTabComplete = useChapterGenerateStore((state) => state.markTabComplete);
  const parsedDataFromStore = useChapterGenerateStore((state) => state.parsedData);
  const setParsedData = useChapterGenerateStore((state) => state.setParsedData);
  const saveChapterResources = useChapterGenerateStore((state) => state.saveChapterResources);

  // 使用 useDataSlice 获取 initChapterResources 方法
  const { initChapterResources, fetchShots } = useDataSlice();

  const [isSplitting, setIsSplitting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [showImportConfirm, setShowImportConfirm] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [isAddingShot, setIsAddingShot] = useState(false);
  const [isInsertingShot, setIsInsertingShot] = useState<number | null>(null);
  const [isDeletingShot, setIsDeletingShot] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteShotInfo, setDeleteShotInfo] = useState<{ shotId: string; shotIndex: number } | null>(null);

  // 使用 store 中的 parsedData，如果 props 中提供了则优先使用 props
  const shotsData = parsedData || parsedDataFromStore;

  // 处理 AI 拆分
  const handleSplit = async () => {
    if (!novelId || !chapterId) return;
    setIsSplitting(true);
    try {
      const result = await chapterApi.split(novelId, chapterId);
      if (result.success && result.data) {
        // 拆分成功后更新 store 中的 parsedData（包含完整的章节资源数据）
        const data = result.data as any;
        const parsedData = {
          chapter: data.chapter || '',
          characters: data.characters || [],
          scenes: data.scenes || [],
          props: data.props || [],
          shots: data.shots.map((shot: any, idx: number) => ({
            id: shot.id || String(idx + 1),
            chapterId: chapterId,
            index: shot.index || (idx + 1),
            description: shot.description || '',
            video_description: shot.video_description || '',
            characters: shot.characters || [],
            scene: shot.scene || '',
            props: shot.props || [],
            duration: shot.duration || 5,
            dialogues: shot.dialogues || [],
          }))
        };
        // 更新到 store
        setParsedData(parsedData);
        // 初始化章节资源（从 parsedData 中提取 characters/scenes/props 到 chapterCharacters/chapterScenes/chapterProps）
        initChapterResources();
        console.log('AI 拆分成功:', parsedData);
        // 拆分完成后标记阶段完成
        markTabComplete(0);
        toast.success(t('chapterGenerate.aiSplitSuccess'));
      } else {
        console.error('AI 拆分失败:', result.message);
        toast.error(t('chapterGenerate.aiSplitFailed', { message: result.message || t('common.unknownError') }));
      }
    } catch (error) {
      console.error('AI 拆分失败:', error);
      toast.error(t('chapterGenerate.aiSplitFailedRetry'));
    } finally {
      setIsSplitting(false);
    }
  };

  // 保存分镜数据
  const handleSave = async () => {
    if (!novelId || !chapterId) return;
    setIsSaving(true);
    try {
      // 1. 保存章节资源（characters, scenes, props）
      await saveChapterResources(novelId, chapterId);

      // 2. 批量保存分镜数据到 Shot 表
      const shotsData = parsedData || parsedDataFromStore;
      if (shotsData?.shots && shotsData.shots.length > 0) {
        const result = await shotsApi.batchUpdateShots(
          novelId,
          chapterId,
          shotsData.shots.map((shot: any) => ({
            id: shot.id,
            description: shot.description,
            characters: shot.characters,
            scene: shot.scene,
            props: shot.props,
            duration: shot.duration,
            dialogues: shot.dialogues,
          }))
        );

        if (result.success) {
          const resultData = result.data as any;
          console.log(t('chapterGenerate.shotsSaved', { count: resultData?.updated_count }));
          markTabComplete(0);
          toast.success(t('chapterGenerate.shotSaveSuccess'));
        } else {
          console.error(t('chapterGenerate.shotSaveFailed', { message: result.message || t('common.unknownError') }));
          toast.error(t('chapterGenerate.shotSaveFailed', { message: result.message || t('common.unknownError') }));
        }
      } else {
        // 没有分镜数据，只保存章节资源
        markTabComplete(0);
        toast.success(t('chapterGenerate.chapterResourceSaved'));
      }
    } catch (error) {
      console.error(t('chapterGenerate.saveFailed') + ':', error);
      toast.error(t('chapterGenerate.saveFailedRetry'));
    } finally {
      setIsSaving(false);
    }
  };

  // 处理分镜列表项点击
  const handleShotClick = (shotId: string, index: number) => {
    setCurrentShot(shotId, index);
  };

  // 新增分镜（在末尾）
  const handleAddShot = async () => {
    if (!novelId || !chapterId) return;
    setIsAddingShot(true);
    try {
      const result = await shotsApi.createShot(novelId, chapterId, {
        description: t('chapterGenerate.newShotDescription'),
        duration: 5,
        characters: [],
        scene: '',
        props: [],
        dialogues: [],
      });

      if (result.success && result.data) {
        // 刷新分镜数据（同时更新 parsedData 和 shotImages）
        await fetchShots(novelId, chapterId);

        // 重新获取更新后的分镜列表
        const updatedShots = await shotsApi.getShots(novelId, chapterId);
        if (updatedShots.success) {
          // 更新 store 中的 parsedData
          const shotsData = parsedData || parsedDataFromStore;
          const newParsedData = {
            ...shotsData,
            shots: updatedShots.data.map((shot, idx) => ({
              ...shot,
              index: idx + 1,
            })),
          };
          setParsedData(newParsedData);
          toast.success(t('chapterGenerate.shotAdded'));
        }
      } else {
        toast.error(t('chapterGenerate.shotAddFailed', { message: result.message || t('common.unknownError') }));
      }
    } catch (error) {
      console.error(t('chapterGenerate.addShotFailed') + ':', error);
      toast.error(t('chapterGenerate.shotAddFailedRetry'));
    } finally {
      setIsAddingShot(false);
    }
  };

  // 插入分镜（在指定分镜前面）
  const handleInsertShot = async (beforeIndex: number) => {
    if (!novelId || !chapterId) return;
    setIsInsertingShot(beforeIndex);
    try {
      // 在指定分镜前面插入，insert_index 就是 beforeIndex
      const result = await shotsApi.createShot(novelId, chapterId, {
        description: t('chapterGenerate.insertedShotDescription'),
        duration: 5,
        characters: [],
        scene: '',
        props: [],
        dialogues: [],
        insert_index: beforeIndex,
      });

      if (result.success && result.data) {
        // 刷新分镜数据（同时更新 parsedData 和 shotImages）
        await fetchShots(novelId, chapterId);

        // 重新获取更新后的分镜列表
        const updatedShots = await shotsApi.getShots(novelId, chapterId);
        if (updatedShots.success) {
          // 更新 store 中的 parsedData
          const shotsData = parsedData || parsedDataFromStore;
          const newParsedData = {
            ...shotsData,
            shots: updatedShots.data.map((shot, idx) => ({
              ...shot,
              index: idx + 1,
            })),
          };
          setParsedData(newParsedData);
          toast.success(t('chapterGenerate.shotInserted'));
        }
      } else {
        toast.error(t('chapterGenerate.shotInsertFailed', { message: result.message || t('common.unknownError') }));
      }
    } catch (error) {
      console.error(t('chapterGenerate.insertShotFailed') + ':', error);
      toast.error(t('chapterGenerate.shotInsertFailedRetry'));
    } finally {
      setIsInsertingShot(null);
    }
  };

  // 删除分镜
  const handleDeleteShot = async (shotId: string, shotIndex: number) => {
    if (!novelId || !chapterId) return;

    // 显示确认对话框
    setDeleteShotInfo({ shotId, shotIndex });
    setShowDeleteConfirm(true);
  };

  // 确认删除
  const confirmDeleteShot = async () => {
    if (!deleteShotInfo || !novelId || !chapterId) return;

    const { shotId, shotIndex } = deleteShotInfo;
    setIsDeletingShot(true);
    try {
      const result = await shotsApi.deleteShot(novelId, chapterId, shotId);

      if (result.success) {
        // 刷新分镜数据（同时更新 parsedData 和 shotImages）
        await fetchShots(novelId, chapterId);

        // 重新获取更新后的分镜列表
        const updatedShotsResult = await shotsApi.getShots(novelId, chapterId);
        if (updatedShotsResult.success) {
          // 更新 store 中的 parsedData
          const shotsData = parsedData || parsedDataFromStore;
          const newParsedData = {
            ...shotsData,
            shots: updatedShotsResult.data.map((shot, idx) => ({
              ...shot,
              index: idx + 1,
            })),
          };
          setParsedData(newParsedData);

          // 如果删除的是当前选中的分镜，调整选中索引
          if (currentShot === shotIndex) {
            if (updatedShotsResult.data.length > 0) {
              // 如果还有分镜，选中同位置的分镜（如果超出范围则选最后一个）
              const newShotIndex = Math.min(shotIndex, updatedShotsResult.data.length);
              const newShot = updatedShotsResult.data[newShotIndex - 1];
              setCurrentShot(newShot.id, newShotIndex);
            }
          } else if ((currentShot || 0) > shotIndex) {
            // 如果删除的是当前分镜前面的分镜，当前分镜索引 -1
            const newShotIndex = (currentShot || 0) - 1;
            // 找到新索引对应的分镜 ID
            const newShot = updatedShotsResult.data[newShotIndex - 1];
            if (newShot) {
              setCurrentShot(newShot.id, newShotIndex);
            }
          }

          toast.success(t('chapterGenerate.shotDeleted'));
        }
      } else {
        toast.error(t('chapterGenerate.shotDeleteFailed', { message: result.message || t('common.unknownError') }));
      }
    } catch (error) {
      console.error(t('chapterGenerate.deleteShotFailed') + ':', error);
      toast.error(t('chapterGenerate.shotDeleteFailedRetry'));
    } finally {
      setIsDeletingShot(false);
      setShowDeleteConfirm(false);
      setDeleteShotInfo(null);
    }
  };

  // 导出分镜数据为 JSON
  const handleExport = () => {
    if (!shotsData || !shotsData.shots || shotsData.shots.length === 0) {
      toast.warning(t('chapterGenerate.noShotsToExport'));
      return;
    }

    setIsExporting(true);
    try {
      // 构建与 AI 拆分返回格式一致的数据
      const exportData = {
        chapter: shotsData.chapter || chapter?.title || '',
        characters: shotsData.characters || [],
        scenes: shotsData.scenes || [],
        props: shotsData.props || [],
        shots: shotsData.shots.map((shot: any, idx: number) => ({
          id: shot.id || String(idx + 1),
          index: shot.index || (idx + 1),
          description: shot.description || '',
          video_description: shot.video_description || '',
          characters: shot.characters || [],
          scene: shot.scene || '',
          props: shot.props || [],
          duration: shot.duration || 5,
          dialogues: shot.dialogues || [],
        }))
      };

      // 创建 JSON blob
      const jsonString = JSON.stringify(exportData, null, 2);
      const blob = new Blob([jsonString], { type: 'application/json' });
      const url = URL.createObjectURL(blob);

      // 创建下载链接
      const a = document.createElement('a');
      a.href = url;
      a.download = `${t('chapterGenerate.shotData_')}${chapter?.title || chapterId || 'unknown'}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      console.log(t('chapterGenerate.shotDataExported') + ':', exportData);
      toast.success(t('chapterGenerate.shotDataExported'));
    } catch (error) {
      console.error(t('chapterGenerate.exportFailed') + ':', error);
      toast.error(t('chapterGenerate.exportFailedRetry'));
    } finally {
      setIsExporting(false);
    }
  };

  // 导入分镜数据
  const handleImport = () => {
    // 创建文件输入元素
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async (e: Event) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;

      // 设置文件并显示确认对话框
      setImportFile(file);
      setShowImportConfirm(true);
    };
    input.click();
  };

  // 确认导入
  const handleConfirmImport = async () => {
    if (!importFile || !novelId || !chapterId) return;

    setShowImportConfirm(false);
    setIsImporting(true);
    try {
      const reader = new FileReader();
      reader.onload = async (readEvent: ProgressEvent<FileReader>) => {
        try {
          const content = readEvent.target?.result as string;
          const importedData = JSON.parse(content);

          // 验证数据格式
          if (!importedData || !Array.isArray(importedData.shots)) {
            throw new Error(t('chapterGenerate.invalidJsonFormat'));
          }

          // 构建分镜数据列表
          const shotsList = importedData.shots.map((shot: any, idx: number) => ({
            id: shot.id || String(idx + 1),
            description: shot.description || '',
            video_description: shot.video_description || '',
            characters: shot.characters || [],
            scene: shot.scene || '',
            props: shot.props || [],
            duration: shot.duration || 5,
            dialogues: shot.dialogues || [],
          }));

          // 1. 批量保存分镜数据到数据库
          const result = await shotsApi.batchUpdateShots(novelId, chapterId, shotsList);

          if (!result.success) {
            throw new Error(result.message || '保存失败');
          }

          // 2. 如果有章节资源数据，也保存到数据库
          if (importedData.characters || importedData.scenes || importedData.props) {
            const parsedData = {
              chapter: importedData.chapter || '',
              characters: importedData.characters || [],
              scenes: importedData.scenes || [],
              props: importedData.props || [],
              shots: shotsList
            };
            setParsedData(parsedData);
            await saveChapterResources(novelId, chapterId);
          }

          // 3. 更新 store
          const newParsedData = {
            chapter: importedData.chapter || '',
            characters: importedData.characters || [],
            scenes: importedData.scenes || [],
            props: importedData.props || [],
            shots: shotsList.map((shot: any, idx: number) => ({
              ...shot,
              chapterId: chapterId,
              index: idx + 1,
            }))
          };
          setParsedData(newParsedData);
          initChapterResources();

          console.log(t('chapterGenerate.shotDataImported') + ':', newParsedData);
          markTabComplete(0);
          toast.success(t('chapterGenerate.shotDataImported'));
        } catch (parseError) {
          console.error(t('chapterGenerate.importFailedJsonError') + ':', parseError);
          toast.error(t('chapterGenerate.importFailedJsonError', { message: (parseError as Error).message }));
        } finally {
          setIsImporting(false);
          setImportFile(null);
        }
      };
      reader.readAsText(importFile);
    } catch (error) {
      console.error(t('chapterGenerate.importFailed') + ':', error);
      toast.error(t('chapterGenerate.importFailed', { message: (error as Error).message }));
      setIsImporting(false);
      setImportFile(null);
    }
  };

  const shots = shotsData?.shots || [];
  // 优先使用 props 中的 currentShot，其次使用 store 中的 currentShotIndex
  const shotIndex = currentShot ?? currentShotIndex ?? 1;

  return (
    <div className="h-full flex flex-col">
      {/* 操作栏 */}
      <div className="flex-shrink-0 flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
        <div className="flex items-center gap-4">
          <button
            onClick={handleSplit}
            disabled={isSplitting || !chapterId}
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSplitting ? t('chapterGenerate.splitting') : t('chapterGenerate.aiSplit')}
          </button>
          <button
            onClick={handleAddShot}
            disabled={isAddingShot || !chapterId}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isAddingShot ? t('chapterGenerate.adding') : t('chapterGenerate.addShot')}
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || !chapterId}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isSaving ? t('common.saving') : t('chapterGenerate.saveShots')}
          </button>
          <button
            onClick={handleExport}
            disabled={isExporting || !shotsData || shots.length === 0}
            className="btn-secondary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isExporting ? t('chapterGenerate.exporting') : t('chapterGenerate.exportShots')}
          </button>
          <button
            onClick={handleImport}
            disabled={isImporting || !chapterId}
            className="btn-secondary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isImporting ? t('chapterGenerate.importing') : t('chapterGenerate.importShots')}
          </button>
        </div>
        <div className="text-sm text-gray-500">
          {t('chapterGenerate.totalShots', { count: shots.length })}
        </div>
      </div>

      {/* 分镜列表和编辑区 */}
      <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
        {/* 分镜列表 */}
        <div className="w-72 flex-shrink-0 overflow-y-auto border border-gray-200 rounded-lg">
          {shots.map((shot: any, idx: number) => {
            const shotNum = idx + 1;
            const shotId = shot.id || String(shotNum);
            const isSelected = shotNum === shotIndex;
            const characters = shot.parsed_data?.characters || shot.characters || [];
            const scene = shot.parsed_data?.scene || shot.scene;
            const props = shot.parsed_data?.props || shot.props || [];
            const dialogues = shot.parsed_data?.dialogues || shot.dialogues || [];

            // 提取有台词的角色（去重）
            const dialogueCharacters = Array.from(
              new Set(dialogues.map((d: any) => d.character_name))
            );

            return (
              <div
                key={shot.id || idx}
                className={`p-3 border-b border-gray-100 cursor-pointer hover:bg-gray-50 transition-colors ${
                  isSelected ? 'bg-blue-50 border-blue-200' : ''
                }`}
              >
                {/* 分镜编号和操作按钮 */}
                <div className="flex items-center justify-between mb-2">
                  <div
                    className="flex items-center gap-2 flex-1 min-w-0"
                    onClick={() => handleShotClick(shotId, shotNum)}
                  >
                    <span className="text-sm font-bold text-gray-900">{t('chapterGenerate.shotNumberLabel', { number: shotNum })}</span>
                    <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">{shot.duration}{t('common.second')}</span>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleInsertShot(shotNum);
                      }}
                      disabled={isInsertingShot === shotNum}
                      className="p-1 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors"
                      title={t('chapterGenerate.insertShotBefore')}
                    >
                      {isInsertingShot === shotNum ? (
                        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                      ) : (
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                        </svg>
                      )}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteShot(shotId, shotNum);
                      }}
                      disabled={isDeletingShot}
                      className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                      title={t('chapterGenerate.deleteShot')}
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* 分镜描述 */}
                <p className="text-xs text-gray-600 line-clamp-2 mb-2 leading-relaxed">{shot.description}</p>

                {/* 角色、场景、道具信息 */}
                <div className="space-y-1">
                  {/* 角色 */}
                  {characters.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      <span className="text-xs text-gray-500 flex-shrink-0">{t('chapterGenerate.charactersColon')}</span>
                      <div className="flex flex-wrap gap-1">
                        {characters.slice(0, 3).map((charName: string) => (
                          <span
                            key={charName}
                            className="inline-flex items-center px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs"
                          >
                            {charName}
                          </span>
                        ))}
                        {characters.length > 3 && (
                          <span className="text-xs text-gray-400">+{characters.length - 3}</span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* 台词角色 */}
                  {dialogueCharacters.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      <span className="text-xs text-gray-500 flex-shrink-0">{t('chapterGenerate.dialoguesColon')}</span>
                      <div className="flex flex-wrap gap-1">
                        {dialogueCharacters.slice(0, 3).map((charName, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs"
                          >
                            {String(charName)}
                          </span>
                        ))}
                        {dialogueCharacters.length > 3 && (
                          <span className="text-xs text-gray-400">+{dialogueCharacters.length - 3}</span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* 场景 */}
                  {scene && (
                    <div className="flex items-center gap-1 flex-wrap">
                      <span className="text-xs text-gray-500 flex-shrink-0">{t('chapterGenerate.sceneColon')}</span>
                      <span className="inline-flex items-center px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-xs">
                        {scene}
                      </span>
                    </div>
                  )}

                  {/* 道具 */}
                  {props.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      <span className="text-xs text-gray-500 flex-shrink-0">{t('chapterGenerate.propsColon')}</span>
                      <div className="flex flex-wrap gap-1">
                        {props.slice(0, 3).map((propName: string) => (
                          <span
                            key={propName}
                            className="inline-flex items-center px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-xs"
                          >
                            {propName}
                          </span>
                        ))}
                        {props.length > 3 && (
                          <span className="text-xs text-gray-400">+{props.length - 3}</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          {shots.length === 0 && (
            <div className="p-8 text-center text-gray-500 text-sm">
              {t('chapterGenerate.clickAiSplitHint')}
            </div>
          )}
        </div>

        {/* 分镜编辑区 */}
        <div className="flex-1 overflow-y-auto border border-gray-200 rounded-lg p-4">
          {shots.length > 0 && shotIndex >= 1 && shotIndex <= shots.length ? (
            <ShotForm
              shotIndex={shotIndex}
              shotData={shots[shotIndex - 1]}
              showVideoDescription={true}
              showDuration={true}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500">
              {t('chapterGenerate.selectShotToEdit')}
            </div>
          )}
        </div>
      </div>

      {/* 导入确认对话框 */}
      {showImportConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('chapterGenerate.confirmImportShots')}</h3>
            </div>
            <p className="text-sm text-red-600 mb-6">
              {t('chapterGenerate.importOverwriteWarning')}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowImportConfirm(false);
                  setImportFile(null);
                }}
                className="btn-secondary"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleConfirmImport}
                className="btn-primary bg-amber-600 hover:bg-amber-700"
              >
                {t('chapterGenerate.confirmImport')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认对话框 */}
      {showDeleteConfirm && deleteShotInfo && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-500/20 flex items-center justify-center">
                <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('chapterGenerate.confirmDeleteShot')}</h3>
            </div>
            <p className="text-sm text-gray-600 mb-2">
              {t('chapterGenerate.aboutToDelete')} <span className="font-semibold">{t('chapterGenerate.shot', { number: deleteShotInfo.shotIndex })}</span>
            </p>
            <p className="text-sm text-red-600 mb-6 font-medium">
              {t('chapterGenerate.deleteCannotUndo')}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowDeleteConfirm(false);
                  setDeleteShotInfo(null);
                }}
                className="btn-secondary"
                disabled={isDeletingShot}
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={confirmDeleteShot}
                disabled={isDeletingShot}
                className="btn-primary bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isDeletingShot ? t('chapterGenerate.deleting') : t('chapterGenerate.confirmDelete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ShotSplitTab;
