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
  const [snapshot, setSnapshot] = useState<{ taskId: string; images: Array<{ label?: string; url: string }> } | null>(null);
  const [loadingTaskId, setLoadingTaskId] = useState<string | null>(null);

  useEffect(() => {
    // Task references are immutable generation inputs. Polling replaces the
    // Shot object, but must not reload or discard this task's image snapshot.
    if (!enabled || !taskId) return;
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
        setSnapshot({ taskId, images });
      })
      .catch(() => {
        if (!cancelled) setSnapshot({ taskId, images: [] });
      })
      .finally(() => {
        if (!cancelled) setLoadingTaskId(null);
      });
    return () => { cancelled = true; };
  }, [enabled, taskId]);

  const referenceImages = useMemo(() => projectShotReferenceImages(
    enabled && snapshot?.taskId === taskId ? snapshot.images : [],
    shot,
    characters,
    props,
  ), [enabled, snapshot, taskId, shot, characters, props]);

  return { referenceImages, referenceImagesLoading: enabled && !!taskId && loadingTaskId === taskId };
}
