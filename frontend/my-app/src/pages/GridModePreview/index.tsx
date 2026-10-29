import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, Film, Image, LayoutGrid, RotateCcw } from 'lucide-react';

type Stage = 'shot_split' | 'shot_image' | 'video_gen';
type Panel = { camera: string; beat: string; status: '通过' | '待复核'; clip: number };
type Clip = { title: string; duration: number; panels: number[]; dialogue: string[]; prompt: string };
type PreviewShot = { title: string; beat: string; board: string; panels: Panel[]; clips: Clip[] };

// Stage 3 uses approved Chapter 1 experiment boards as fixed visual fixtures.
// No preview action writes to a novel, Shot, Task, or ComfyUI.
const shots: PreviewShot[] = [
  {
    title: '山路抵村', beat: '杜甫从山路走向村落，黄昏将尽。',
    board: '/previews/grid-mode/shot-01-board.jpg',
    panels: [
      { camera: '远景 · 高机位', beat: '空山与蜿蜒山路，建立村外空间。', status: '通过', clip: 1 },
      { camera: '中远景 · 平视', beat: '杜甫进入山路，保留行进方向。', status: '通过', clip: 1 },
      { camera: '近景 · 正面', beat: '杜甫停步观察村落。', status: '通过', clip: 2 },
      { camera: '特写 · 低机位', beat: '脚步落定，行囊随之停下。', status: '待复核', clip: 2 },
    ],
    clips: [
      { title: 'C1 · 抵达', duration: 8, panels: [1, 2], dialogue: [], prompt: '' },
      { title: 'C2 · 停步', duration: 6, panels: [3, 4], dialogue: [], prompt: '' },
    ],
  },
  {
    title: '门前试探', beat: '破旧农舍门前，杜甫与老妪互相打量。',
    board: '/previews/grid-mode/shot-04-board.jpg',
    panels: [
      { camera: '近景 · 老妪', beat: '老妪在门边迟疑，背景保留木门。', status: '通过', clip: 1 },
      { camera: '近景 · 杜甫', beat: '反打杜甫，维持人物轴线。', status: '通过', clip: 1 },
      { camera: '特写 · 老妪', beat: '老妪眉眼中的迟疑。', status: '通过', clip: 2 },
      { camera: '中景 · 老翁', beat: '老翁坐在院角，交代第三人的位置。', status: '通过', clip: 2 },
    ],
    clips: [
      { title: 'C1 · 门前反打', duration: 9, panels: [1, 2], dialogue: ['老妪：你是何人？', '杜甫：路过此地，想借宿一晚。'], prompt: '' },
      { title: 'C2 · 院内反应', duration: 7, panels: [3, 4], dialogue: [], prompt: '' },
    ],
  },
  {
    title: '院门交谈', beat: '老妪回望院内，老翁应声，杜甫等待答复。',
    board: '/previews/grid-mode/shot-05-board.jpg',
    panels: [
      { camera: '过肩拍 · 中景', beat: '从老翁肩后看老妪，建立视线关系。', status: '通过', clip: 1 },
      { camera: '近景 · 老翁', beat: '反打老翁，人物仍处于院门轴线内。', status: '通过', clip: 1 },
      { camera: '双人中景 · 平视', beat: '杜甫与老妪同框，老翁留在门内。', status: '待复核', clip: 2 },
      { camera: '空镜 · 拉远', beat: '人物退场后停留在院门，承接下个 Shot。', status: '通过', clip: 2 },
    ],
    clips: [
      {
        title: 'C1 · 过肩与反打', duration: 10, panels: [1, 2],
        dialogue: ['老妪：让他进来吧。', '老翁：兵荒马乱的，进出门都不容易。'],
        prompt: `subject_definitions:\n<Subject 1> = 老妪，灰白发、深色旧衣，站在院门左侧。\n<Subject 2> = 老翁，灰须、深灰旧衣，站在院内。\nsummary:\nGenerate a 10-second Ref2VA scene using <Picture 1> and <Picture 2>.\nretention_analysis:\n<Picture 1> anchors the over-the-shoulder composition; <Picture 2> anchors the reverse close-up. Preserve <Subject 1> and <Subject 2>.\ndetailed_description:\n[Shot 1] Begin over <Subject 2>'s shoulder toward <Subject 1>. Keep the courtyard axis. <Subject 1> (S1) [D1 @ 1.0-3.0s generated-clip] speaks <d>让他进来吧。</d>\n[Shot 2] At 00:04.000 cut to a close-up of <Subject 2>. <Subject 2> (S2) [D2 @ 5.0-8.5s generated-clip] speaks <d>兵荒马乱的，进出门都不容易。</d>\noverall_soundscape:\nQuiet dusk ambience, footsteps and a wooden door creak.\nnon_diegetic_music:\nNone`,
      },
      {
        title: 'C2 · 双人到空镜', duration: 8, panels: [3, 4],
        dialogue: ['杜甫：多谢老人家。'],
        prompt: `subject_definitions:\n<Subject 1> = 老妪，灰白发、深色旧衣，站在院门内。\n<Subject 3> = 杜甫，束发、褐色旧袍，站在院门外。\nsummary:\nGenerate an 8-second Ref2VA scene using <Picture 1> and <Picture 2>.\nretention_analysis:\n<Picture 1> anchors the two-person composition; <Picture 2> anchors the empty courtyard. Preserve <Subject 1> and <Subject 3>.\ndetailed_description:\n[Shot 1] Hold a two-person medium shot. <Subject 3> (S3) [D3 @ 1.0-3.0s generated-clip] speaks <d>多谢老人家。</d>\n[Shot 2] At 00:04.000 pull back toward the empty courtyard after both Subjects leave frame.\noverall_soundscape:\nSoft footsteps and quiet dusk wind.\nnon_diegetic_music:\nNone`,
      },
    ],
  },
];

