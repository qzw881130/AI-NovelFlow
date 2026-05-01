import { useState, useEffect } from 'react';
import { Server, Loader2, Thermometer, MemoryStick } from 'lucide-react';
import { useTranslation } from '../stores/i18nStore';
import { healthApi, type SystemStats } from '../api/health';

const asNumber = (value: unknown, fallback = 0) =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const asOptionalNumber = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

export default function ComfyUIStatus() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<SystemStats>({
    status: 'offline',
    gpuUsage: 0,
    vramUsed: 0,
    vramTotal: 16,
    vramPercent: 0,
    queueSize: 0,
    temperature: undefined,
    gpuName: undefined,
    ramUsed: undefined,
    ramTotal: undefined,
    ramPercent: undefined,
  });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchStats = async () => {
    try {
      const data = await healthApi.getSystemStatus();
      if (data.status === 'ok') {
        const vramUsed = asNumber(data.data?.vram_used);
        const vramTotal = asNumber(data.data?.vram_total, 16);

        setStats({
          status: 'online',
          gpuUsage: asNumber(data.data?.gpu_usage),
          vramUsed,
          vramTotal,
          vramPercent: vramTotal > 0 ? (vramUsed / vramTotal) * 100 : 0,
          queueSize: asNumber(data.data?.queue_running) + asNumber(data.data?.queue_pending),
          temperature: asOptionalNumber(data.data?.temperature),
          gpuSource: data.data?.gpu_source,
          gpuName: data.data?.device_name,
          ramUsed: asOptionalNumber(data.data?.ram_used),
          ramTotal: asOptionalNumber(data.data?.ram_total),
          ramPercent: asOptionalNumber(data.data?.ram_percent),
        });
      }
    } catch (error) {
      console.error('Failed to fetch GPU stats:', error);
      setStats(prev => ({ ...prev, status: 'offline' }));
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 text-gray-400 animate-spin" />
          <span className="ml-2 text-gray-500">{t('tasks.connecting')}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
      <h3 className="text-lg font-semibold text-gray-900 mb-5">{t('tasks.systemStatusTitle')}</h3>
      
      <div className="space-y-5">
        {/* ComfyUI 状态 */}
        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-3 min-w-0">
              <div className="p-2 bg-gray-50 rounded-lg flex-shrink-0">
                <Server className="h-5 w-5 text-gray-600" />
              </div>
              <div className="min-w-0">
                <div className="text-gray-700 font-medium leading-6">ComfyUI</div>
              </div>
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0 self-start pl-1">
              <span className={`w-2.5 h-2.5 rounded-full ${stats.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
              <span className={`text-sm font-medium whitespace-nowrap ${stats.status === 'online' ? 'text-green-600' : 'text-gray-400'}`}>
                {stats.status === 'online' ? t('tasks.online') : t('tasks.offline')}
              </span>
            </div>
          </div>
        </div>

        {/* 显卡型号 */}
        {stats.gpuName && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-gray-700 font-medium">{t('tasks.gpuModel')}</span>
            </div>
            <span className="text-gray-900 font-semibold text-sm break-all" title={stats.gpuName}>
              {stats.gpuName}
            </span>
          </div>
        )}

        {/* GPU 使用率 */}
          <div>
            <div className="flex flex-col gap-1 mb-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-gray-700 font-medium">{t('tasks.gpuUsage')}</span>
                {stats.gpuSource === 'real' && (
                  <span className="text-xs px-1.5 py-0.5 bg-green-100 text-green-700 rounded">{t('tasks.realtime')}</span>
                )}
              </div>
              <span className="text-gray-900 font-semibold sm:text-right">{stats.gpuUsage}%</span>
            </div>
          <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
            <div 
              className={`h-full rounded-full transition-all duration-500 ${
                stats.gpuUsage > 80 ? 'bg-red-500' : 
                stats.gpuUsage > 50 ? 'bg-amber-500' : 'bg-green-500'
              }`}
              style={{ width: `${stats.gpuUsage}%` }}
            />
          </div>
        </div>

        {/* 显存占用 */}
          <div>
            <div className="flex flex-col gap-1 mb-2 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-gray-700 font-medium">{t('tasks.vramUsage')}</span>
              <span className="text-gray-900 font-semibold break-words sm:text-right">
                {stats.vramUsed.toFixed(1)} / {stats.vramTotal.toFixed(0)} GB
              </span>
            </div>
          <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
            <div 
              className={`h-full rounded-full transition-all duration-500 ${
                stats.vramPercent > 80 ? 'bg-red-500' : 
                stats.vramPercent > 50 ? 'bg-amber-500' : 'bg-blue-500'
              }`}
              style={{ width: `${stats.vramPercent}%` }}
            />
          </div>
        </div>

        {/* 内存占用 */}
        {stats.ramUsed != null && stats.ramTotal != null && (
          <div>
            <div className="flex flex-col gap-1 mb-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <MemoryStick className="h-4 w-4 text-gray-500" />
                <span className="text-gray-700 font-medium">{t('tasks.ramUsage')}</span>
              </div>
              <span className="text-gray-900 font-semibold break-words sm:text-right">
                {stats.ramUsed.toFixed(1)} / {stats.ramTotal.toFixed(0)} GB
              </span>
            </div>
            <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all duration-500 ${
                  (stats.ramPercent || 0) > 80 ? 'bg-red-500' : 
                  (stats.ramPercent || 0) > 60 ? 'bg-amber-500' : 'bg-green-500'
                }`}
                style={{ width: `${stats.ramPercent || 0}%` }}
              />
            </div>
          </div>
        )}

        {/* GPU 温度 */}
        {stats.temperature !== undefined && stats.temperature > 0 && (
          <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <Thermometer className="h-4 w-4 text-gray-500" />
              <span className="text-gray-700 font-medium">{t('tasks.gpuTemperature')}</span>
            </div>
            <span className={`font-semibold ${
              stats.temperature > 80 ? 'text-red-600' :
              stats.temperature > 70 ? 'text-amber-600' : 'text-green-600'
            }`}>
              {stats.temperature}°C
            </span>
          </div>
        )}

        {/* 队列任务 */}
        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-gray-700 font-medium">{t('tasks.queueTasks')}</span>
          <span className={`text-2xl font-bold ${stats.queueSize > 0 ? 'text-amber-600' : 'text-gray-900'}`}>
            {stats.queueSize}
          </span>
        </div>
      </div>
    </div>
  );
}
