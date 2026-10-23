import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, RefreshCw, X } from 'lucide-react';
import type { CoverTextStyle, NovelVideoMergeHistory } from '../../../api/novels';
import { youtubeApi, type YoutubePlaylist, type YoutubeSettings } from '../../../api/youtube';
import { toast } from '../../../stores/toastStore';

const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败';
const requireData = <T,>(response: { success: boolean; data?: T; message?: string; detail?: string }, fallback: string): T => {
  if (!response.success || !response.data) throw new Error(response.detail || response.message || fallback);
  return response.data;
};
const PLAYLIST_STORAGE_KEY = 'novelflow-youtube-last-playlist-id';
const coverStyleNames: Record<CoverTextStyle, string> = {
  classic: '经典居中', cinematic: '文学电影', editorial: '左下纪实', vintage: '朱砂旧书',
};
const lastPlaylistId = () => {
  try { return window.localStorage.getItem(PLAYLIST_STORAGE_KEY) || ''; }
  catch { return ''; }
};

export function YoutubeUploadModal({ novelId, novelTitle, item, onClose, onUploaded }: {
  novelId: string; novelTitle: string; item: NovelVideoMergeHistory;
  onClose: () => void; onUploaded: () => void;
}) {
  const covers = (item.covers?.length ? item.covers : item.cover ? [item.cover] : [])
    .filter(value => value.aspectRatio === '16:9' && value.status === 'completed' && value.imageUrl);
  const [selectedCoverId, setSelectedCoverId] = useState(covers[0]?.id || '');
  const cover = covers.find(value => value.id === selectedCoverId) || covers[0];
  const [settings, setSettings] = useState<YoutubeSettings | null>(null);
  const [tab, setTab] = useState<'upload' | 'settings'>('upload');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [redirectUri, setRedirectUri] = useState('');
  const [defaultTags, setDefaultTags] = useState('');
  const [title, setTitle] = useState(novelTitle.slice(0, 100));
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [privacyStatus, setPrivacyStatus] = useState<'private' | 'unlisted' | 'public'>('private');
  const [playlistId, setPlaylistId] = useState(lastPlaylistId);
  const [playlists, setPlaylists] = useState<YoutubePlaylist[]>([]);
  const [busy, setBusy] = useState(false);
  const [playlistsBusy, setPlaylistsBusy] = useState(false);
  const authOriginRef = useRef(youtubeApi.callbackOrigin());

  const applySettings = (value: YoutubeSettings) => {
    setSettings(value);
    setClientId(value.clientId);
    setClientSecret('');
    setRedirectUri(value.redirectUri);
    try { authOriginRef.current = new URL(value.redirectUri).origin; } catch { /* Keep API origin. */ }
    setDefaultTags(value.defaultTags);
    setTags(previous => previous || value.defaultTags);
    if (!value.connected) {
      setTab('settings');
      setPlaylists([]);
    }
  };

  const loadSettings = async () => {
    const response = await youtubeApi.settings();
    const value = requireData(response, '读取 YouTube 配置失败');
    applySettings(value);
    if (value.connected) await loadPlaylists();
  };

  const loadPlaylists = async () => {
    setPlaylistsBusy(true);
    try {
      const available = requireData(await youtubeApi.playlists(), '读取播放列表失败');
      setPlaylists(available);
      setPlaylistId(previous => !previous || available.some(list => list.id === previous) ? previous : '');
      const stored = lastPlaylistId();
      if (stored && !available.some(list => list.id === stored)) {
        try { window.localStorage.removeItem(PLAYLIST_STORAGE_KEY); } catch { /* Storage may be disabled. */ }
      }
    } catch (error) {
      toast.error(errorText(error));
    } finally { setPlaylistsBusy(false); }
  };

  const selectPlaylist = (id: string) => {
    setPlaylistId(id);
    try { window.localStorage.setItem(PLAYLIST_STORAGE_KEY, id); } catch { /* Storage may be disabled. */ }
  };

  useEffect(() => {
    void loadSettings().catch(error => toast.error(errorText(error)));
    const onMessage = (event: MessageEvent) => {
      if (event.origin === authOriginRef.current && event.data === 'novelflow-youtube-oauth') {
        void loadSettings().catch(error => toast.error(errorText(error)));
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const saveSettings = async () => {
    setBusy(true);
    try {
      const result = await youtubeApi.saveSettings({ clientId, clientSecret, redirectUri, defaultTags });
      applySettings(requireData(result, '保存配置失败'));
      toast.success('YouTube 配置已保存');
    } catch (error) { toast.error(errorText(error)); }
    finally { setBusy(false); }
  };

  const uploadFile = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    try {
      applySettings(requireData(await youtubeApi.uploadClientFile(file), '上传 OAuth 文件失败'));
      toast.success('OAuth 客户端文件已读取');
    } catch (error) { toast.error(errorText(error)); }
    finally { setBusy(false); }
  };

  const authorize = async () => {
    const popup = window.open('', '_blank', 'width=650,height=750');
    if (!popup) { toast.error('浏览器阻止了授权窗口'); return; }
    setBusy(true);
    try {
      const { url } = requireData(await youtubeApi.authUrl(), '生成授权链接失败');
      popup.location.href = url;
    } catch (error) { popup.close(); toast.error(errorText(error)); }
    finally { setBusy(false); }
  };

  const submit = async () => {
    if (!cover) { toast.error('请先生成此视频的 16:9 封面'); return; }
    if (!title.trim()) { toast.error('请填写视频标题'); return; }
    setBusy(true);
    try {
      requireData(await youtubeApi.upload(novelId, item.id, {
        title: title.trim(), description: description.trim(), tags: tags.trim(),
        privacyStatus, playlistId, coverId: cover.id,
      }), '提交 YouTube 上传失败');
      toast.success('视频已加入 YouTube 上传队列');
      onUploaded();
      onClose();
    } catch (error) { toast.error(errorText(error)); }
    finally { setBusy(false); }
  };

  return createPortal(
    <div className="fixed inset-0 z-[340] flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="上传到 YouTube" onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h2 className="text-lg font-semibold">上传到 YouTube</h2>
          <button type="button" onClick={onClose} aria-label="关闭" className="rounded p-1 hover:bg-gray-100"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex gap-4 border-b px-5 text-sm">
          <button type="button" onClick={() => setTab('upload')} className={`py-3 ${tab === 'upload' ? 'border-b-2 border-blue-600 font-medium text-blue-700' : 'text-gray-600'}`}>上传视频</button>
          <button type="button" onClick={() => setTab('settings')} className={`py-3 ${tab === 'settings' ? 'border-b-2 border-blue-600 font-medium text-blue-700' : 'text-gray-600'}`}>YouTube 配置</button>
        </div>
        <div className="space-y-4 overflow-y-auto p-5 text-sm">
          {tab === 'settings' ? <>
            <p className="rounded bg-blue-50 p-3 text-blue-800">在 Google Cloud 启用 YouTube Data API v3，配置 OAuth 同意屏幕，并创建“Web 应用”OAuth 客户端。将下方 Redirect URI 加入已获授权的重定向 URI，然后上传客户端 JSON 或填写凭据。</p>
            <label className="block">OAuth client_secret.json <input type="file" accept="application/json,.json" onChange={event => { void uploadFile(event.target.files?.[0]); event.target.value = ''; }} className="mt-1 block w-full rounded border p-2" /></label>
            <label className="block">Client ID <input value={clientId} onChange={event => setClientId(event.target.value)} className="mt-1 w-full rounded border p-2" /></label>
            <label className="block">Client secret {settings?.hasClientSecret && <span className="text-gray-500">（已保存，留空则保留）</span>}<input type="password" value={clientSecret} onChange={event => setClientSecret(event.target.value)} className="mt-1 w-full rounded border p-2" /></label>
            <label className="block">Redirect URI <input value={redirectUri} onChange={event => setRedirectUri(event.target.value)} className="mt-1 w-full rounded border p-2" /></label>
            <p className="text-xs text-gray-500">局域网 HTTP 地址可能无法用于 Google Web OAuth；请使用浏览器可访问的 localhost 回调地址，或为服务配置 HTTPS 域名。</p>
            <label className="block">默认标签（用逗号分隔）<input value={defaultTags} onChange={event => setDefaultTags(event.target.value)} className="mt-1 w-full rounded border p-2" /></label>
            <p className="text-xs text-gray-500">YouTube 网络代理请在 <a href="/settings#proxy" className="text-blue-700 underline">系统配置 → 代理设置</a> 中管理。</p>
            <div className="flex items-center gap-2">
              <button type="button" disabled={busy} onClick={() => void saveSettings()} className="btn-primary px-4 py-2">保存配置</button>
              <button type="button" disabled={busy || !settings?.hasClientSecret} onClick={() => void authorize()} className="btn-secondary px-4 py-2">授权 YouTube</button>
              <a href="https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas" target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">查看额度</a>
              <span className={settings?.connected ? 'text-green-700' : 'text-gray-500'}>{settings?.connected ? '已连接' : '未连接'}</span>
            </div>
          </> : <>
            <p className="text-gray-500">{novelTitle} · 合并 {item.chapters.length} 个章回</p>
            <label className="block">视频标题 <input value={title} maxLength={100} onChange={event => setTitle(event.target.value)} className="mt-1 w-full rounded border p-2" /></label>
            <label className="block">视频简介 <textarea value={description} maxLength={5000} rows={3} onChange={event => setDescription(event.target.value)} className="mt-1 w-full rounded border p-2" /></label>
            <label className="block">标签（用逗号分隔）<input value={tags} onChange={event => setTags(event.target.value)} className="mt-1 w-full rounded border p-2" /></label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">保存或发布<select value={privacyStatus} onChange={event => setPrivacyStatus(event.target.value as typeof privacyStatus)} className="mt-1 w-full rounded border p-2"><option value="private">私人</option><option value="unlisted">不公开列出</option><option value="public">公开</option></select></label>
              <label className="block">播放列表 <button type="button" onClick={() => void loadPlaylists()} disabled={playlistsBusy || !settings?.connected} title="刷新播放列表" className="ml-2 align-middle text-blue-600"><RefreshCw className={`h-4 w-4 ${playlistsBusy ? 'animate-spin' : ''}`} /></button><select value={playlistId} onChange={event => selectPlaylist(event.target.value)} className="mt-1 w-full rounded border p-2"><option value="">不加入播放列表</option>{playlists.map(list => <option key={list.id} value={list.id}>{list.title}</option>)}</select></label>
            </div>
            <div className="rounded-lg border p-3">
              <div className="font-medium">视频封面 · 16:9</div>
              {covers.length > 1 && <div className="mt-2 grid grid-cols-2 gap-2">
                {covers.map(option => <button key={option.id} type="button" onClick={() => setSelectedCoverId(option.id)} aria-pressed={cover?.id === option.id}
                  className={`rounded border p-1.5 text-left ${cover?.id === option.id ? 'border-blue-600 bg-blue-50 ring-1 ring-blue-600' : 'border-gray-200 hover:border-blue-300'}`}>
                  <img src={option.imageUrl || ''} alt="" className="aspect-video w-full rounded object-cover" />
                  <span className="mt-1 block truncate text-xs">{coverStyleNames[option.textStyle || 'classic']}{option.createdAt ? ` · ${new Date(option.createdAt).toLocaleString('zh-CN')}` : ''}</span>
                </button>)}
              </div>}
              {cover?.imageUrl ? <div className="mt-2 aspect-video w-full overflow-hidden rounded bg-gray-900"><img src={cover.imageUrl} alt="选中的 16:9 视频封面预览" className="h-full w-full object-cover" /></div> : <p className="mt-2 text-amber-700">请先在“播放 / 封面”中生成 16:9 封面。</p>}
              <p className="mt-2 text-xs text-gray-500">视频包含 AI 生成内容；上传时会向 YouTube 标记合成媒体。此合并视频暂无独立 SRT 字幕。</p>
            </div>
            <button type="button" disabled={busy || !settings?.connected || !cover} onClick={() => void submit()} className="btn-primary inline-flex items-center px-4 py-2">{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}上传</button>
          </>}
        </div>
      </div>
    </div>, document.body
  );
}