const stageLabels: { key: Stage; label: string }[] = [
  { key: 'shot_split', label: '分镜拆分' },
  { key: 'shot_image', label: '分镜图生成' },
  { key: 'video_gen', label: '视频生成' },
];

function PlannedAction({ children, primary = false }: { children: React.ReactNode; primary?: boolean }) {
  return <button type="button" disabled title="静态预览：将在生成 API 接入后启用"
    className={`rounded-lg border px-3 py-2 text-sm font-medium opacity-65 cursor-not-allowed ${primary ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-200 bg-white text-gray-600'}`}>{children}</button>;
}

function WorkflowActions({ stage, shotIndex }: { stage: Stage; shotIndex: number }) {
  return <section aria-label="当前阶段操作" className="rounded-xl border border-gray-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold text-gray-900">{stage === 'shot_split' ? '准备素材与拆分' : stage === 'shot_image' ? '生成与审阅宫格' : '规划 Clip 与生成视频'}</h2>
      <p className="mt-1 text-xs text-gray-500">静态流程预览 · 生成操作待接入</p></div><span className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-600">当前 Shot {shotIndex + 1} / {shots.length}</span></div>
    {stage === 'shot_split' && <div className="mt-3 flex flex-wrap gap-2"><PlannedAction primary>AI 拆分本章</PlannedAction><PlannedAction>保存分镜</PlannedAction></div>}
    {stage === 'shot_image' && <div className="mt-3 flex flex-wrap gap-2"><PlannedAction primary>生成当前宫格</PlannedAction><PlannedAction>批量生成本章宫格</PlannedAction><PlannedAction>上传替换整板</PlannedAction><PlannedAction>重新生成当前宫格</PlannedAction></div>}
    {stage === 'video_gen' && <div className="mt-3 space-y-3"><div><p className="mb-2 text-xs font-medium text-gray-500">先规划，再生成</p><div className="flex flex-wrap gap-2"><PlannedAction>规划本 Shot 的 Clip</PlannedAction><PlannedAction primary>生成当前 Clip</PlannedAction><PlannedAction>批量生成本 Shot</PlannedAction><PlannedAction>批量生成本章</PlannedAction></div></div>
      <div><p className="mb-2 text-xs font-medium text-gray-500">结果与交付</p><div className="flex flex-wrap gap-2"><PlannedAction>合并本 Shot</PlannedAction><PlannedAction>合并章回视频</PlannedAction><PlannedAction>导出章回素材</PlannedAction></div></div></div>}
  </section>;
}

