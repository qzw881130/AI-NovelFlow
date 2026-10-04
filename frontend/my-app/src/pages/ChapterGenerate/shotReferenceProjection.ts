export type ShotReferenceImage = {
  label: string;
  url: string;
  source: 'task' | 'current_resource';
};

type TaskReferenceImage = { label?: string; url: string };
type ResourceImage = { name?: string; imageUrl?: string | null; image_url?: string | null; existence?: string | null };
type ShotBindings = { characters?: unknown; props?: unknown };

const boundNames = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.filter((name): name is string => typeof name === 'string' && !!name);
  if (typeof value !== 'string') return [];
  try {
    return boundNames(JSON.parse(value));
  } catch {
    return [];
  }
};

const resourceUrl = (resource?: ResourceImage) => resource?.imageUrl || resource?.image_url || null;

export function projectShotReferenceImages(
  taskReferences: TaskReferenceImage[],
  shot: ShotBindings | null | undefined,
  characters: ResourceImage[],
  props: ResourceImage[],
): ShotReferenceImage[] {
  const projected: ShotReferenceImage[] = [];
  const seen = new Set<string>();
  const add = (image: ShotReferenceImage) => {
    const key = `${image.label}\u0000${image.url}`;
    if (!seen.has(key)) {
      seen.add(key);
      projected.push(image);
    }
  };

  for (const reference of Array.isArray(taskReferences) ? taskReferences : []) {
    if (typeof reference?.url !== 'string' || !reference.url) continue;
    const label = typeof reference.label === 'string' && reference.label ? reference.label : '参考图';
    // Keep the actual task snapshot. Expanded current assets are supplemental
    // previews, not replacements for physical references used by that task.
    projected.push({ label, url: reference.url, source: 'task' });
    if (label.includes('角色合并图') || reference.url.includes('/merged_characters/')) {
      for (const name of boundNames(shot?.characters)) {
        const url = resourceUrl(characters.find((resource) => resource?.name === name));
        if (url) add({ label: `角色：${name}`, url, source: 'current_resource' });
      }
    } else if (label.includes('道具合并图') || reference.url.includes('/merged_props/')) {
      for (const name of boundNames(shot?.props)) {
        const resource = props.find((item) => item?.name === name);
        if (resource?.existence === 'FICTIONAL_OR_NONEXISTENT') continue;
        const url = resourceUrl(resource);
        if (url) add({ label: `道具：${name}`, url, source: 'current_resource' });
      }
    }
  }
  return projected;
}
