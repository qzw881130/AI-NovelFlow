import { useState } from 'react';
import { Plus, Search, BookOpen, Loader2 } from 'lucide-react';
import { useTranslation } from '../../stores/i18nStore';
import { useNovelsState } from './hooks/useNovelsState';
import { NovelCard } from './components/NovelCard';
import { CreateNovelModal } from './components/CreateNovelModal';
import { EditNovelModal } from './components/EditNovelModal';
import { ParseConfirmDialog } from './components/ParseConfirmDialog';
import type { NovelFormData } from './types';

export default function Novels() {
  const { t } = useTranslation();
  const {
    isLoading,
    searchQuery,
    setSearchQuery,
    showCreateModal,
    setShowCreateModal,
    editingNovel,
    setEditingNovel,
    parsingNovelId,
    parsingScenesNovelId,
    confirmDialog,
    chapterRange,
    setChapterRange,
    templatesByType,
    filteredNovels,
    createNovel,
    deleteNovel,
    updateNovel,
    openParseConfirm,
    closeParseConfirm,
    confirmParseCharacters,
    confirmParseScenes,
    getTemplateDisplayName,
  } = useNovelsState();

  const [newNovel, setNewNovel] = useState<NovelFormData>({
    title: '',
    author: '',
    description: '',
    stylePromptTemplateId: '',
    characterParsePromptTemplateId: '',
    sceneParsePromptTemplateId: '',
    promptTemplateId: '',
    scenePromptTemplateId: '',
    chapterSplitPromptTemplateId: '',
    aspectRatio: '16:9'
  });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    await createNovel(newNovel);
    setShowCreateModal(false);
    setNewNovel({
      title: '',
      author: '',
      description: '',
      stylePromptTemplateId: '',
      characterParsePromptTemplateId: '',
      sceneParsePromptTemplateId: '',
      promptTemplateId: '',
      scenePromptTemplateId: '',
      chapterSplitPromptTemplateId: '',
      aspectRatio: '16:9'
    });
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingNovel) return;
    await updateNovel(editingNovel.id, {
      title: editingNovel.title,
      author: editingNovel.author,
      description: editingNovel.description,
      stylePromptTemplateId: editingNovel.stylePromptTemplateId,
      characterParsePromptTemplateId: editingNovel.characterParsePromptTemplateId,
      sceneParsePromptTemplateId: editingNovel.sceneParsePromptTemplateId,
      promptTemplateId: editingNovel.promptTemplateId,
      scenePromptTemplateId: editingNovel.scenePromptTemplateId,
      chapterSplitPromptTemplateId: editingNovel.chapterSplitPromptTemplateId,
      aspectRatio: editingNovel.aspectRatio,
    });
    setEditingNovel(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('novels.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">{t('novels.subtitle')}</p>
        </div>
        <div className="flex gap-3">
          <button onClick={() => setShowCreateModal(true)} className="btn-primary">
            <Plus className="mr-2 h-4 w-4" />
            {t('novels.createNovel')}
          </button>
        </div>
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
      ) : filteredNovels.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <BookOpen className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">{t('novels.noNovelsTitle')}</h3>
          <p className="mt-1 text-sm text-gray-500">{t('novels.noNovelsSubtitle')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredNovels.map((novel) => (
            <NovelCard
              key={novel.id}
              novel={novel}
              templatesByType={templatesByType}
              parsingNovelId={parsingNovelId}
              parsingScenesNovelId={parsingScenesNovelId}
              onDelete={deleteNovel}
              onEdit={setEditingNovel}
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
      />

      {/* Edit Modal */}
      <EditNovelModal
        novel={editingNovel}
        onClose={() => setEditingNovel(null)}
        onSubmit={handleEditSubmit}
        setNovel={setEditingNovel}
        templatesByType={templatesByType}
        getTemplateDisplayName={getTemplateDisplayName}
      />

      {/* Parse Confirm Dialog */}
      <ParseConfirmDialog
        isOpen={confirmDialog.isOpen}
        confirmDialog={confirmDialog}
        chapterRange={chapterRange}
        parsingNovelId={parsingNovelId}
        parsingScenesNovelId={parsingScenesNovelId}
        onClose={closeParseConfirm}
        onConfirmCharacters={confirmParseCharacters}
        onConfirmScenes={confirmParseScenes}
        onChapterRangeChange={setChapterRange}
      />
    </div>
  );
}
