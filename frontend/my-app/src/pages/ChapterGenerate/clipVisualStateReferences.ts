import type { SemanticClipPlan } from '../../api/shots';

export function clipVisualStateOptions(clip: SemanticClipPlan) {
  const enabled = clip.visual_state_reference_config?.enabled_state_ids;
  return [...new Set(clip.visual_state_indexes || [])].map(index => ({
    id: `KF${index}`, index, enabled: enabled == null || enabled.includes(`KF${index}`),
  }));
}

export function visualStatePromptIsCurrent(clip: SemanticClipPlan) {
  const disabled = clipVisualStateOptions(clip).filter(s => !s.enabled).map(s => s.id);
  return JSON.stringify(disabled) === JSON.stringify(clip.prompt_projection?.disabled_visual_state_ids || []);
}
