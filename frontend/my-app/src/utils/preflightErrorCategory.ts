// Keep these names aligned with the two validation catalogs shown in Settings.
export const videoCheckLabels: Record<string, string> = {
  SHOT_EXISTS: '分镜归属',
  SHOT_IMAGE_READY: '主分镜图',
  CLIP_PLAN_READY: '片段计划',
  TASK_RELATION_VALID: '任务关系',
  ACTIVE_VIDEO_TASK: '重复执行',
  IDENTITY_FEATURES_RECORDED: '人物稳定特征',
  IDENTITY_PORTRAIT_READY: '人物参考图',
  VISUAL_PLAN_CONTRACT: '视觉状态与过渡计划',
  REQUIRED_IMAGE_RESOURCES: '必需关键帧图片',
  CLIP_EXECUTION_INPUT: 'Clip 执行输入',
  VIDEO_WORKFLOW_CONFIGURATION: '视频工作流配置',
  PHASE_B_SOURCE_BINDING: 'Phase B 输入与续接来源',
  PHASE_B_PLAN_REUSE: '导演计划复用',
  PHASE_B_DIRECTOR_SCHEMA: '导演输出格式',
  PHASE_B_TIMING_ANCHORS: '对白时间与关键帧',
  PHASE_B_LANGUAGE_CONSISTENCY: '提示词语言一致性',
  PHASE_B_PROMPT_STRUCTURE: '视频提示词结构',
  PHASE_B_PICTURE_BINDING: '图片引用绑定',
  PHASE_B_WORKFLOW_BINDING: '工作流提交绑定',
  VIDEO_OUTPUT_ARTIFACT: '视频输出文件',
  CLIP_RESULT_RECOVERY: 'Clip 结果恢复与回写',
  CLIP_RECEIPT_ACCEPTANCE: '已完成 Clip 回执接受',
  CLIP_ASSEMBLY_PROVENANCE: '片段合并来源',
};

export const gridCheckLabels: Record<string, string> = {
  GRID_CHAPTER_INPUT: '章回输入与覆盖保护',
  GRID_TASK_OWNERSHIP: '任务归属与并发',
  GRID_SHOT_PLAN_CONTRACT: '叙事 Shot 与台词',
  GRID_PANEL_PLAN_CONTRACT: '宫格与台词分配',
  GRID_IMAGE_INPUT_OUTPUT: '生图输入与图片文件',
  GRID_PANEL_AI_REVIEW: '自动逐格 AI 初审',
  GRID_PANEL_FAIL_RETRY: '初审 FAIL 自动重做一次',
  GRID_PANEL_NON_FAIL: '子格进入 Clip 的条件',
  GRID_CLIP_PLAN_CONTRACT: 'Clip 时间轴与台词',
  GRID_H3_INPUT_BINDING: 'H3 提示词与参考图',
  GRID_VIDEO_VISUAL_REVIEW: 'Clip 成片人物验收',
  GRID_VIDEO_ARTIFACT: '视频文件与合并来源',
};

