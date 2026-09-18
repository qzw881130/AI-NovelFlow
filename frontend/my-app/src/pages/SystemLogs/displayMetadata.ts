import { chapterApi } from '../../api/chapters';
import { novelApi } from '../../api/novels';
import { shotsApi } from '../../api/shots';

export interface SystemLogDisplayMetadata {
  novels: Record<string, { id: string; title: string }>;
  chapters: Record<string, { id: string; novelId: string; number: number; title: string }>;
  shots: Record<string, { id: string; chapterId: string; index: number }>;
}

export const EMPTY_DISPLAY_METADATA: SystemLogDisplayMetadata = {
  novels: {},
  chapters: {},
  shots: {},
};

export const shortTechnicalId = (value: string | null | undefined) => {
  if (!value) return '';
  return value.length <= 16 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
};

export async function loadSystemLogDisplayMetadata(): Promise<SystemLogDisplayMetadata> {
  const novelResponse = await novelApi.fetchList();
  if (!novelResponse.success || !novelResponse.data) return EMPTY_DISPLAY_METADATA;

  const metadata: SystemLogDisplayMetadata = { novels: {}, chapters: {}, shots: {} };
  novelResponse.data.forEach(novel => {
    metadata.novels[novel.id] = { id: novel.id, title: novel.title };
  });

  const chapterResponses = await Promise.all(novelResponse.data.map(async novel => ({
    novelId: novel.id,
    response: await chapterApi.fetchByNovel(novel.id),
  })));
  const chapters = chapterResponses.flatMap(({ novelId, response }) => {
    if (!response.success || !response.data) return [];
    return response.data.map(chapter => ({ ...chapter, novelId: chapter.novelId || novelId }));
  });
  chapters.forEach(chapter => {
    metadata.chapters[chapter.id] = {
      id: chapter.id,
      novelId: chapter.novelId,
      number: chapter.number,
      title: chapter.title,
    };
  });

  const shotResponses = await Promise.all(chapters.map(async chapter => ({
    chapterId: chapter.id,
    response: await shotsApi.getShots(chapter.novelId, chapter.id),
  })));
  shotResponses.forEach(({ chapterId, response }) => {
    if (!response.success || !response.data) return;
    response.data.forEach(shot => {
      metadata.shots[shot.id] = { id: shot.id, chapterId, index: shot.index };
    });
  });
  return metadata;
}
