import { useEffect, useMemo, useState } from 'react';
import { taskApi } from '../../api/tasks';
import { useChapterGenerateStore } from './stores';
import { projectShotReferenceImages, type ShotReferenceImage } from './shotReferenceProjection';

type ShotReferenceSource = {
  imageTaskId?: string | null;
  image_task_id?: string | null;
  characters?: unknown;
  props?: unknown;
};

export function useShotReferenceImages(shot: ShotReferenceSource | null | undefined, enabled = true): {
  referenceImages: ShotReferenceImage[];
  referenceImagesLoading: boolean;
} {
  const characters = useChapterGenerateStore((state) => state.characters);
  const props = useChapterGenerateStore((state) => state.props);
  const taskId = String(shot?.imageTaskId || shot?.image_task_id || '');
  const [snapshot, setSnapshot] = useState<{ taskId: string; shot: ShotReferenceSource; images: Array<{ label?: string; url: string }> } | null>(null);
  const [loadingTaskId, setLoadingTaskId] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !taskId || !shot) return;
    let cancelled = false;
    setLoadingTaskId(taskId);
    taskApi.fetch(taskId)
      .then((response) => {
        if (cancelled) return;
        const taskReferenceImages = response.data?.referenceImages;
        const images = Array.isArray(taskReferenceImages)
          ? taskReferenceImages.filter((image): image is { label?: string; url: string } => (
            !!image && typeof image.url === 'string' && image.url.length > 0
          ))
          : [];
        setSnapshot({ taskId, shot, images });
      })
      .catch(() => {
        if (!cancelled) setSnapshot({ taskId, shot, images: [] });
      })
      .finally(() => {
        if (!cancelled) setLoadingTaskId(null);
      });
    return () => { cancelled = true; };
  }, [enabled, taskId, shot]);

  const referenceImages = useMemo(() => projectShotReferenceImages(
    enabled && snapshot?.taskId === taskId && snapshot.shot === shot ? snapshot.images : [],
    shot,
    characters,
    props,
  ), [enabled, snapshot, taskId, shot, characters, props]);

  return { referenceImages, referenceImagesLoading: enabled && !!taskId && loadingTaskId === taskId };
}
