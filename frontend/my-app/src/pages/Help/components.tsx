import { useState, type ReactNode } from 'react';
import { Check, Copy, Info, ShieldAlert } from 'lucide-react';

export const recommendedEvents = [
  'H3 提示词优化失败',
  'Preflight 修复失败',
  'Clip 生成完成',
  'Clip 生成失败',
  'Shot 合并完成',
  'Shot 合并失败',
  'Clip 结果恢复完成',
];

export function CodeBlock({ label, value }: { label: string; value: string }) {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle');

  const copy = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = value;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        try {
          textarea.focus();
          textarea.select();
          if (!document.execCommand('copy')) throw new Error('复制失败');
        } finally {
          textarea.remove();
        }
      }
      setCopyStatus('copied');
    } catch {
      setCopyStatus('failed');
    }
  };

  return <div className="min-w-0 overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
    <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-3 py-2">
      <span className="text-xs font-medium text-gray-600">{label}</span>
      <button type="button" onClick={() => void copy()} className="inline-flex shrink-0 items-center gap-1 rounded px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500" aria-label={`复制${label}`}>
        {copyStatus === 'copied' ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        {copyStatus === 'copied' ? '已复制' : copyStatus === 'failed' ? '复制失败，请手动复制' : '复制'}
      </button>
    </div>
    <pre className="overflow-x-auto whitespace-pre-wrap break-all px-3 py-3 text-sm leading-6 text-gray-800"><code>{value}</code></pre>
  </div>;
}

export function StepCard({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby={`step-${number}`}>
    <div className="mb-4 flex items-center gap-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">{number}</span>
      <h2 id={`step-${number}`} className="text-lg font-semibold text-gray-900">步骤 {number}：{title}</h2>
    </div>
    <div className="space-y-4 pl-0 text-sm leading-7 text-gray-700 sm:pl-11">{children}</div>
  </section>;
}

export function Note({ children, warning = false }: { children: ReactNode; warning?: boolean }) {
  return <div className={`flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm leading-6 ${warning ? 'bg-amber-50 text-amber-900' : 'bg-blue-50 text-blue-900'}`}>
    {warning ? <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" />}
    <span>{children}</span>
  </div>;
}
