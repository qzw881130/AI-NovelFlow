const LAST_SELECTED_NOVEL_KEY = 'novelflow:lastSelectedNovelId';

export const getLastSelectedNovelId = () => {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(LAST_SELECTED_NOVEL_KEY) || '';
};

export const setLastSelectedNovelId = (novelId: string) => {
  if (typeof window === 'undefined') return;
  if (novelId) {
    localStorage.setItem(LAST_SELECTED_NOVEL_KEY, novelId);
  }
};