const codeCategories: Array<[RegExp, string]> = [
  [/CLIP_RECEIPT_ACCEPTANCE_/, videoCheckLabels.CLIP_RECEIPT_ACCEPTANCE],
  [/CLIP_RECOVERY_|CANONICAL_RECOVERY_CONFLICT|CANDIDATE_SOURCE_CHANGED|EXECUTION_PROJECTION_/, videoCheckLabels.CLIP_RESULT_RECOVERY],
  [/H3_PROMPT_LANGUAGE_MISMATCH/, videoCheckLabels.PHASE_B_LANGUAGE_CONSISTENCY],
  [/PHASE_B_PREFLIGHT_FAILED|PHASE_B_FINAL_PROMPT_CHANGED/, videoCheckLabels.PHASE_B_PROMPT_STRUCTURE],
  [/PHASE_B_INPUT_NOT_COVERED|PREVIOUS_AV_BINDING_UNVERIFIED|PREVIOUS_AV_UNAVAILABLE|PHASE_B_TEMPORAL_SOURCE_CHANGED/, videoCheckLabels.PHASE_B_SOURCE_BINDING],
  [/PHASE_B_REUSABLE_PLAN_MISSING|PHASE_B_CURRENT_PROMPT_CHANGED/, videoCheckLabels.PHASE_B_PLAN_REUSE],
  [/DIRECTOR_RESPONSE_FIELDS_INVALID|DIRECTOR_PROSE_REQUIRED|H3_SINGLE_STAGE_DIRECTOR_SECTIONS_INVALID/, videoCheckLabels.PHASE_B_DIRECTOR_SCHEMA],
  [/H3_PHASE_B_UNDEFINED_SUBJECT_REFERENCE/, videoCheckLabels.PHASE_B_PROMPT_STRUCTURE],
  [/PHASE_B_REFERENCE_PATH_MISMATCH|PHASE_B_REFERENCE_SOURCE_CHANGED/, videoCheckLabels.PHASE_B_PICTURE_BINDING],
  [/PHASE_B_SUBMISSION_BINDING_FAILED|PHASE_B_WORKFLOW_MODE_MISMATCH/, videoCheckLabels.PHASE_B_WORKFLOW_BINDING],
  [/DIALOGUE_DURATION_INSUFFICIENT/, videoCheckLabels.PHASE_B_TIMING_ANCHORS],
  [/视频输出解码校验失败|视频文件校验失败|RAW_CLIP_RECEIPT_UNAVAILABLE|NATIVE_CONTINUITY_OUTPUT_UNAVAILABLE/, videoCheckLabels.VIDEO_OUTPUT_ARTIFACT],
];

const gridStepCategories: Record<string, string> = {
  chapter_plan: gridCheckLabels.GRID_SHOT_PLAN_CONTRACT,
  panels_plan: gridCheckLabels.GRID_PANEL_PLAN_CONTRACT,
  board_prepare: gridCheckLabels.GRID_IMAGE_INPUT_OUTPUT,
  board_generate: gridCheckLabels.GRID_IMAGE_INPUT_OUTPUT,
  panel_generate: gridCheckLabels.GRID_IMAGE_INPUT_OUTPUT,
  clips_plan: gridCheckLabels.GRID_CLIP_PLAN_CONTRACT,
  clip_prepare: gridCheckLabels.GRID_H3_INPUT_BINDING,
  shot_merge: gridCheckLabels.GRID_VIDEO_ARTIFACT,
  chapter_merge: gridCheckLabels.GRID_VIDEO_ARTIFACT,
};

export function preflightErrorCategory(message?: string | null, gridStep?: string | null): string | null {
  if (!message) return null;
  const catalogLabels = { ...videoCheckLabels, ...gridCheckLabels };
  const explicit = message.match(/\[([^\]]+)\]/)?.[1];
  if (explicit && Object.values(catalogLabels).includes(explicit)) return explicit;
  // An aggregate report can contain every check ID, including PASS entries.
  if (message.includes('GENERATION_PREFLIGHT_FAILED')) {
    const mentioned = Object.keys(catalogLabels).filter(id => message.includes(id));
    return mentioned.length === 1 ? catalogLabels[mentioned[0]] : '视频生成预检';
  }
  const checkId = Object.keys(catalogLabels).find(id => message.includes(id));
  if (checkId) return catalogLabels[checkId];
  if (message.includes('成片视觉验收')) return gridCheckLabels.GRID_VIDEO_VISUAL_REVIEW;
  if (message.includes('PHASE_B_PREFLIGHT_FAILED') && /picture_audit['"]?\s*:\s*(?:false|False)/.test(message))
    return videoCheckLabels.PHASE_B_PICTURE_BINDING;
  const coded = codeCategories.find(([pattern]) => pattern.test(message));
  if (coded) return coded[1];
  if (gridStep === 'clip_generate') {
    if (/参考图|提示词|Subject|Speaker|H3.*输入/.test(message)) return gridCheckLabels.GRID_H3_INPUT_BINDING;
    if (/视频文件|视频输出|合并|解码/.test(message)) return gridCheckLabels.GRID_VIDEO_ARTIFACT;
  }
  if (gridStep === 'clips_plan' && /子格|初审 FAIL|图片/.test(message)) return gridCheckLabels.GRID_PANEL_NON_FAIL;
  return gridStep ? gridStepCategories[gridStep] || null : null;
}
