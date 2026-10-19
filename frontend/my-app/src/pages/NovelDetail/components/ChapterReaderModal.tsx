import { useEffect, useRef, useState } from 'react';
import { BookOpen, ChevronLeft, ChevronRight, Loader2, Minus, Plus, X } from 'lucide-react';
import { chapterApi } from '../../../api/chapters';
import type { Chapter } from '../../../types';

interface ChapterReaderModalProps {
  novelId: string;
  novelTitle: string;
  chapters: Chapter[];
  onClose: () => void;
}

const MIN_FONT_SIZE = 14;
const MAX_FONT_SIZE = 26;

export function ChapterReaderModal({ novelId, novelTitle, chapters, onClose }: ChapterReaderModalProps) {
  const [chapterIndex, setChapterIndex] = useState(0);
  const [fontSize, setFontSize] = useState(18);
  const [loadedChapter, setLoadedChapter] = useState<{ id: string; content: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retryCount, setRetryCount] = useState(0);
  const contentCache = useRef(new Map<string, string>());
  const readingArea = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const chapter = chapters[chapterIndex];
  const content = loadedChapter?.id === chapter?.id ? loadedChapter.content : null;

  useEffect(() => {
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, [onClose]);

  useEffect(() => {
    if (!chapter) return;
    let active = true;
    readingArea.current?.scrollTo({ top: 0 });
    setError('');

    const cached = contentCache.current.get(chapter.id);
    if (cached !== undefined) {
      setLoadedChapter({ id: chapter.id, content: cached });
      setLoading(false);
      return;
    }

    setLoadedChapter(null);
    setLoading(true);
    chapterApi.fetchForReading(novelId, chapter.id).then(response => {
      if (!response.success || !response.data) throw new Error(response.message || '无法读取章回');
      const text = response.data.content || '';
      contentCache.current.set(chapter.id, text);
      if (active) setLoadedChapter({ id: chapter.id, content: text });
    }).catch(cause => {
      if (active) setError(cause instanceof Error ? cause.message : '读取章回失败');
    }).finally(() => {
      if (active) setLoading(false);
    });

    return () => { active = false; };
  }, [novelId, chapter?.id, retryCount]);

  const changeChapter = (index: number) => {
    if (index >= 0 && index < chapters.length) setChapterIndex(index);
  };

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/55 p-3 sm:p-6"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="chapter-reader-title"
        className="flex h-[min(92vh,900px)] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h2 id="chapter-reader-title" className="truncate text-lg font-semibold text-gray-900">{novelTitle}</h2>
            <p className="text-xs text-gray-500">阅读 · 第 {chapterIndex + 1} / {chapters.length} 章</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg border border-gray-200 p-1" aria-label="字号设置">
              <span className="pl-2 text-xs text-gray-500">字号</span>
              <button type="button" aria-label="缩小字号" title="缩小字号" disabled={fontSize <= MIN_FONT_SIZE}
                onClick={() => setFontSize(size => Math.max(MIN_FONT_SIZE, size - 2))}
                className="rounded p-1.5 text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"><Minus className="h-4 w-4" /></button>
              <span className="min-w-[3.5rem] text-center text-sm text-gray-600" aria-live="polite">{fontSize} px</span>
              <button type="button" aria-label="放大字号" title="放大字号" disabled={fontSize >= MAX_FONT_SIZE}
                onClick={() => setFontSize(size => Math.min(MAX_FONT_SIZE, size + 2))}
                className="rounded p-1.5 text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"><Plus className="h-4 w-4" /></button>
            </div>
            <button ref={closeButton} type="button" onClick={onClose} aria-label="关闭阅读器" title="关闭阅读器"
              className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700"><X className="h-5 w-5" /></button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <nav aria-label="章回目录" className="hidden w-64 shrink-0 overflow-y-auto border-r border-gray-200 bg-gray-50 p-3 md:block">
            <p className="px-3 pb-2 text-xs font-semibold text-gray-500">章回目录 · 共 {chapters.length} 章</p>
            {chapters.map((item, index) => (
              <button key={item.id} type="button" onClick={() => changeChapter(index)} aria-current={index === chapterIndex ? 'page' : undefined}
                className={`mb-1 w-full rounded-lg px-3 py-2 text-left text-sm ${index === chapterIndex ? 'bg-primary-100 font-medium text-primary-700' : 'text-gray-700 hover:bg-gray-100'}`}>
                <span className="block truncate">{item.title}</span>
              </button>
            ))}
          </nav>
          <div className="border-b border-gray-200 p-3 md:hidden">
            <label htmlFor="reader-chapter-select" className="sr-only">选择章回</label>
            <select id="reader-chapter-select" value={chapterIndex} onChange={event => changeChapter(Number(event.target.value))}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800">
              {chapters.map((item, index) => <option key={item.id} value={index}>{item.title}</option>)}
            </select>
          </div>
          <article ref={readingArea} className="min-h-0 flex-1 overflow-y-auto bg-[#fdfbf7] px-5 py-7 sm:px-10 sm:py-10">
            <div className="mx-auto max-w-3xl">
              <p className="text-sm font-medium text-primary-600">第 {chapter?.number ?? chapterIndex + 1} 章</p>
              <h3 className="mt-2 text-2xl font-semibold leading-snug text-gray-900">{chapter?.title}</h3>
              <div className="mt-8 border-t border-gray-200 pt-7">
                {loading && <p className="flex items-center gap-2 text-gray-500"><Loader2 className="h-4 w-4 animate-spin" />正在读取正文…</p>}
                {error && <div role="alert" className="text-red-600"><p>读取失败：{error}</p><button type="button" onClick={() => setRetryCount(count => count + 1)} className="mt-3 text-sm underline">重试</button></div>}
                {!loading && !error && content === '' && <p className="flex items-center gap-2 text-gray-500"><BookOpen className="h-5 w-5" />本章暂无正文</p>}
                {!loading && !error && content && <div className="whitespace-pre-wrap break-words text-gray-800" style={{ fontSize: `${fontSize}px`, lineHeight: 1.9 }}>{content}</div>}
              </div>
            </div>
          </article>
        </div>

        <footer className="flex items-center justify-between border-t border-gray-200 bg-white px-4 py-3 sm:px-6">
          <button type="button" onClick={() => changeChapter(chapterIndex - 1)} disabled={chapterIndex === 0}
            className="btn-secondary px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40"><ChevronLeft className="mr-1 h-4 w-4" />上一章</button>
          <span className="text-xs text-gray-500">{chapterIndex + 1} / {chapters.length}</span>
          <button type="button" onClick={() => changeChapter(chapterIndex + 1)} disabled={chapterIndex === chapters.length - 1}
            className="btn-secondary px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40">下一章<ChevronRight className="ml-1 h-4 w-4" /></button>
        </footer>
      </div>
    </div>
  );
}
