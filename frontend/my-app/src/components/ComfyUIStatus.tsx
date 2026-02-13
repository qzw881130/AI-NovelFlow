import { useState, useEffect } from 'react';
import { 
  Server, 
  Cpu, 
  HardDrive, 
  ListTodo,
  AlertCircle,
  Loader2,
  Thermometer,
  MemoryStick
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface ComfyUIStats {
  status: 'online' | 'offline';
  gpuUsage: number;
  vramPercent: number;
  vramUsed: number;
  vramTotal: number;
  queueSize: number;
  deviceName: string;
  // 新增字段
  cpuUsage?: number;
  ramPercent?: number;
  ramUsed?: number;
  ramTotal?: number;
  temperature?: number;
  hddUsage?: number;
}

export default function ComfyUIStatus() {
  const [stats, setStats] = useState<ComfyUIStats>({
    status: 'offline',
    gpuUsage: 0,
    vramPercent: 0,
    vramUsed: 0,
    vramTotal: 16,
    queueSize: 0,
    deviceName: 'Unknown',
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<any>(null);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/health/comfyui`);
      
      if (res.ok) {
        const data = await res.json();
        
        if (data.status === 'ok' && data.data) {
          const systemStats = data.data;
          
          // 获取队列信息
          let queueSize = 0;
          try {
            const queueRes = await fetch(`${API_BASE}/health/comfyui-queue`);
            if (queueRes.ok) {
              const queueData = await queueRes.json();
              queueSize = queueData.queue_size || 0;
            }
          } catch (e) {
            // 忽略队列错误
          }
          
          // 计算百分比
          const vramPercent = systemStats.vram_total > 0 
            ? Math.round((systemStats.vram_used / systemStats.vram_total) * 100)
            : 0;
          
          const ramPercent = systemStats.ram_total > 0
            ? Math.round((systemStats.ram_used / systemStats.ram_total) * 100)
            : 0;
          
          setStats({
            status: 'online',
            gpuUsage: Math.round(systemStats.gpu_usage || 0),
            vramPercent: vramPercent,
            vramUsed: systemStats.vram_used || 0,
            vramTotal: systemStats.vram_total || 16,
            queueSize: queueSize,
            deviceName: systemStats.device_name || 'NVIDIA GPU',
            // 新增字段
            cpuUsage: systemStats.cpu_usage !== undefined ? Math.round(systemStats.cpu_usage) : undefined,
            ramPercent: ramPercent,
            ramUsed: systemStats.ram_used || 0,
            ramTotal: systemStats.ram_total || 0,
            temperature: systemStats.temperature !== undefined ? Math.round(systemStats.temperature) : undefined,
            hddUsage: systemStats.hdd_usage !== undefined ? Math.round(systemStats.hdd_usage) : undefined,
          });
          setDebugInfo(data.raw);
          setError(null);
        } else {
          setStats(prev => ({ ...prev, status: 'offline' }));
          setError('ComfyUI 返回异常数据');
        }
      } else {
        const errorData = await res.json().catch(() => ({}));
        setStats(prev => ({ ...prev, status: 'offline' }));
        setError(errorData.detail || '无法连接到 ComfyUI');
      }
    } catch (err: any) {
      setStats(prev => ({ ...prev, status: 'offline' }));
      setError(err.message || '网络连接失败');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    // 每0.5秒刷新一次
    const interval = setInterval(fetchStatus, 500);
    return () => clearInterval(interval);
  }, []);

  if (isLoading) {
    return (
      <div className="bg-slate-800 rounded-xl p-4 flex items-center justify-center">
        <Loader2 className="h-5 w-5 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-400">正在连接 ComfyUI...</span>
      </div>
    );
  }

  // 计算要显示的项目数量
  const hasExtraStats = stats.cpuUsage !== undefined || stats.ramPercent !== undefined || 
                        stats.temperature !== undefined || stats.hddUsage !== undefined;
  
  // 动态网格列数
  const gridCols = hasExtraStats ? 'grid-cols-8' : 'grid-cols-4';

  return (
    <div className="bg-slate-800 rounded-xl p-4 text-white">
      <div className={`grid ${gridCols} gap-3 items-center`}>
        {/* ComfyUI状态 */}
        <div className="flex items-center gap-2">
          <div className="p-2 bg-slate-700 rounded-lg">
            <Server className="h-4 w-4 text-slate-300" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-slate-400">ComfyUI状态</p>
            <div className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${stats.status === 'online' ? 'bg-emerald-400' : 'bg-red-400'}`} />
              <span className={`text-sm font-medium ${stats.status === 'online' ? 'text-emerald-400' : 'text-red-400'}`}>
                {stats.status === 'online' ? '在线' : '离线'}
              </span>
            </div>
          </div>
        </div>

        {/* GPU使用率 */}
        <div className="flex items-center gap-2 border-l border-slate-600 pl-3">
          <div className="p-2 bg-slate-700 rounded-lg">
            <Cpu className="h-4 w-4 text-slate-300" />
          </div>
          <div>
            <p className="text-xs text-slate-400">GPU使用率</p>
            <p className="text-sm font-medium">{stats.gpuUsage}%</p>
          </div>
        </div>

        {/* 显存占用 - 改为百分比 */}
        <div className="flex items-center gap-2 border-l border-slate-600 pl-3">
          <div className="p-2 bg-slate-700 rounded-lg">
            <HardDrive className="h-4 w-4 text-slate-300" />
          </div>
          <div>
            <p className="text-xs text-slate-400">显存占用</p>
            <p className="text-sm font-medium">{stats.vramPercent}%</p>
          </div>
        </div>

        {/* 队列任务 */}
        <div className="flex items-center gap-2 border-l border-slate-600 pl-3">
          <div className="p-2 bg-slate-700 rounded-lg">
            <ListTodo className="h-4 w-4 text-slate-300" />
          </div>
          <div>
            <p className="text-xs text-slate-400">队列任务</p>
            <p className="text-sm font-medium">{stats.queueSize}</p>
          </div>
        </div>

        {/* CPU使用率 - 如果有数据 */}
        {stats.cpuUsage !== undefined && (
          <div className="flex items-center gap-2 border-l border-slate-600 pl-3">
            <div className="p-2 bg-slate-700 rounded-lg">
              <Cpu className="h-4 w-4 text-blue-300" />
            </div>
            <div>
              <p className="text-xs text-slate-400">CPU</p>
              <p className="text-sm font-medium">{stats.cpuUsage}%</p>
            </div>
          </div>
        )}

        {/* RAM使用率 - 改为百分比 */}
        {stats.ramPercent !== undefined && (
          <div className="flex items-center gap-2 border-l border-slate-600 pl-3">
            <div className="p-2 bg-slate-700 rounded-lg">
              <MemoryStick className="h-4 w-4 text-green-300" />
            </div>
            <div>
              <p className="text-xs text-slate-400">RAM</p>
              <p className="text-sm font-medium">{stats.ramPercent}%</p>
            </div>
          </div>
        )}

        {/* 温度 */}
        {stats.temperature !== undefined && (
          <div className="flex items-center gap-2 border-l border-slate-600 pl-3">
            <div className="p-2 bg-slate-700 rounded-lg">
              <Thermometer className="h-4 w-4 text-orange-300" />
            </div>
            <div>
              <p className="text-xs text-slate-400">温度</p>
              <p className="text-sm font-medium">{stats.temperature}°C</p>
            </div>
          </div>
        )}

        {/* HDD使用率 */}
        {stats.hddUsage !== undefined && (
          <div className="flex items-center gap-2 border-l border-slate-600 pl-3">
            <div className="p-2 bg-slate-700 rounded-lg">
              <HardDrive className="h-4 w-4 text-purple-300" />
            </div>
            <div>
              <p className="text-xs text-slate-400">HDD</p>
              <p className="text-sm font-medium">{stats.hddUsage}%</p>
            </div>
          </div>
        )}
      </div>

      {/* 显卡信息 - 显示完整名称和显存详情 */}
      {stats.status === 'online' && stats.deviceName && (
        <div className="mt-3 pt-3 border-t border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">显卡信息</p>
              <p className="text-sm font-medium text-emerald-400">{stats.deviceName}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-slate-400">显存详情</p>
              <p className="text-sm text-slate-300">
                {stats.vramUsed.toFixed(1)} / {stats.vramTotal.toFixed(1)} GB ({stats.vramPercent}%)
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 错误信息 */}
      {error && (
        <div className="mt-3 flex items-center gap-2 text-red-400 text-sm bg-red-900/20 p-2 rounded">
          <AlertCircle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      )}

      {/* 调试信息 */}
      {debugInfo && (
        <details className="mt-2 text-xs text-slate-500">
          <summary className="cursor-pointer hover:text-slate-400">调试信息</summary>
          <pre className="mt-1 p-2 bg-slate-900 rounded overflow-auto max-h-32 text-[10px]">
            {JSON.stringify(debugInfo, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
