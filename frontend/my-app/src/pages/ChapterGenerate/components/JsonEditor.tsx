import { Code, Grid3x3, Save, Loader2 } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import JsonTableEditor from './JsonTableEditor';
import { useChapterGenerateStore } from '../stores';
import type { DialogueData } from '../types';

/**
 * JSON 编辑器组件
 * 使用 ChapterGenerateStore 管理状态
 */
export function JsonEditor() {
  const { t } = useTranslation();

  // 从 Store 获取 UI 状态
  const {
    editableJson,
    setEditableJson,
    jsonEditMode,
    setJsonEditMode,
    isSavingJson,
    editorKey,
    handleSaveJson,
    chapter,
    novel,
    parsedData,
    activeShotWorkflow,
    characters,
    scenes,
    props,
  } = useChapterGenerateStore();

  // 从 Store 获取音频相关状态
  const {
    audioUrls,
    audioSources,
    isShotAudioGenerating,
    getShotAudioTasks,
    regenerateAudio,
    generateShotAudio,
    uploadDialogueAudio,
    deleteDialogueAudio,
    isAudioUploading,
  } = useChapterGenerateStore();

  // 获取当前章节和小说ID
  const novelId = novel?.id || '';
  const chapterId = chapter?.id || '';

  // 可用资源列表 - 从小说整体库获取（不是章节数据）
  const availableScenes = scenes.map(s => s.name);
  const availableCharacters = characters.map(c => c.name);
  const availableProps = props.map(p => p.name);

  // 处理保存
  const onSave = async () => {
    if (!novelId || !chapterId) return;
    await handleSaveJson(novelId, chapterId, editableJson);
  };

  // 处理音频生成
  const onGenerateDialogueAudio = async (shotIndex: number, dialogue: DialogueData) => {
    if (!novelId || !chapterId) return;
    await generateShotAudio(novelId, chapterId, shotIndex, [dialogue]);
  };

  // 处理音频重新生成
  const onRegenerateAudio = async (shotIndex: number, characterName: string, dialogue: DialogueData) => {
    if (!novelId || !chapterId) return;
    await regenerateAudio(novelId, chapterId, shotIndex, characterName, dialogue);
  };

  // 处理音频上传
  const onUploadDialogueAudio = async (shotIndex: number, characterName: string, file: File) => {
    if (!novelId || !chapterId) return;
    await uploadDialogueAudio(novelId, chapterId, shotIndex, characterName, file);
  };

  // 处理音频删除
  const onDeleteDialogueAudio = async (shotIndex: number, characterName: string) => {
    if (!novelId || !chapterId) return;
    await deleteDialogueAudio(novelId, chapterId, shotIndex, characterName);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
          <button
            onClick={() => setJsonEditMode('text')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              jsonEditMode === 'text'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <Code className="h-4 w-4" />
            {t('chapterGenerate.jsonText')}
          </button>
          <button
            onClick={() => setJsonEditMode('table')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              jsonEditMode === 'table'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <Grid3x3 className="h-4 w-4" />
            {t('chapterGenerate.tableEdit')}
          </button>
        </div>
        <button
          onClick={onSave}
          disabled={isSavingJson || !editableJson.trim()}
          className="btn-primary text-sm py-2 px-4 disabled:opacity-50"
        >
          {isSavingJson ? (
            <><Loader2 className="h-4 w-4 mr-2 animate-spin" />{t('common.saving')}</>
          ) : (
            <><Save className="h-4 w-4 mr-2" />{t('chapterGenerate.saveChanges')}</>
          )}
        </button>
      </div>

      {jsonEditMode === 'text' ? (
        <textarea
          className="w-full h-64 bg-gray-900 text-gray-100 p-4 rounded-lg font-mono text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:outline-none"
          value={editableJson}
          onChange={(e) => setEditableJson(e.target.value)}
          placeholder={t('chapterGenerate.jsonPlaceholder')}
          spellCheck={false}
        />
      ) : (
        <JsonTableEditor
          key={editorKey}
          value={editableJson}
          onChange={setEditableJson}
          availableScenes={availableScenes}
          availableCharacters={availableCharacters}
          availableProps={availableProps}
          activeShotWorkflow={activeShotWorkflow}
          audioUrls={audioUrls}
          audioSources={audioSources}
          isShotAudioGenerating={isShotAudioGenerating}
          getShotAudioTasks={getShotAudioTasks}
          onRegenerateAudio={onRegenerateAudio}
          onGenerateDialogueAudio={onGenerateDialogueAudio}
          onUploadDialogueAudio={onUploadDialogueAudio}
          onDeleteDialogueAudio={onDeleteDialogueAudio}
          isAudioUploading={isAudioUploading}
        />
      )}
    </div>
  );
}
