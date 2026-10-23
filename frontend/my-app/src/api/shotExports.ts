interface ExportJob {
  task_id: string; status: string; progress: number; current_step?: string;
  error_message?: string; download_url?: string;
}
class ExportRequestError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function requestJob(url: string, method = 'GET'): Promise<ExportJob> {
  const response = await fetch(url, { method, signal: AbortSignal.timeout(20_000) });
  const result = await response.json();
  if (!response.ok || !result.success) throw new ExportRequestError(result.detail || result.message || '导出请求失败', response.status);
  return result.data;
}

export async function downloadQueuedShotExport(base: string, params: URLSearchParams, onProgress?: (message: string) => void): Promise<void> {
  const key = `shotExport:${base}:${params.toString()}`;
  let saved: string | null = null;
  const remember = (id?: string) => {
    try { if (id) localStorage.setItem(key, id); else localStorage.removeItem(key); } catch { /* Storage is optional. */ }
  };
  try { saved = localStorage.getItem(key); } catch { /* Storage is optional. */ }
  let job: ExportJob | undefined;
  if (saved) {
    try { job = await requestJob(`${base}/exports/${encodeURIComponent(saved)}`); }
    catch (error) {
      if (!(error instanceof ExportRequestError) || ![404, 410].includes(error.status)) throw error;
      remember();
    }
    if (job?.status === 'failed' || job?.status === 'cancelled') {
      remember();
      job = undefined;
    }
  }
  if (!job) {
    onProgress?.('正在提交后台打包任务');
    job = await requestJob(`${base}/export-video-materials?${params}`, 'POST');
  }
  remember(job.task_id);
  let failures = 0;
  while (job.status === 'pending' || job.status === 'running') {
    onProgress?.(`${job.current_step || '后台打包中'} · ${job.progress || 0}%`);
    await new Promise(resolve => window.setTimeout(resolve, 1500));
    try {
      job = await requestJob(`${base}/exports/${encodeURIComponent(job.task_id)}`);
      failures = 0;
    } catch {
      onProgress?.('连接暂时中断，后台仍在打包，正在重连…');
      if (++failures >= 5) throw new Error('进度查询暂时不可用，后台任务会继续。可在任务队列查看结果，或再次点击导出继续查询。');
    }
  }
  if (job.status !== 'completed') {
    remember();
    throw new Error(job.error_message || '导出任务已停止，请重试');
  }
  onProgress?.('打包完成，开始下载');
  // Let the browser stream the finished ZIP to disk. No Blob buffering or
  // request timeout covers the entire build/download duration.
  const link = document.createElement('a');
  link.href = `${base}/exports/${encodeURIComponent(job.task_id)}/download`;
  link.download = '';
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  remember();
}
