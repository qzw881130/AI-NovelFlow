import { useState, useCallback } from 'react';
import { API_BASE } from '../constants';
import type { Chapter, Novel, Character, Scene, ParsedData } from '../types';

interface UseChapterDataReturn {
  // 状态
  chapter: Chapter | null;
  novel: Novel | null;
  parsedData: ParsedData | null;
  editableJson: string;
  characters: Character[];
  scenes: Scene[];
  loading: boolean;
  // 方法
  fetchNovel: (novelId: string | undefined) => Promise<void>;
  fetchChapter: (novelId: string | undefined, chapterId: string | undefined) => Promise<void>;
  fetchCharacters: (novelId: string | undefined) => Promise<void>;
  fetchScenes: (novelId: string | undefined) => Promise<void>;
  setParsedData: React.Dispatch<React.SetStateAction<ParsedData | null>>;
  setEditableJson: React.Dispatch<React.SetStateAction<string>>;
  getCharacterImage: (name: string) => string | null;
  getSceneImage: (name: string) => string | null;
}

export default function useChapterData(): UseChapterDataReturn {
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [parsedData, setParsedData] = useState<ParsedData | null>(null);
  const [editableJson, setEditableJson] = useState<string>('');
  const [characters, setCharacters] = useState<Character[]>([]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);

  // 获取小说数据
  const fetchNovel = useCallback(async (novelId: string | undefined) => {
    if (!novelId) return;
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/`);
      const data = await res.json();
      if (data.success) {
        setNovel(data.data);
      }
    } catch (error) {
      console.error('获取小说数据失败:', error);
    }
  }, []);

  // 获取章节数据
  const fetchChapter = useCallback(async (novelId: string | undefined, chapterId: string | undefined) => {
    if (!novelId || !chapterId) return;
    
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}/`);
      const data = await res.json();
      if (data.success) {
        setChapter(data.data);
        // 如果章节有解析数据，加载它
        if (data.data.parsedData) {
          try {
            const parsed = typeof data.data.parsedData === 'string' 
              ? JSON.parse(data.data.parsedData) 
              : data.data.parsedData;
            setParsedData(parsed);
            setEditableJson(JSON.stringify(parsed, null, 2));
          } catch (e) {
            console.error('解析数据格式错误:', e);
          }
        }
      }
    } catch (error) {
      console.error('获取章节数据失败:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  // 获取角色列表
  const fetchCharacters = useCallback(async (novelId: string | undefined) => {
    if (!novelId) return;
    try {
      const res = await fetch(`${API_BASE}/characters/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        setCharacters(data.data);
      }
    } catch (error) {
      console.error('获取角色列表失败:', error);
    }
  }, []);

  // 获取场景列表
  const fetchScenes = useCallback(async (novelId: string | undefined) => {
    if (!novelId) return;
    try {
      const res = await fetch(`${API_BASE}/scenes/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        setScenes(data.data);
      }
    } catch (error) {
      console.error('获取场景列表失败:', error);
    }
  }, []);

  // 根据角色名获取角色图片
  const getCharacterImage = useCallback((name: string): string | null => {
    const character = characters.find(c => c.name === name);
    return character?.imageUrl || null;
  }, [characters]);

  // 根据场景名获取场景图片
  const getSceneImage = useCallback((name: string): string | null => {
    const scene = scenes.find(s => s.name === name);
    return scene?.imageUrl || null;
  }, [scenes]);

  return {
    chapter,
    novel,
    parsedData,
    editableJson,
    characters,
    scenes,
    loading,
    fetchNovel,
    fetchChapter,
    fetchCharacters,
    fetchScenes,
    setParsedData,
    setEditableJson,
    getCharacterImage,
    getSceneImage,
  };
}
