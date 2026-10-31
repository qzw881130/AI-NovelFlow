import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { novelApi } from '../api/novels';
import type { Novel } from '../types';
import ChapterGenerate from './ChapterGenerate';
import GridModePage from './GridMode';

export default function ModeGeneratePage() {
  const { id } = useParams<{ id: string }>();
  const [novel, setNovel] = useState<Novel | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { if (!id) return; novelApi.fetch(id).then(result => {
    if (result.success && result.data) setNovel(result.data);
    else setError(result.message || '小说不存在');
  }).catch(() => setError('小说加载失败')); }, [id]);
  if (error) return <div className="p-8 text-red-600">{error}</div>;
  if (!novel) return <div className="p-8 text-gray-500">正在加载小说模式…</div>;
  return novel.videoMode === 'grid' ? <GridModePage /> : <ChapterGenerate />;
}