function PanelImage({ board, index, className = '' }: { board: string; index: number; className?: string }) {
  const positions = ['0% 0%', '100% 0%', '0% 100%', '100% 100%'];
  return <div role="img" aria-label={`宫格子图 ${index + 1}`} className={`aspect-video bg-cover bg-no-repeat ${className}`}
    style={{ backgroundImage: `url(${board})`, backgroundSize: '200% 200%', backgroundPosition: positions[index % 4] }} />;
}

export default function GridModePreview() {
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const [stage, setStage] = useState<Stage>('shot_image');
  const [shotIndex, setShotIndex] = useState(2);
  const [panelIndex, setPanelIndex] = useState(0);
  const [clipIndex, setClipIndex] = useState(0);
  const [imageView, setImageView] = useState<'board' | 'panels'>('board');
  const [layoutExample, setLayoutExample] = useState<'2x2' | '2x3'>('2x2');
  const shot = shots[shotIndex];
  const clip = shot.clips[clipIndex];
  const selectShot = (index: number) => { setShotIndex(index); setPanelIndex(0); setClipIndex(0); setLayoutExample('2x2'); };
  const oldPage = `/novels/${id}/chapters/${cid}/generate`;

  return <div className="min-h-full bg-gray-50 pb-10">
    <header className="border-b border-gray-200 bg-white px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link to={oldPage} aria-label="返回现有章回页" className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"><ArrowLeft className="h-5 w-5" /></Link>
          <div><h1 className="text-lg font-semibold text-gray-900">第一章：黄昏投宿 <span className="ml-2 rounded-full bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">宫格模式 · 静态预览</span></h1>
            <p className="mt-1 text-xs text-gray-500">3 个叙事 Shot · 12 个子格 · 6 条 Clip · 样例数据不写入现有小说</p></div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Link to="/novels" className="rounded-lg border border-gray-200 px-3 py-1.5 hover:bg-gray-50">在小说管理中创建／编辑小说</Link>
          <Link to={oldPage} className="rounded-lg border border-gray-200 px-3 py-1.5 hover:bg-gray-50">查看现有单镜页面</Link>
        </div>
      </div>
    </header>
    <>
      <nav aria-label="生成阶段" className="flex gap-1 overflow-x-auto whitespace-nowrap border-b border-gray-200 bg-white px-6 pt-2">
        {stageLabels.map(item => <button type="button" key={item.key} onClick={() => setStage(item.key)}
          className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm ${stage === item.key ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-800'}`}>{item.label}</button>)}
        <span className="px-4 py-3 text-sm text-gray-300">音频生成</span><span className="px-4 py-3 text-sm text-gray-300">高清重绘</span>
      </nav>
      <div className="grid gap-4 p-5 xl:grid-cols-[250px_minmax(0,1fr)_300px]">
        <aside className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-gray-900">叙事 Shot</h2><span className="text-xs text-gray-500">3 个</span></div>
          <p className="mb-3 text-xs text-gray-500">一个 Shot 管一段情节；子格只属于当前 Shot。</p>
          <div className="flex gap-2 overflow-x-auto xl:block xl:space-y-2">{shots.map((item, index) => <button type="button" key={item.title} onClick={() => selectShot(index)}
            className={`min-w-[180px] flex-1 overflow-hidden rounded-lg border text-left xl:min-w-0 ${index === shotIndex ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-blue-200'}`}>
            <img src={item.board} alt={`${item.title} 宫格缩略图`} className="aspect-video w-full object-cover" />
            <span className="block px-3 py-2 text-sm font-medium text-gray-900">Shot {index + 1} · {item.title}</span>
            <span className="block px-3 pb-2 text-xs text-gray-500">2×2 · 4 格 · {item.clips.length} Clips</span>
          </button>)}</div>
        </aside>

        <main className="min-w-0 space-y-4">
          <WorkflowActions stage={stage} shotIndex={shotIndex} />
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-gray-900">Shot {shotIndex + 1} · {shot.title}</h2><p className="mt-1 text-sm text-gray-600">{shot.beat}</p></div><span className="rounded-full bg-indigo-50 px-3 py-1 text-xs text-indigo-700">宫格 Shot · 2×2 · 每格 16:9</span></div>
            {stage === 'shot_split' && <div className="mt-5 space-y-4">
              <div><p className="mb-2 text-sm font-medium text-gray-800">版式规划示意</p><div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setLayoutExample('2x2')} className={`rounded-lg border px-3 py-2 text-sm ${layoutExample === '2x2' ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200'}`}>2×2 · 4 格</button>
                <button type="button" onClick={() => setLayoutExample('2x3')} className={`rounded-lg border px-3 py-2 text-sm ${layoutExample === '2x3' ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200'}`}>2×3 · 6 格</button>
                <span className="rounded-lg border border-dashed border-gray-200 px-3 py-2 text-sm text-gray-400">3×3 · 实验候选</span>
              </div><p className="mt-2 text-xs text-gray-500">版式选择只演示布局；下面始终显示当前 Shot 的四张真实实验子格。</p></div>
              <div className={`grid gap-2 ${layoutExample === '2x3' ? 'grid-cols-3' : 'grid-cols-2'}`}>
                {Array.from({ length: layoutExample === '2x3' ? 6 : 4 }, (_, index) => <div key={index} className="flex aspect-video items-center justify-center rounded-md border border-dashed border-blue-200 bg-blue-50 text-sm text-blue-700">格 {index + 1}</div>)}
              </div>
              <ol className="space-y-2">{shot.panels.map((panel, index) => <li key={index} className="rounded-lg bg-gray-50 p-3 text-sm"><strong>格 {index + 1} · {panel.camera}</strong><span className="ml-2 text-gray-600">{panel.beat}</span></li>)}</ol>
            </div>}
            {stage === 'shot_image' && <div className="mt-5">
              <div className="mb-3 flex gap-2"><button type="button" onClick={() => setImageView('board')} className={`rounded-lg px-3 py-1.5 text-sm ${imageView === 'board' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'}`}><LayoutGrid className="mr-1 inline h-4 w-4" />整板</button>
                <button type="button" onClick={() => setImageView('panels')} className={`rounded-lg px-3 py-1.5 text-sm ${imageView === 'panels' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'}`}><Image className="mr-1 inline h-4 w-4" />逐格</button></div>
              {imageView === 'board' ? <div className="relative overflow-hidden rounded-lg bg-gray-900"><img src={shot.board} alt={`${shot.title} 宫格整板`} className="w-full" />
                <div aria-hidden="true" className="pointer-events-none absolute h-1/2 w-1/2 border-2 border-blue-400" style={{ left: `${panelIndex % 2 * 50}%`, top: `${Math.floor(panelIndex / 2) * 50}%` }} /></div>
                : <div className="grid grid-cols-2 gap-2">{shot.panels.map((panel, index) => <button type="button" key={index} onClick={() => setPanelIndex(index)} className={`overflow-hidden rounded-lg border-2 text-left ${panelIndex === index ? 'border-blue-500' : 'border-transparent'}`}><PanelImage board={shot.board} index={index} /><span className="block bg-gray-50 p-2 text-xs">格 {index + 1} · {panel.camera}</span></button>)}</div>}
              <div className="mt-3 grid grid-cols-4 gap-2">{shot.panels.map((panel, index) => <button type="button" key={index} onClick={() => setPanelIndex(index)} className={`rounded-lg border p-1 text-left ${panelIndex === index ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}><PanelImage board={shot.board} index={index} /><span className="mt-1 block text-xs">格 {index + 1}</span></button>)}</div>
              <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium">格 {panelIndex + 1} · {shot.panels[panelIndex].camera}</p><span className={`text-xs ${shot.panels[panelIndex].status === '通过' ? 'text-green-700' : 'text-amber-700'}`}>{shot.panels[panelIndex].status}</span></div>
                <p className="mt-1 text-sm text-gray-600">{shot.panels[panelIndex].beat}</p><p className="mt-1 text-xs text-gray-500">对应 Clip C{shot.panels[panelIndex].clip}</p>
                <div className="mt-3 flex gap-2"><button type="button" disabled title="第六阶段接入逐格评审" className="rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-400">审核通过 · 待接入</button><button type="button" disabled title="第六阶段接入单格重试" className="rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-400"><RotateCcw className="mr-1 inline h-3 w-3" />重做此格 · 待接入</button></div>
              </div>
            </div>}
            {stage === 'video_gen' && <div className="mt-5 space-y-4"><div className="grid gap-3 sm:grid-cols-2">{shot.clips.map((item, index) => <button type="button" key={index} onClick={() => setClipIndex(index)} className={`rounded-lg border p-3 text-left ${clipIndex === index ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}><span className="text-sm font-semibold">{item.title}</span><span className="ml-2 text-xs text-gray-500">{item.duration}s</span><p className="mt-2 text-xs text-gray-600">子格 {item.panels.join(' → ')} · {item.dialogue.length} 句台词</p></button>)}</div>
              <div className="rounded-lg border border-gray-200 p-4"><h3 className="text-sm font-semibold">{clip.title} · H3 实际参考图预览</h3><p className="mt-1 text-xs text-gray-500">Picture 顺序随 Clip 保存。角色身份图仅在需要时另附；整板直传保留为显式策略。</p><div className="mt-3 grid grid-cols-2 gap-3">{clip.panels.map((panelNumber, index) => <div key={panelNumber}><PanelImage board={shot.board} index={panelNumber - 1} className="rounded-md" /><p className="mt-1 text-xs text-gray-600">Picture {index + 1} · 子格 {panelNumber}</p></div>)}</div></div>
              <div className="rounded-lg border border-gray-200 p-4"><h3 className="text-sm font-semibold">台词与说话人</h3>{clip.dialogue.length ? <ol className="mt-2 space-y-1 text-sm text-gray-700">{clip.dialogue.map((line, index) => <li key={index}>{index + 1}. {line}</li>)}</ol> : <p className="mt-2 text-sm text-gray-500">无台词</p>}</div>
              <div className="rounded-lg border border-gray-200 p-4"><h3 className="text-sm font-semibold">H3 六段式提示词预览</h3><p className="mt-1 text-xs text-gray-500">静态示例；实际提示词由第四至六阶段的模式配置和任务生成。</p><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-4 text-xs leading-relaxed text-slate-100">{clip.prompt || '无台词 Clip 的六段式提示词将在生成规划后显示。'}</pre></div>
            </div>}
          </section>
        </main>

        <aside className="space-y-4"><section className="rounded-xl border border-gray-200 bg-white p-4"><h2 className="font-semibold text-gray-900">最终 Shot 视频</h2><div className="relative mt-3 overflow-hidden rounded-lg bg-gray-950"><img src={shot.board} alt="Shot 视频占位图" className="aspect-video w-full object-cover opacity-60" /><div className="absolute inset-0 flex items-center justify-center text-sm text-white"><Film className="mr-2 h-5 w-5" />静态预览 · 尚无视频</div></div><p className="mt-2 text-xs text-gray-500">Clip 合片完成后在这里播放，不改变现有播放器位置。</p></section>
          <section className="rounded-xl border border-gray-200 bg-white p-4"><h2 className="font-semibold text-gray-900">Shot / 章回结果</h2><div className="mt-3 space-y-2 text-sm text-gray-600"><p className="flex justify-between"><span>宫格整板</span><span className="flex items-center text-green-700"><CheckCircle2 className="mr-1 h-4 w-4" />样例已备</span></p><p className="flex justify-between"><span>逐格</span><span>4 / 4</span></p><p className="flex justify-between"><span>Clip 视频</span><span>0 / {shot.clips.length}</span></p><p className="flex justify-between"><span>Shot 成片</span><span>待生成</span></p><p className="flex justify-between border-t pt-2"><span>章回合片</span><span>待生成</span></p></div></section>
        </aside>
      </div>
    </>
  </div>;
}
