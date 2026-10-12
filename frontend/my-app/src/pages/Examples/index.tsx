import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BookOpen, ChevronRight, Eye, Import, Loader2, X } from 'lucide-react';
import { examplesApi, type ExampleDetail, type ExampleSummary } from '../../api/examples';
import { toast } from '../../stores/toastStore';

export default function Examples() {
  const navigate = useNavigate();
  const [examples, setExamples] = useState<ExampleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<ExampleDetail | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [chapterIndex, setChapterIndex] = useState(0);
  const [importingId, setImportingId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    examplesApi.list().then(data => { if (active) setExamples(data); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setPreview(null); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, []);

  async function openPreview(id: string) {
    setPreview(null);
    setPreviewError('');
    setPreviewLoading(true);
    setChapterIndex(0);
    try {
      setPreview(await examplesApi.detail(id));
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function importExample(id: string) {
    setImportingId(id);
    try {
      const result = await examplesApi.import(id);
      toast.success(`导入成功，已创建 ${result.chapter_count} 个章回`);
      navigate(`/novels/${result.novel_id}`);
    } catch (err) {
      toast.error(`导入失败：${err instanceof Error ? err.message : String(err)}`, 6000);
    } finally {
      setImportingId(null);
    }
  }

  return <div className="mx-auto max-w-7xl space-y-7 p-6" data-testid="examples-page">
    <header>
      <div className="flex items-center gap-3">
        <div className="rounded-xl bg-blue-50 p-2.5 text-blue-600"><BookOpen className="h-6 w-6" /></div>
        <div><h1 className="text-2xl font-semibold text-gray-900">示例小说</h1><p className="mt-1 text-sm text-gray-500">选择预设小说，快速导入 NovelFlow，之后可以自由进行解析、分镜和视频创作。</p></div>
      </div>
    </header>
    {loading && <div className="flex items-center gap-2 py-16 text-gray-500"><Loader2 className="h-5 w-5 animate-spin" />正在读取示例…</div>}
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">读取示例失败：{error}</p>}
    <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
      {examples.map(example => <article key={example.id} className="flex min-h-[260px] flex-col rounded-2xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md" data-testid={`example-card-${example.id}`}>
        <div className="mb-5 flex items-start justify-between gap-3"><div className="rounded-xl bg-blue-50 p-3 text-blue-600"><BookOpen className="h-6 w-6" /></div><span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">{example.category}</span></div>
        <h2 className="text-xl font-semibold text-gray-900">{example.title}</h2>
        <p className="mt-3 flex-1 text-sm leading-6 text-gray-600">{example.description}</p>
        <p className="mt-4 text-sm text-gray-500">共 {example.chapterCount} 章</p>
        <div className="mt-5 flex flex-wrap gap-2 border-t border-gray-100 pt-5">
          <button type="button" onClick={() => void openPreview(example.id)} className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"><Eye className="h-4 w-4" />预览内容</button>
          <button type="button" onClick={() => void importExample(example.id)} disabled={importingId !== null} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">{importingId === example.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Import className="h-4 w-4" />}导入小说</button>
        </div>
      </article>)}
    </section>
    {(previewLoading || previewError || preview) && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={event => { if (event.target === event.currentTarget) { setPreview(null); setPreviewError(''); setPreviewLoading(false); } }}>
      <div role="dialog" aria-modal="true" aria-label="示例小说预览" className="flex h-[min(85vh,840px)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b px-6 py-5"><div><h2 className="text-xl font-semibold text-gray-900">{preview?.title || '示例小说预览'}</h2>{preview && <p className="mt-2 text-sm leading-6 text-gray-600">{preview.description}</p>}</div><button aria-label="关闭预览" onClick={() => { setPreview(null); setPreviewError(''); setPreviewLoading(false); }} className="rounded-lg p-1 text-gray-500 hover:bg-gray-100"><X className="h-5 w-5" /></button></header>
        {previewLoading && <p className="p-6 text-gray-500">正在读取正文…</p>}
        {previewError && <p role="alert" className="p-6 text-red-600">预览失败：{previewError}</p>}
        {preview && <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <nav aria-label="章回目录" className="w-full shrink-0 overflow-y-auto border-b bg-gray-50 p-3 md:w-64 md:border-b-0 md:border-r"><p className="px-3 pb-2 text-xs font-semibold text-gray-500">章回目录 · {preview.chapters.length} 章</p>{preview.chapters.map((chapter, index) => <button key={chapter.number} type="button" onClick={() => setChapterIndex(index)} className={`mb-1 flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm ${index === chapterIndex ? 'bg-blue-100 font-medium text-blue-700' : 'text-gray-700 hover:bg-gray-100'}`}><span>{chapter.title}</span>{index === chapterIndex && <ChevronRight className="h-4 w-4 shrink-0" />}</button>)}</nav>
          <article className="min-h-0 flex-1 overflow-y-auto px-6 py-6 md:px-8"><p className="text-xs font-medium text-blue-600">第 {preview.chapters[chapterIndex]?.number} 章</p><h3 className="mt-2 text-xl font-semibold text-gray-900">{preview.chapters[chapterIndex]?.title}</h3><div className="mt-6 whitespace-pre-wrap break-words text-base leading-8 text-gray-700" data-testid="example-chapter-content">{preview.chapters[chapterIndex]?.content}</div></article>
        </div>}
      </div>
    </div>}
  </div>;
}
