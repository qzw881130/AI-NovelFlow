import { useState, useEffect } from 'react';
import { Server, Loader2, Thermometer, MemoryStick } from 'lucide-react';

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
  const [stats, setStats] = useState<SystemStats>({
    status: 'offline',
    gpuUsage: 0,
    vramUsed: 0,
    vramTotal: 16,
    vramPercent: 0,
    queueSize: 0,
    temperature: undefined,
    gpuSource: 'estimated',
    ramUsed: undefined,
    ramTotal: undefined,
    ramPercent: undefined,
  });
  const [isLoading, setIsLoading] = useState(true);

  const fetchStatus = async () => {
    try {
      // 获取 ComfyUI 状态
      const res = await fetch(`${API_BASE}/health/comfyui/`);
      
      if (res.ok) {
        const data = await res.json();
        
        if (data.status === 'ok' && data.data) {
          const systemStats = data.data;
          
          // 获取队列信息
          let queueSize = 0;
          try {
            const queueRes = await fetch(`${API_BASE}/health/comfyui-queue/`);
            if (queueRes.ok) {
              const queueData = await queueRes.json();
              queueSize = queueData.queue_size || 0;
            }
          } catch (e) {
            // 忽略队列错误
          }
          
          // 计算显存百分比
          const vramPercent = systemStats.vram_total > 0 
            ? Math.round((systemStats.vram_used / systemStats.vram_total) * 100)
            : 0;
          
          setStats({
            status: 'online',
            gpuUsage: Math.round(systemStats.gpu_usage || 0),
            vramUsed: systemStats.vram_used || 0,
            vramTotal: systemStats.vram_total || 16,
            vramPercent: vramPercent,
            queueSize: queueSize,
            temperature: systemStats.temperature,
            gpuSource: systemStats.gpu_source || 'estimated',
            gpuName: systemStats.device_name,  // 显卡型号
            // RAM 信息
            ramUsed: systemStats.ram_used,
            ramTotal: systemStats.ram_total,
            ramPercent: systemStats.ram_percent,
          });
        } else {
          setStats(prev => ({ ...prev, status: 'offline' }));
        }
      } else {
        setStats(prev => ({ ...prev, status: 'offline' }));
      }
    } catch (err) {
      setStats(prev => ({ ...prev, status: 'offline' }));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    // 每秒刷新一次（WebSocket 模式下更实时）
    const interval = setInterval(fetchStatus, 1000);
    return () => clearInterval(interval);
  }, []);

  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 text-gray-400 animate-spin" />
          <span className="ml-2 text-gray-500">正在连接...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
      <h3 className="text-lg font-semibold text-gray-900 mb-5">系统状态</h3>
      
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
              {stats.status === 'online' ? '在线' : '离线'}
            </span>
          </div>
        </div>

        {/* 显卡型号 */}
        {stats.gpuName && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-gray-700 font-medium">显卡型号</span>
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
              <span className="text-gray-700 font-medium">GPU 使用率</span>
              {stats.gpuSource === 'real' && (
                <span className="text-xs px-1.5 py-0.5 bg-green-100 text-green-700 rounded">实时</span>
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
            <span className="text-gray-700 font-medium">显存占用</span>
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
                <span className="text-gray-700 font-medium">内存占用</span>
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
              <span className="text-gray-700 font-medium">GPU 温度</span>
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
          <span className="text-gray-700 font-medium">队列任务</span>
          <span className={`text-2xl font-bold ${stats.queueSize > 0 ? 'text-amber-600' : 'text-gray-900'}`}>
            {stats.queueSize}
          </span>
        </div>
      </div>
    </div>
  );
}
