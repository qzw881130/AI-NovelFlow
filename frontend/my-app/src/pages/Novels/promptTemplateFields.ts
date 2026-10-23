// 模板类型配置
export const TEMPLATE_FIELDS = [
  { key: 'storyWorldContextPromptTemplateId', labelKey: 'novels.storyWorldContextPromptLabel', hintKey: 'novels.storyWorldContextPromptHint', templateType: 'story_world_context_recommender', category: 'story_context' },
  { key: 'stylePromptTemplateId', labelKey: 'novels.stylePromptLabel', hintKey: 'novels.stylePromptHint', templateType: 'style', category: 'style_design' },
  { key: 'characterParsePromptTemplateId', labelKey: 'novels.characterParsePromptLabel', hintKey: 'novels.characterParsePromptHint', templateType: 'character_parse', category: 'asset_parse' },
  { key: 'sceneParsePromptTemplateId', labelKey: 'novels.sceneParsePromptLabel', hintKey: 'novels.sceneParsePromptHint', templateType: 'scene_parse', category: 'asset_parse' },
  { key: 'propParsePromptTemplateId', labelKey: 'novels.propParsePromptLabel', hintKey: 'novels.propParsePromptHint', templateType: 'prop_parse', category: 'asset_parse' },
  { key: 'promptTemplateId', labelKey: 'novels.characterPromptLabel', hintKey: 'novels.characterPromptHint', templateType: 'character', category: 'asset_generation' },
  { key: 'scenePromptTemplateId', labelKey: 'novels.scenePromptLabel', hintKey: 'novels.scenePromptHint', templateType: 'scene', category: 'asset_generation' },
  { key: 'propPromptTemplateId', labelKey: 'novels.propPromptLabel', hintKey: 'novels.propPromptHint', templateType: 'prop', category: 'asset_generation' },
  { key: 'sceneSettingPromptTemplateId', labelKey: 'promptConfig.types.sceneSetting', hintKey: 'promptConfig.types.sceneSettingDesc', templateType: 'scene_setting', category: 'asset_generation' },
  { key: 'propAppearancePromptTemplateId', labelKey: 'promptConfig.types.propAppearance', hintKey: 'promptConfig.types.propAppearanceDesc', templateType: 'prop_appearance', category: 'asset_generation' },
  { key: 'chapterSplitPromptTemplateId', labelKey: 'novels.splitPromptLabel', hintKey: 'novels.splitPromptHint', templateType: 'chapter_split', category: 'shot_planning' },
  { key: 'keyframeDescriptionPromptTemplateId', labelKey: 'novels.keyframeDescriptionPromptLabel', hintKey: 'novels.keyframeDescriptionPromptHint', templateType: 'keyframe_description', category: 'shot_planning' },
  { key: 'shotImagePromptTemplateId', labelKey: 'novels.shotImagePromptLabel', hintKey: 'novels.shotImagePromptHint', templateType: 'shot_image_prompt', category: 'shot_image' },
  { key: 'keyframePlannerPromptTemplateId', labelKey: 'novels.keyframePlannerPromptLabel', hintKey: 'novels.keyframePlannerPromptHint', templateType: 'keyframe_planner', category: 'video_director' },
  { key: 'keyframeTransitionPromptTemplateId', labelKey: 'novels.keyframeTransitionPromptLabel', hintKey: 'novels.keyframeTransitionPromptHint', templateType: 'keyframe_transition', category: 'video_director' },
  { key: 'clipExecutionPlannerPromptTemplateId', labelKey: 'promptConfig.types.clipExecutionPlanner', hintKey: 'promptConfig.types.clipExecutionPlannerDesc', templateType: 'clip_execution_planner', category: 'video_director' },
  { key: 'temporalReferenceSelectorPromptTemplateId', labelKey: 'promptConfig.types.temporalReferenceSelector', hintKey: 'promptConfig.types.temporalReferenceSelectorDesc', templateType: 'temporal_reference_selector', category: 'keyframe_image' },
  { key: 'keyframeImagePromptTemplateId', labelKey: 'novels.keyframeImagePromptLabel', hintKey: 'novels.keyframeImagePromptHint', templateType: 'keyframe_image_prompt', category: 'keyframe_image' },
  { key: 'imageQualityReviewPromptTemplateId', labelKey: 'promptConfig.types.imageQualityReviewPrompt', hintKey: 'promptConfig.types.imageQualityReviewPromptDesc', templateType: 'image_quality_review_prompt', category: 'keyframe_image' },
  { key: 'h3MultiKeyframePromptTemplateId', labelKey: 'novels.h3MultiKeyframePromptLabel', hintKey: 'novels.h3MultiKeyframePromptHint', templateType: 'h3_multi_keyframe_prompt', category: 'video_generation' },
  { key: 'h3MultiKeyframeDirectorPhaseBTemplateId', labelKey: 'novels.h3MultiKeyframeDirectorPhaseBLabel', hintKey: 'novels.h3MultiKeyframeDirectorPhaseBHint', templateType: 'h3_multi_keyframe_director_phase_b', category: 'video_generation' },
  { key: 'h3ExecutionOptimizerPromptTemplateId', labelKey: 'novels.h3ExecutionOptimizerPromptLabel', hintKey: 'novels.h3ExecutionOptimizerPromptHint', templateType: 'h3_execution_optimizer_prompt', category: 'video_generation' },
  { key: 'h3PreflightRepairPromptTemplateId', labelKey: 'novels.h3PreflightRepairPromptLabel', hintKey: 'novels.h3PreflightRepairPromptHint', templateType: 'h3_preflight_repair_prompt', category: 'video_generation' },
] as const;

export const TEMPLATE_CATEGORIES = [
  { key: 'story_context', labelKey: 'promptConfig.categories.storyContext' },
  { key: 'style_design', labelKey: 'promptConfig.categories.styleDesign' },
  { key: 'asset_parse', labelKey: 'promptConfig.categories.assetParse' },
  { key: 'asset_generation', labelKey: 'promptConfig.categories.assetGeneration' },
  { key: 'shot_planning', labelKey: 'promptConfig.categories.shotPlanning' },
  { key: 'shot_image', labelKey: 'promptConfig.categories.shotImage' },
  { key: 'video_director', labelKey: 'promptConfig.categories.videoDirector' },
  { key: 'keyframe_image', labelKey: 'promptConfig.categories.keyframeImage' },
  { key: 'video_generation', labelKey: 'promptConfig.categories.videoGeneration' },
] as const;


export type NovelTemplateFieldKey = typeof TEMPLATE_FIELDS[number]['key'];

export const emptyNovelTemplateSelection = (): Record<NovelTemplateFieldKey, string> =>
  Object.fromEntries(TEMPLATE_FIELDS.map(field => [field.key, ''])) as Record<NovelTemplateFieldKey, string>;
