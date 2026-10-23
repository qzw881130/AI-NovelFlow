import { useState } from 'react';
import { Plus, Copy, Search, BookOpen, Loader2 } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { toast } from '../../stores/toastStore';
import { useNovelsState } from './hooks/useNovelsState';
import { NovelCard } from './components/NovelCard';
import { CreateNovelModal } from './components/CreateNovelModal';
import { CopyNovelModal } from './components/CopyNovelModal';
import { StoryWorldContextModal } from './components/StoryWorldContextModal';
import { EditNovelModal } from './components/EditNovelModal';
import { ParseConfirmDialog } from './components/ParseConfirmDialog';
import type { NovelFormData } from './types';
import { TEMPLATE_FIELDS, emptyNovelTemplateSelection } from './promptTemplateFields';

export default function Novels() {
  const { t } = useTranslation();
  const {
    novels,
    isLoading,
    searchQuery,
    setSearchQuery,
    showCreateModal,
    setShowCreateModal,
    showCopyModal,
    setShowCopyModal,
    editingNovel,
    setEditingNovel,
    parsingNovelId,
    parsingScenesNovelId,
    parsingPropsNovelId,
    confirmDialog,
    chapterRange,
    setChapterRange,
    templatesByType,
    filteredNovels,
    fetchNovels,
    createNovel,
    copyNovel,
    deleteNovel,
    updateNovel,
    setNovelArchived,
    openParseConfirm,
    closeParseConfirm,
    confirmParseCharacters,
    confirmParseScenes,
    confirmParseProps,
    getTemplateDisplayName,
  } = useNovelsState();

  const [newNovel, setNewNovel] = useState<NovelFormData>({
    title: '', author: '', description: '', aspectRatio: '16:9',
    ...emptyNovelTemplateSelection(),
  });
  const [storyContextNovel, setStoryContextNovel] = useState<(typeof novels)[number] | null>(null);
  const [archiveView, setArchiveView] = useState(false);
  const [archivingNovelId, setArchivingNovelId] = useState<string | null>(null);
  const visibleNovels = filteredNovels.filter(novel => Boolean(novel.isArchived) === archiveView);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    await createNovel(newNovel);
    setShowCreateModal(false);
    setNewNovel({ title: '', author: '', description: '', aspectRatio: '16:9', ...emptyNovelTemplateSelection() });
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingNovel) return;
    await updateNovel(editingNovel.id, {
      title: editingNovel.title, author: editingNovel.author,
      description: editingNovel.description, aspectRatio: editingNovel.aspectRatio,
      ...Object.fromEntries(TEMPLATE_FIELDS.map(field => [field.key, editingNovel[field.key]])),
    });
    setEditingNovel(null);
  };

  const handleDeleteNovel = async (novelId: string) => {
    const novel = filteredNovels.find((item) => item.id === novelId);
    const title = novel?.title || '当前小说';
    const chapterCount = novel?.chapterCount ?? 0;
    const confirmed = window.confirm(
      `确认删除《${title}》吗？\n\n该操作会删除小说及其 ${chapterCount} 个章节相关数据，且不可撤销。`
    );
    if (!confirmed) return;
    await deleteNovel(novelId);
  };

  const handleArchiveChange = async (novelId: string, isArchived: boolean) => {
    setArchivingNovelId(novelId);
    try {
      await setNovelArchived(novelId, isArchived);
      toast.success(isArchived ? '小说已归档' : '小说已恢复到活动');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新归档状态失败');
    } finally {
      setArchivingNovelId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('novels.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">{t('novels.subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button onClick={() => setShowCreateModal(true)} className="btn-primary">
            <Plus className="mr-2 h-4 w-4" />
            {t('novels.createNovel')}
          </button>
          <button onClick={() => setShowCopyModal(true)} disabled={isLoading || novels.length === 0} className="btn-secondary">
            <Copy className="mr-2 h-4 w-4" />
            {t('novels.copyNovel')}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="小说状态">
        {([false, true] as const).map(isArchived => (
          <button
            key={String(isArchived)}
            type="button"
            onClick={() => setArchiveView(isArchived)}
            aria-pressed={archiveView === isArchived}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${archiveView === isArchived ? 'bg-primary-600 text-white' : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'}`}
          >
            {isArchived ? '归档' : '活动'} <span className="ml-1 opacity-70">{novels.filter(novel => Boolean(novel.isArchived) === isArchived).length}</span>
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder={t('novels.searchPlaceholder')}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="input-field pl-10"
        />
      </div>

      {/* Novels Grid */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
        </div>
      ) : visibleNovels.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <BookOpen className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">{searchQuery ? '没有匹配的小说' : archiveView ? '暂无归档小说' : t('novels.noNovelsTitle')}</h3>
          <p className="mt-1 text-sm text-gray-500">{searchQuery ? '试试其他关键词' : archiveView ? '在活动列表中点击归档按钮后，小说会显示在这里。' : t('novels.noNovelsSubtitle')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
          {visibleNovels.map((novel) => (
            <NovelCard
              key={novel.id}
              novel={novel}
              templatesByType={templatesByType}
              parsingNovelId={parsingNovelId}
              parsingScenesNovelId={parsingScenesNovelId}
              parsingPropsNovelId={parsingPropsNovelId}
              onDelete={handleDeleteNovel}
              onArchiveChange={handleArchiveChange}
              archiveBusy={archivingNovelId === novel.id}
              onEdit={setEditingNovel}
              onStoryContext={setStoryContextNovel}
              onParseConfirm={openParseConfirm}
              getTemplateDisplayName={getTemplateDisplayName}
            />
          ))}
        </div>
      )}

      {/* Create Modal */}
      <CreateNovelModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSubmit={handleCreate}
        formData={newNovel}
        setFormData={setNewNovel}
        templatesByType={templatesByType}
        getTemplateDisplayName={getTemplateDisplayName}
        referenceNovels={novels}
      />

      {showCopyModal && (
        <CopyNovelModal novels={novels} onClose={() => setShowCopyModal(false)} onCopy={copyNovel} />
      )}

      {storyContextNovel && (
        <StoryWorldContextModal
          novel={storyContextNovel}
          onClose={() => setStoryContextNovel(null)}
          onSaved={fetchNovels}
        />
      )}

      {/* Edit Modal */}
      <EditNovelModal
        novel={editingNovel}
        onClose={() => setEditingNovel(null)}
        onSubmit={handleEditSubmit}
        setNovel={setEditingNovel}
        templatesByType={templatesByType}
        getTemplateDisplayName={getTemplateDisplayName}
        referenceNovels={novels}
      />

      {/* Parse Confirm Dialog */}
      <ParseConfirmDialog
        isOpen={confirmDialog.isOpen}
        confirmDialog={confirmDialog}
        chapterRange={chapterRange}
        parsingNovelId={parsingNovelId}
        parsingScenesNovelId={parsingScenesNovelId}
        parsingPropsNovelId={parsingPropsNovelId}
        onClose={closeParseConfirm}
        onConfirmCharacters={confirmParseCharacters}
        onConfirmScenes={confirmParseScenes}
        onConfirmProps={confirmParseProps}
        onChapterRangeChange={setChapterRange}
      />
    </div>
  );
}
