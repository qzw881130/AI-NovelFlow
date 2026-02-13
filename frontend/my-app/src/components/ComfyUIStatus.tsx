import { useState, useEffect } from 'react';
import { 
  Server, 
  Cpu, 
  HardDrive, 
  ListTodo,
  AlertCircle,
  Loader2,
  Activity
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface ComfyUIStats {
  status: 'online' | 'offline';
  gpuUsage: number;
  vramUsed: number;
  vramTotal: number;
  queueSize: number;
  deviceName?: string;
  raw?: any;  // 调试信息
}

export default function ComfyUIStatus() {
  const [stats, setStats] = useState<ComfyUIStats>({
    status: 'offline',
    gpuUsage: 0,
    vramUsed: 0,
    vramTotal: 16,
    queueSize: 0,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<any>(null);

  const fetchStatus = async () => {
    try {
      // 获取系统状态
      const res = await fetch(`${API_BASE}/health/comfyui`);
      
      if (res.ok) {
        const data = await res.json();
        console.log('[ComfyUI Status] API Response:', data);
        
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
            console.log('[ComfyUI Status] Queue fetch failed:', e);
          }
          
          setStats({
            status: 'online',
            gpuUsage: systemStats.gpu_usage || 0,
            vramUsed: systemStats.vram_used || 0,
            vramTotal: systemStats.vram_total || 16,
            queueSize: queueSize,
            deviceName: systemStats.device_name || 'NVIDIA GPU',
            raw: data.raw,  // 保存原始数据用于调试
          });
          setDebugInfo(data.raw);
          setError(null);
        } else {
          setStats(prev => ({ ...prev, status: 'offline' }));
          setError('ComfyUI 返回异常数据');
        }
      } else {
        const errorData = await res.json().catch(() => ({}));
        console.error('[ComfyUI Status] API Error:', errorData);
        setStats(prev => ({ ...prev, status: 'offline' }));
        setError(errorData.detail || '无法连接到 ComfyUI');
      }
    } catch (err: any) {
      console.error('[ComfyUI Status] Fetch Error:', err);
      setStats(prev => ({ ...prev, status: 'offline' }));
      setError(err.message || '网络连接失败');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    // 每5秒刷新一次
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const formatVRAM = (gb: number) => `${gb.toFixed(1)} GB`;

  if (isLoading) {
    return (
      <div className="bg-slate-800 rounded-xl p-4 flex items-center justify-center">
        <Loader2 className="h-5 w-5 text-slate-400 animate-spin" />
        <span className="ml-2 text-slate-400">正在连接 ComfyUI...</span>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl p-4 text-white">
      <div className="grid grid-cols-4 gap-4 items-center">
        {/* ComfyUI状态 */}
        <div className="flex items-center gap-3">
          <div className="p-2 bg-slate-700 rounded-lg">
            <Server className="h-5 w-5 text-slate-300" />
          </div>
          <div>
            <p className="text-xs text-slate-400">ComfyUI状态</p>
            <div className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${stats.status === 'online' ? 'bg-emerald-400' : 'bg-red-400'}`} />
              <span className={`font-medium ${stats.status === 'online' ? 'text-emerald-400' : 'text-red-400'}`}>
                {stats.status === 'online' ? '在线' : '离线'}
              </span>
            </div>
            {stats.deviceName && stats.status === 'online' && (
              <p className="text-xs text-slate-500 mt-0.5 truncate max-w-[120px]">{stats.deviceName}</p>
            )}
          </div>
        </div>

        {/* GPU使用率 */}
        <div className="flex items-center gap-3 border-l border-slate-600 pl-4">
          <div className="p-2 bg-slate-700 rounded-lg">
            <Cpu className="h-5 w-5 text-slate-300" />
          </div>
          <div>
            <p className="text-xs text-slate-400">GPU使用率</p>
            <p className="font-medium text-lg">{stats.gpuUsage}%</p>
          </div>
        </div>

        {/* 显存占用 */}
        <div className="flex items-center gap-3 border-l border-slate-600 pl-4">
          <div className="p-2 bg-slate-700 rounded-lg">
            <HardDrive className="h-5 w-5 text-slate-300" />
          </div>
          <div>
            <p className="text-xs text-slate-400">显存占用</p>
            <p className="font-medium text-lg">
              {formatVRAM(stats.vramUsed)} / {formatVRAM(stats.vramTotal)}
            </p>
          </div>
        </div>

        {/* 队列任务 */}
        <div className="flex items-center gap-3 border-l border-slate-600 pl-4">
          <div className="p-2 bg-slate-700 rounded-lg">
            <ListTodo className="h-5 w-5 text-slate-300" />
          </div>
          <div>
            <p className="text-xs text-slate-400">队列任务</p>
            <p className="font-medium text-lg">{stats.queueSize}</p>
          </div>
        </div>
      </div>

      {/* 错误信息 */}
      {error && (
        <div className="mt-3 flex items-center gap-2 text-red-400 text-sm bg-red-900/20 p-2 rounded">
          <AlertCircle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      )}

      {/* 调试信息 (仅在开发环境显示) */}
      {process.env.NODE_ENV === 'development' && debugInfo && (
        <details className="mt-2 text-xs text-slate-500">
          <summary className="cursor-pointer hover:text-slate-400">调试信息</summary>
          <pre className="mt-1 p-2 bg-slate-900 rounded overflow-auto max-h-40">
            {JSON.stringify(debugInfo, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
