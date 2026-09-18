/**
 * 数据 Slice - 管理章节数据、资源数据和分镜数据
 */
import type { StateCreator } from 'zustand';
import type {
  DataSliceState,
  ChapterGenerateStore,
  Shot,
  ParsedData,
  ShotDataFromParsed,
} from './types';
import type { Character } from '../../types';
import { API_BASE } from '../../constants';
import { shotsApi } from '../../../../api/shots';
import { assetResolutionsApi } from '../../../../api/assetResolutions';
import type { ShotRevisionDraft } from '../../../../api/shotRevision';
import {shotRevisionPatch,captureShotSaves,receiveShotSnapshots,normalizeKnownEventIdentities} from '../../../../api/shotRevision';

export interface DataSlice extends DataSliceState {
  fetchNovel: (novelId: string) => Promise<void>;
  fetchChapter: (novelId: string, chapterId: string) => Promise<void>;
  fetchCharacters: (novelId: string) => Promise<void>;
  fetchScenes: (novelId: string) => Promise<void>;
  fetchProps: (novelId: string) => Promise<void>;
  fetchShots: (novelId: string, chapterId: string) => Promise<void>;
  fetchShotsWithReturn: (novelId: string, chapterId: string) => Promise<Shot[]>;
  setParsedData: (data: ParsedData | null) => void;
  setEditableJson: (json: string) => void;
  setShots: (shots: Shot[]) => void;
  updateShot: (shotId: string, data: Partial<Shot>) => Promise<void>;
  saveShotRevisions: (novelId: string, chapterId: string, drafts: ShotRevisionDraft[]) => Promise<Shot[]>;
  shotTreatmentDrafts: Record<string, import('../../../../api/shotRevision').TreatmentDraft>;
  shotServerHeads: Record<string, Shot>;
  shotEventIdentities: Record<string, import('../../../../api/shotRevision').ShotEventIdentities>;
  setShotTreatmentDraft: (shotId: string, draft: import('../../../../api/shotRevision').TreatmentDraft) => void;
  getCharacterImage: (name: string) => string | undefined;
  getSceneImage: (name: string) => string | null;
  getPropImage: (name: string) => string | null;

  // 章节资源管理
  initChapterResources: () => Promise<void>;
  addResourceToChapter: (type: 'character' | 'scene' | 'prop', name: string) => void;
  removeResourceFromChapter: (type: 'character' | 'scene' | 'prop', name: string) => void;
  saveChapterResources: (novelId: string, chapterId: string) => Promise<void>;
}

export const createDataSlice: StateCreator<
  ChapterGenerateStore,
  [],
  [],
  DataSlice
