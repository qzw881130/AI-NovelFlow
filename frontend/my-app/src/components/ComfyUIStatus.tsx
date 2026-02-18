import { useState, useEffect } from 'react';
import { Server, Loader2, Thermometer, MemoryStick } from 'lucide-react';
import { useTranslation } from '../stores/i18nStore';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface SystemStats {
  status: 'online' | 'offline';
  gpuUsage: number;
  vramUsed: number;
  vramTotal: number;
  vramPercent: number;
  queueSize: number;
  temperature?: number;
  gpuSource?: 'real' | 'estimated';
  gpuName?: string;  // 显卡型号
  // RAM 信息
  ramUsed?: number;
  ramTotal?: number;
  ramPercent?: number;
}

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
      const response = await fetch(`${API_BASE}/health/comfyui`);
      if (response.ok) {
        const data = await response.json();
        if (data.status === 'ok') {
          setStats({
            status: 'online',
            gpuUsage: data.data?.gpu_usage || 0,
            vramUsed: data.data?.vram_used || 0,
            vramTotal: data.data?.vram_total || 16,
            vramPercent: ((data.data?.vram_used || 0) / (data.data?.vram_total || 16)) * 100,
            queueSize: (data.data?.queue_running || 0) + (data.data?.queue_pending || 0),
            temperature: data.data?.temperature,
            gpuSource: data.data?.gpu_source,
            gpuName: data.data?.device_name,
            ramUsed: data.data?.ram_used,
            ramTotal: data.data?.ram_total,
            ramPercent: data.data?.ram_percent,
          });
        }
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
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 text-gray-400 animate-spin" />
          <span className="ml-2 text-gray-500">{t('tasks.connecting')}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
      <h3 className="text-lg font-semibold text-gray-900 mb-5">{t('tasks.systemStatusTitle')}</h3>
      
      <div className="space-y-5">
        {/* ComfyUI 状态 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gray-50 rounded-lg">
              <Server className="h-5 w-5 text-gray-600" />
            </div>
            <span className="text-gray-700 font-medium">ComfyUI</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${stats.status === 'online' ? 'bg-green-500' : 'bg-gray-300'}`} />
            <span className={`text-sm font-medium ${stats.status === 'online' ? 'text-green-600' : 'text-gray-400'}`}>
              {stats.status === 'online' ? t('tasks.online') : t('tasks.offline')}
            </span>
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
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-gray-700 font-medium">{t('tasks.gpuUsage')}</span>
              {stats.gpuSource === 'real' && (
                <span className="text-xs px-1.5 py-0.5 bg-green-100 text-green-700 rounded">{t('tasks.realtime')}</span>
              )}
            </div>
            <span className="text-gray-900 font-semibold">{stats.gpuUsage}%</span>
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
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-700 font-medium">{t('tasks.vramUsage')}</span>
            <span className="text-gray-900 font-semibold">
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
        {stats.ramUsed !== undefined && stats.ramTotal !== undefined && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <MemoryStick className="h-4 w-4 text-gray-500" />
                <span className="text-gray-700 font-medium">{t('tasks.ramUsage')}</span>
              </div>
              <span className="text-gray-900 font-semibold">
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
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
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
