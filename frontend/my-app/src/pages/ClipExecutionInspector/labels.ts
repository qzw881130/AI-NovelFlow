import { useI18nStore } from '../../stores/i18nStore';

const en = {
  title: 'Clip Execution Inspector', entry: 'Execution analysis', back: 'Back to video generation', loading: 'Loading…', retry: 'Retry',
  summary: 'Clip Summary', timeline: 'Unified Timeline', filmstrip: 'Filmstrip', frame: 'Frame Inspector', authority: 'Prompt Authority',
  observation: 'Human observations', saveAnalysis: 'Save analysis', saved: 'Saved analysis', newAnalysis: 'New analysis', artifact: 'Execution result',
  sampling: 'Sampling interval', events: 'Include events', neighbors: 'Event ±0.25s', time: 'Requested time', view: 'View frame', next: 'Next page', previous: 'Previous page',
  actual: 'ACTUAL FRAME', expected: 'EXPECTED / PLAN EVIDENCE', exact: 'EXPECTED at exact event/request time', gap: 'No active dialogue at this time',
  unavailable: 'Source not available', unknown: 'Exact timing unknown', save: 'Save observation', saving: 'Saving…', edit: 'Edit', delete: 'Delete', cancel: 'Cancel',
  note: 'Note', start: 'Start (seconds)', end: 'End (optional)', tags: 'Observation tags', noNotes: 'No human observations yet', copy: 'Copy evidence',
  raw: 'Raw execution evidence', current: 'Current plan', speech: 'Speech authority', previousState: 'Previous semantic state', nextState: 'Next semantic state',
  distance: 'Signed distance to target', browserSeek: 'Video seeking is navigation; exact frame evidence comes from the extracted image.',
  clip: 'Clip Time', native: 'Native Time', planned: 'Planned duration', replacement: 'Replacement frames', nativeFrames: 'Whole Native frames', latent: 'Requested latent frames',
  missingMedia: 'Source video is unavailable. Saved evidence and notes remain readable.', sourceChanged: 'Source changed; this analysis retains its saved evidence.',
  noFrames: 'No available frames', marker: 'Marker', untimed: 'Context / untimed evidence', tail: 'Outside planned duration', zoom: 'Zoom',
  revisionMeaning: 'Director / Shot / Clip semantic revision',
  contactSheet: 'Contact sheet', close: 'Close', frameNumber: 'Frame', uniformOnly: 'Uniform samples only', zeroBasedFrames: 'Frame numbers start at 0',
  executionMeaning: 'One semantic Revision can have multiple Execution → Video results. The selector chooses a specific execution result.',
  DIALOGUE: 'Dialogue', LIFECYCLE: 'Lifecycle / Action', MOTION: 'Motion', SEMANTIC_KF: 'Semantic Target', PHYSICAL_ANCHOR: 'Physical Anchor', TRANSITION: 'Transition', CAMERA: 'Camera / Visual Direction', HUMAN: 'Human Observation',
};
type Labels = typeof en;
const zh: Labels = {
  title: '片段执行分析', entry: '执行分析', back: '返回视频生成', loading: '正在加载…', retry: '重试', summary: '片段概览', timeline: '统一时间轴', filmstrip: '抽样帧', frame: '帧检查', authority: 'Prompt Authority',
  observation: '人工观察', saveAnalysis: '保存分析', saved: '已保存分析', newAnalysis: '新建分析', artifact: '执行结果', sampling: '采样间隔', events: '加入事件', neighbors: '事件附近 ±0.25s', time: '请求时间', view: '查看帧', next: '下一页', previous: '上一页',
  actual: 'ACTUAL FRAME · 实际画面', expected: 'EXPECTED / PLAN EVIDENCE · 计划证据', exact: '事件/请求精确时间的 EXPECTED', gap: '此刻没有已分配的台词', unavailable: '来源不可用', unknown: '精确时刻未知', save: '保存人工标记', saving: '正在保存…', edit: '编辑', delete: '删除', cancel: '取消',
  note: '备注', start: '开始时间（秒）', end: '结束时间（可选）', tags: '观察标签', noNotes: '尚无人工观察', copy: '复制证据', raw: '执行原始证据', current: '当前计划', speech: 'Speech authority', previousState: '前一语义状态', nextState: '下一语义状态', distance: '距目标的带符号时间',
  browserSeek: '视频定位用于导航；精确帧证据以抽取图片为准。', clip: 'Clip Time · 片段局部时间', native: 'Native Time · 文件时间', planned: '计划时长', replacement: 'Replacement 帧数', nativeFrames: '完整 Native 帧数', latent: '请求 latent 帧数',
  missingMedia: '源视频不可用；已保存的证据和人工标记仍可读取。', sourceChanged: '源数据已改变；此分析保留保存时的证据。', noFrames: '没有可用帧', marker: '人工标记', untimed: '上下文 / 无精确时间证据', tail: '超出计划时长', zoom: '缩放',
  revisionMeaning: 'Director / Shot / Clip 语义修订',
  contactSheet: '合并帧图', close: '关闭', frameNumber: '帧', uniformOnly: '仅按采样间隔取帧', zeroBasedFrames: '帧号从 0 开始',
  executionMeaning: 'Revision 表示语义修订；同一 Revision 可有多个 Execution → Video。下拉框选择具体执行结果。',
  DIALOGUE: '对白', LIFECYCLE: 'Lifecycle / 角色动作', MOTION: 'Motion / 运动要求', SEMANTIC_KF: 'Semantic Target · 语义 KF', PHYSICAL_ANCHOR: 'Physical Anchor · 物理锚点', TRANSITION: '过渡', CAMERA: 'Camera / 画面要求', HUMAN: '人工观察',
};
const locales: Record<string, Labels> = {
  'en-US': en, 'zh-CN': zh,
  'zh-TW': { ...zh, title: '片段執行分析', entry: '執行分析', back: '返回影片生成', timeline: '統一時間軸', filmstrip: '抽樣影格', frame: '影格檢查', observation: '人工觀察', saveAnalysis: '儲存分析', save: '儲存人工標記', delete: '刪除', edit: '編輯', note: '備註', loading: '正在載入…' },
  'ja-JP': { ...en, title: 'クリップ実行分析', entry: '実行分析', back: '動画生成へ戻る', summary: 'クリップ概要', timeline: '共通タイムライン', filmstrip: '抽出フレーム', frame: 'フレーム検査', observation: '手動の観察', saveAnalysis: '分析を保存', save: '観察を保存', delete: '削除', edit: '編集', note: 'メモ', loading: '読み込み中…', unavailable: 'ソースを取得できません', unknown: '正確な時刻は不明' },
  'ko-KR': { ...en, title: '클립 실행 분석', entry: '실행 분석', back: '동영상 생성으로 돌아가기', summary: '클립 요약', timeline: '통합 타임라인', filmstrip: '추출 프레임', frame: '프레임 검사', observation: '수동 관찰', saveAnalysis: '분석 저장', save: '관찰 저장', delete: '삭제', edit: '편집', note: '메모', loading: '불러오는 중…', unavailable: '소스를 사용할 수 없음', unknown: '정확한 시점 알 수 없음' },
};
export function useInspectorLabels(): Labels { return locales[useI18nStore(s => s.language)] || en; }
