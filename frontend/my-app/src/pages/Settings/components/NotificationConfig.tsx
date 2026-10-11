import { useEffect, useState } from 'react';
import { Bell, BellRing, Check, ChevronDown, Loader2, Play, Send, Volume2 } from 'lucide-react';
import { notificationApi } from '../../../api/notifications';
import type { NotificationConfig as Config, NotificationEvent } from '../../../api/notifications';
import { playNotificationSound } from '../../../services/notificationSound';
import { toast } from '../../../stores/toastStore';
import './NotificationConfig.css';

const inputClass = 'w-full min-w-0 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500';

export default function NotificationConfig() {
  const [config, setConfig] = useState<Config | null>(null);
  const [busy, setBusy] = useState('');
  const [webhook, setWebhook] = useState('');
  const [secret, setSecret] = useState('');
  const [botToken, setBotToken] = useState('');
  const [chatId, setChatId] = useState('');
  const [testEventCode, setTestEventCode] = useState('clip.generation.completed');
  const [testPayload, setTestPayload] = useState('{"shot_index":4,"clip_index":2,"status":"completed"}');
  const [testResult, setTestResult] = useState('');

  useEffect(() => {
    let alive = true;
    notificationApi.getConfig()
      .then(data => { if (alive) setConfig(data); })
      .catch(error => { if (alive) toast.error(`通知配置加载失败：${String(error)}`); });
    return () => { alive = false; };
  }, []);

  const errorMessage = (error: unknown) => error instanceof Error ? error.message : '请求失败';

  const savePageSound = async () => {
    if (!config) return;
    setBusy('sound');
    try {
      setConfig(await notificationApi.updateConfig({ pageSound: config.pageSound }));
      toast.success('页面声音配置已保存');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally { setBusy(''); }
  };

  const saveFeishu = async (test = false) => {
    if (!config) return;
    setBusy('feishu');
    try {
      const updated = await notificationApi.updateConfig({ feishu: {
        enabled: config.feishu.enabled,
        ...(webhook.trim() ? { webhook: webhook.trim() } : {}),
        ...(secret.trim() ? { secret: secret.trim() } : {}),
      } });
      setConfig(updated);
      setWebhook('');
      setSecret('');
      if (test) {
        const result = await notificationApi.testChannel('FEISHU');
        if (result.status !== 'sent') throw new Error(result.status === 'disabled' ? '请先开启飞书通道' : '飞书测试发送失败，请检查机器人配置');
        toast.success('飞书测试消息已发送');
      } else toast.success('飞书配置已保存');
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setBusy(''); }
  };

  const saveTelegram = async (test = false) => {
    if (!config) return;
    setBusy('telegram');
    try {
      const updated = await notificationApi.updateConfig({ telegram: {
        enabled: config.telegram.enabled,
        ...(botToken.trim() ? { botToken: botToken.trim() } : {}),
        ...(chatId.trim() ? { chatId: chatId.trim() } : {}),
      } });
      setConfig(updated);
      setBotToken('');
      setChatId('');
      if (test) {
        const result = await notificationApi.testChannel('TELEGRAM');
        if (result.status !== 'sent') throw new Error(result.status === 'disabled' ? '请先开启 Telegram 通道' : 'Telegram 测试发送失败，请检查 Bot 配置');
        toast.success('Telegram 测试消息已发送');
      } else toast.success('Telegram 配置已保存');
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setBusy(''); }
  };

  const toggleEvent = async (event: NotificationEvent) => {
    if (!config) return;
    setBusy('events');
    setConfig({
      ...config,
      events: config.events.map(item => item.event_code === event.event_code ? { ...item, enabled: !item.enabled } : item),
    });
    try {
      setConfig(await notificationApi.updateConfig({ eventSwitches: { [event.event_code]: !event.enabled } }));
    } catch (error) {
      setConfig(config);
      toast.error(errorMessage(error));
    }
    finally { setBusy(''); }
  };

  const simulateEvent = async () => {
    setBusy('simulation');
    try {
      const parsed: unknown = JSON.parse(testPayload);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Payload 必须是 JSON 对象');
      const result = await notificationApi.testEvent(testEventCode, parsed as Record<string, unknown>);
      const channelText = Object.entries(result.channels).map(([channel, status]) => `${channel}: ${status}`).join(' · ');
      setTestResult(`${result.status}${channelText ? ` · ${channelText}` : ''}`);
      if (result.status === 'failed') toast.error('模拟事件发送失败');
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setBusy(''); }
  };

  if (!config) return <div className="flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" />正在加载通知配置…</div>;
  const groups = Array.from(new Set(config.events.map(event => event.category)));
  const disabled = Boolean(busy);

  return <div className="notification-config-container min-w-0 space-y-4">
    <div className="rounded-lg bg-blue-50 px-4 py-2.5 text-sm text-blue-800">
      三个通道独立工作。事件开关仅控制通知，不改变生成任务状态。
    </div>

    <div className="notification-channel-grid grid min-w-0 gap-4">
      <section className="notification-sound-card flex min-w-0 flex-col rounded-xl border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2"><Volume2 className="h-5 w-5 text-blue-600" /><h3 className="font-semibold text-gray-900">页面声音提醒</h3></div>
          <label className="flex shrink-0 items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={config.pageSound.enabled} onChange={e => setConfig({ ...config, pageSound: { ...config.pageSound, enabled: e.target.checked } })} />开启</label>
        </div>
        <div className="mt-3 flex min-w-0 flex-1 flex-col">
          <div className="notification-sound-fields grid min-w-0 items-end gap-3">
            <label className="min-w-0 text-sm text-gray-700">提示音
              <select className={`${inputClass} mt-1`} value={config.pageSound.soundId} onChange={e => setConfig({ ...config, pageSound: { ...config.pageSound, soundId: e.target.value } })}>
                {config.sounds.map(sound => <option value={sound.id} key={sound.id}>{sound.name}</option>)}
              </select>
            </label>
            <label className="min-w-0 text-sm text-gray-700">音量：{Math.round(config.pageSound.volume * 100)}%
              <div className="flex h-[38px] items-center"><input aria-label="页面声音音量" className="w-full accent-blue-600" type="range" min="0" max="1" step="0.05" value={config.pageSound.volume} onChange={e => setConfig({ ...config, pageSound: { ...config.pageSound, volume: Number(e.target.value) } })} /></div>
            </label>
          </div>
          <div className="mt-auto flex flex-wrap justify-end gap-2 pt-3">
            <button type="button" className="btn-secondary gap-2 whitespace-nowrap" onClick={() => void playNotificationSound(config.pageSound.soundId, config.pageSound.volume).catch(() => toast.error('浏览器阻止播放，请点击页面后重试'))}><Play className="h-4 w-4" />试听</button>
            <button type="button" disabled={disabled} className="btn-primary gap-2 whitespace-nowrap" onClick={() => void savePageSound()}><Check className="h-4 w-4" />保存</button>
          </div>
        </div>
      </section>

        <section className="flex min-w-0 flex-col rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between gap-4"><div className="flex items-center gap-2"><BellRing className="h-5 w-5 text-blue-600" /><h3 className="font-semibold text-gray-900">飞书通知</h3></div>
            <label className="flex shrink-0 items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={config.feishu.enabled} onChange={e => setConfig({ ...config, feishu: { ...config.feishu, enabled: e.target.checked } })} />开启</label></div>
          <div className="mt-3 space-y-3">
            <label className="block min-w-0 text-sm text-gray-700">自定义机器人 Webhook
              <input className={`${inputClass} mt-1`} type="url" autoComplete="off" value={webhook} onChange={e => setWebhook(e.target.value)} placeholder={config.feishu.webhookMasked || 'https://open.feishu.cn/open-apis/bot/v2/hook/...'} />
              {config.feishu.webhookMasked && <span className="block break-all text-xs text-gray-500">已保存：{config.feishu.webhookMasked}；留空表示保持原值</span>}
            </label>
            <label className="block min-w-0 text-sm text-gray-700">签名密钥（可选）
              <input className={`${inputClass} mt-1`} type="password" autoComplete="new-password" value={secret} onChange={e => setSecret(e.target.value)} placeholder={config.feishu.secretMasked || '未配置'} />
              {config.feishu.secretMasked && <span className="block break-all text-xs text-gray-500">已保存：{config.feishu.secretMasked}；留空表示保持原值</span>}
            </label>
          </div>
          <div className="mt-auto flex flex-wrap justify-end gap-2 pt-3"><button type="button" disabled={disabled} className="btn-secondary gap-2" onClick={() => void saveFeishu(true)}><Send className="h-4 w-4" />保存并发送测试</button><button type="button" disabled={disabled} className="btn-primary gap-2" onClick={() => void saveFeishu()}><Check className="h-4 w-4" />保存</button></div>
        </section>

        <section className="flex min-w-0 flex-col rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between gap-4"><div className="flex items-center gap-2"><Send className="h-5 w-5 text-blue-600" /><h3 className="font-semibold text-gray-900">Telegram 通知</h3></div>
            <label className="flex shrink-0 items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={config.telegram.enabled} onChange={e => setConfig({ ...config, telegram: { ...config.telegram, enabled: e.target.checked } })} />开启</label></div>
          <div className="mt-3 space-y-3">
            <label className="block min-w-0 text-sm text-gray-700">Bot Token
              <input className={`${inputClass} mt-1`} type="password" autoComplete="new-password" value={botToken} onChange={e => setBotToken(e.target.value)} placeholder={config.telegram.botTokenMasked || 'Bot Token'} />
              {config.telegram.botTokenMasked && <span className="block break-all text-xs text-gray-500">已保存：{config.telegram.botTokenMasked}；留空保持原值</span>}
            </label>
            <label className="block min-w-0 text-sm text-gray-700">Chat ID
              <input className={`${inputClass} mt-1`} type="text" autoComplete="off" value={chatId} onChange={e => setChatId(e.target.value)} placeholder={config.telegram.chatIdMasked || 'Chat ID'} />
              {config.telegram.chatIdMasked && <span className="block break-all text-xs text-gray-500">已保存：{config.telegram.chatIdMasked}；留空保持原值</span>}
            </label>
          </div>
          <div className="mt-auto flex flex-wrap justify-end gap-2 pt-3"><button type="button" disabled={disabled} className="btn-secondary gap-2" onClick={() => void saveTelegram(true)}><Send className="h-4 w-4" />保存并发送测试</button><button type="button" disabled={disabled} className="btn-primary gap-2" onClick={() => void saveTelegram()}><Check className="h-4 w-4" />保存</button></div>
        </section>
    </div>

    <section className="notification-event-container rounded-xl border border-gray-200 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="flex items-center gap-2"><Bell className="h-5 w-5 text-blue-600" /><h3 className="font-semibold text-gray-900">事件通知配置</h3></div>
        <p className="text-xs text-gray-500">按事件设置订阅；新增成功事件默认关闭，每项修改后立即保存</p>
      </div>
      <div className="notification-category-grid mt-4 grid min-w-0 gap-3">
        {groups.map(category => <div key={category} className="notification-category-card min-w-0 rounded-lg border border-gray-200 bg-white p-3">
          <h4 className="mb-2 border-b border-gray-100 pb-1.5 text-sm font-semibold text-gray-700">{category}</h4>
          <div className="notification-event-grid grid min-w-0 gap-2">
            {config.events.filter(event => event.category === category).map(event => <label key={event.event_code} title={event.description} className="flex min-w-0 cursor-pointer items-start gap-2.5 rounded-lg border border-gray-200 bg-gray-50/60 px-3 py-2 hover:border-blue-200 hover:bg-blue-50/40">
              <input type="checkbox" className="mt-0.5 shrink-0 accent-blue-600" aria-label={`启用 ${event.name}`} checked={event.enabled} disabled={disabled} onChange={() => void toggleEvent(event)} />
              <span className="min-w-0"><span className="block text-sm font-medium leading-5 text-gray-800">{event.name}</span><span className="block break-all text-xs leading-4 text-gray-500">{event.event_code}</span></span>
            </label>)}
          </div>
        </div>)}
      </div>
    </section>

    <details className="group rounded-xl border border-dashed border-gray-300">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 marker:hidden [&::-webkit-details-marker]:hidden">
        <span className="font-semibold text-gray-900">开发测试 · 模拟通知事件</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-gray-500 transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-3 border-t border-gray-100 px-4 pb-4 pt-3">
        <p className="text-sm text-gray-500">仅开发环境中通过 NovelFlow 页面可用，支持已开放访问的局域网设备。消息会标注“开发模拟事件”，不会修改真实 Shot、Clip 或任务状态。</p>
        <select aria-label="模拟事件" className={inputClass} value={testEventCode} onChange={e => setTestEventCode(e.target.value)}>{config.events.map(event => <option key={event.event_code} value={event.event_code}>{event.name} · {event.event_code}</option>)}</select>
        <label className="block text-sm text-gray-700">Payload（JSON 对象）<textarea className={`${inputClass} mt-1 font-mono`} rows={3} value={testPayload} onChange={e => setTestPayload(e.target.value)} /></label>
        <div className="flex flex-wrap items-center justify-between gap-3"><span className="min-w-0 break-all text-xs text-gray-500" role="status">{testResult}</span><button type="button" disabled={disabled} className="btn-secondary gap-2" onClick={() => void simulateEvent()}><Send className="h-4 w-4" />发送模拟事件</button></div>
      </div>
    </details>
  </div>;
}