> = (set, get) => ({
  // ========== 初始状态 ==========
  chapter: null,
  novel: null,
  parsedData: null,
  editableJson: '',
  loading: true,
  characters: [] as Character[],
  scenes: [],
  props: [],
  shots: [],
  shotTreatmentDrafts: {},
  shotServerHeads: {},
  shotEventIdentities: {},
  setShotTreatmentDraft: (shotId, draft) => set(state => ({shotTreatmentDrafts: {...state.shotTreatmentDrafts, [shotId]: draft}})),
  // 章节级资源初始化为空数组
  chapterCharacters: [],
  chapterScenes: [],
  chapterProps: [],

  // ========== 数据获取方法 ==========

  fetchNovel: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/`);
      const data = await res.json();
      if (data.success) {
        set({ novel: data.data });
      }
    } catch (error) {
      console.error('获取小说数据失败:', error);
    }
  },

  fetchChapter: async (novelId: string, chapterId: string) => {
    set({ loading: true });
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}/`);
      const data = await res.json();
      if (data.success) {
        // 转换 snake_case 到 camelCase
        const rawChapter = data.data;
        const chapter = {
          ...rawChapter,
          novelId: rawChapter.novel_id || rawChapter.novelId || novelId,
          parsedData: rawChapter.parsed_data || rawChapter.parsedData,
          characterImages: rawChapter.character_images || rawChapter.characterImages,
          shotImages: rawChapter.shot_images || rawChapter.shotImages,
          shotVideos: rawChapter.shot_videos || rawChapter.shotVideos,
          transitionVideos: rawChapter.transition_videos || rawChapter.transitionVideos,
          finalVideo: rawChapter.final_video || rawChapter.finalVideo,
          createdAt: rawChapter.created_at || rawChapter.createdAt,
          updatedAt: rawChapter.updated_at || rawChapter.updatedAt,
        };
        set({
          chapter,
          transitionVideos: chapter.transitionVideos || {},
        });

        // 获取分镜数据（存储在独立的 shots 表中）
        await get().fetchShotsWithReturn(novelId, chapterId);

        // 解析 parsedData（仅包含章节资源：characters, scenes, props）
        if (chapter.parsedData) {
          try {
            const parsed = typeof chapter.parsedData === 'string'
              ? JSON.parse(chapter.parsedData)
              : chapter.parsedData;

            // parsedData 不再包含 shots，shots 从独立的 Shot 表获取
            const parsedData: ParsedData = {
              chapter: parsed.chapter || chapter.title,
              characters: parsed.characters || [],
              scenes: parsed.scenes || [],
              props: parsed.props || [],
            };

              set({
                parsedData,
                editableJson: JSON.stringify(parsedData, null, 2),
                transitionVideos: parsed.transition_videos || chapter.transitionVideos || {},
              });

            // 初始化章节级资源
            get().initChapterResources();
          } catch (e) {
            console.error('解析数据格式错误:', e);
          }
        } else {
          // 如果没有 parsedData，初始化空的资源数据
          const parsedData: ParsedData = {
            chapter: chapter.title,
            characters: [],
            scenes: [],
            props: [],
          };
          set({
            parsedData,
            editableJson: JSON.stringify(parsedData, null, 2),
            transitionVideos: chapter.transitionVideos || {},
          });

          // 初始化章节级资源
          get().initChapterResources();
        }
      }
    } catch (error) {
      console.error('获取章节数据失败:', error);
    } finally {
      set({ loading: false });
    }
  },

  fetchCharacters: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/characters/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        set({ characters: data.data });
      }
    } catch (error) {
      console.error('获取角色列表失败:', error);
    }
  },

  fetchScenes: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/scenes/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        set({ scenes: data.data });
      }
    } catch (error) {
      console.error('获取场景列表失败:', error);
    }
  },

  fetchProps: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/props/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        set({ props: data.data });
      }
    } catch (error) {
      console.error('获取道具列表失败:', error);
    }
  },

  fetchShots: async (novelId: string, chapterId: string) => {
    try {
      const result = await shotsApi.getShots(novelId, chapterId);
      if (result.success) {
        set(state => receiveShotSnapshots(state,result.data,{}, {},true));
        get().initAudioFromShots(get().shots);
      }
    } catch (error) {
      console.error('获取分镜列表失败:', error);
    }
  },

  fetchShotsWithReturn: async (novelId: string, chapterId: string): Promise<Shot[]> => {
    try {
      const result = await shotsApi.getShots(novelId, chapterId);
      if (result.success) {
        set(state => receiveShotSnapshots(state,result.data,{}, {},true));
        get().initAudioFromShots(get().shots);
        return get().shots;
      }
      return [];
    } catch (error) {
      console.error('获取分镜列表失败:', error);
      return [];
    }
  },

  // ========== 数据更新方法 ==========

  setParsedData: (data: ParsedData | null) => {
    set({ parsedData: data });
  },

  setEditableJson: (json: string) => {
    set({ editableJson: json });
  },

  setShots: (shots: Shot[]) => {
    set(state=>{
      shots=shots.map(shot=>normalizeKnownEventIdentities(state,shot));
      const newer=shots.filter(shot=>{
        const current=state.shots.find(value=>value.id===shot.id);
        return current && (shot.sourceRevision ?? -1)>(current.sourceRevision ?? -1);
      });
      const accepted=receiveShotSnapshots(state,newer);
      return {...accepted,shots:shots.map(shot=>{
        const current=accepted.shots.find((value:Shot)=>value.id===shot.id);
        return newer.some(value=>value.id===shot.id) || (current && (current.sourceRevision ?? -1)>(shot.sourceRevision ?? -1)) ? current : shot;
      })};
    });
  },

  updateShot: async (shotId: string, data: Partial<Shot>) => {
    const { chapter } = get();
    if (!chapter) return;
    await get().saveShotRevisions(chapter.novelId, chapter.id, [{...data, id: shotId}]);
  },

  saveShotRevisions: async (novelId, chapterId, drafts) => {
    const submittedDrafts = {...get().shotTreatmentDrafts};
    for (const draft of drafts) {
      const treatment = submittedDrafts[draft.id];
      if (treatment?.error) throw new Error(`TREATMENT_DRAFT_INVALID: ${treatment.error}`);
      if (treatment && JSON.stringify(draft.source_treatments ?? draft.sourceTreatments) !== JSON.stringify(JSON.parse(treatment.json))) {
        throw new Error('TREATMENT_DRAFT_NOT_INCLUDED: 请先保存当前原文处理合同草稿');
      }
    }
    const patches=drafts.map(draft=>shotRevisionPatch(normalizeKnownEventIdentities(get(),draft)));
    const contexts=captureShotSaves(get(),patches);
    const result = await shotsApi.batchUpdateShots(novelId, chapterId, patches);
    if (!result.success) throw new Error(result.message || '保存分镜失败');
    const saved = result.data?.shots;
    if (!saved || saved.length !== drafts.length || patches.some(patch => !saved.some(shot => shot.id === patch.id && Number.isInteger(shot.sourceRevision) && shot.sourceRevision>=patch.expected_revision))) {
      throw new Error('SHOT_REVISION_RESPONSE_INVALID');
    }
    if (get().chapter?.id === chapterId) {
      set(state => {
        const accepted=receiveShotSnapshots(state,saved,contexts,result.data?.eventIdMaps);
        const shotTreatmentDrafts = {...state.shotTreatmentDrafts};
        for (const shot of saved) {
          const current=state.shots.find(value=>value.id===shot.id);
          if ((current?.sourceRevision ?? -1)<=shot.sourceRevision && shotTreatmentDrafts[shot.id] === submittedDrafts[shot.id]) delete shotTreatmentDrafts[shot.id];
        }
        return {...accepted, shotTreatmentDrafts};
      });
      return saved.map(shot=>get().shots.find(current=>current.id===shot.id) || shot);
    }
    return saved;
  },

  // ========== 辅助方法 ==========

  getCharacterImage: (name: string): string | undefined => {
    const character = get().characters.find((c) => c.name === name);
    return character?.imageUrl ?? undefined;
  },

  getSceneImage: (name: string): string | null => {
    const scene = get().scenes.find((s) => s.name === name);
    return scene?.imageUrl || null;
  },

  getPropImage: (name: string): string | null => {
    const prop = get().props.find((p) => p.name === name);
    return prop?.imageUrl || null;
  },

  // ========== 章节资源管理方法 ==========

  /** 只从正式章回关联读取白名单，空列表不表示已确认空集。 */
  initChapterResources: async () => {
    const chapter=get().chapter;
    set({chapterCharacters:[],chapterScenes:[],chapterProps:[]});
    if(!chapter)return;
    try {
      const result=await assetResolutionsApi.bindings(chapter.novelId,chapter.id);
      if(get().chapter?.id!==chapter.id||!result.success||!result.data)return;
      const assets=result.data.assets;
      set({chapterCharacters:assets.characters.status==='SUCCEEDED'?assets.characters.bindings.map(b=>b.name):[],
        chapterScenes:assets.scenes.status==='SUCCEEDED'?assets.scenes.bindings.map(b=>b.name):[],
        chapterProps:assets.props.status==='SUCCEEDED'?assets.props.bindings.map(b=>b.name):[]});
    } catch(error) { console.error('读取正式章回关联失败',error); }
  },

  /** 添加资源到章节 */
  addResourceToChapter: (type: 'character' | 'scene' | 'prop', name: string) => {
    const key = type === 'character' ? 'chapterCharacters' : type === 'scene' ? 'chapterScenes' : 'chapterProps';
    const currentList = get()[key as keyof DataSliceState] as string[];

    if (!currentList.includes(name)) {
      set({ [key]: [...currentList, name] });
    }
  },

  /** 从章节移除资源 */
  removeResourceFromChapter: (type: 'character' | 'scene' | 'prop', name: string) => {
    const key = type === 'character' ? 'chapterCharacters' : type === 'scene' ? 'chapterScenes' : 'chapterProps';
    const currentList = get()[key as keyof DataSliceState] as string[];

    set({ [key]: currentList.filter((item) => item !== name) });
  },

  /** 保存章节资源到 parsedData 和后端 */
  saveChapterResources: async (novelId: string, chapterId: string) => {
    throw new Error('请在章回素材解析页修改正式关联；旧名字资源写入已停用');
  },
});
