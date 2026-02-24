"""
ComfyUI 实时监控服务
通过 WebSocket 和 HTTP 轮询获取 ComfyUI 状态
"""
import asyncio
import json
import httpx
from typing import Dict, Any, Optional
from datetime import datetime

# 启用 WebSocket 模式（局域网低延迟环境下更实时）
USE_WEBSOCKET = True

# 导入 websockets
try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    print("[ComfyUIMonitor] websockets 库未安装，将使用 HTTP 模式")


class ComfyUIMonitor:
    """ComfyUI 状态监控器"""
    
    def __init__(self, comfyui_host: str):
        # 保留初始值作为备用，但实际使用动态属性
        self._initial_base_url = comfyui_host
        self.stats = {
            "status": "offline",
            "gpu_usage": 0,
            "vram_used": 0,
            "vram_total": 32,  # 默认 32GB，会根据实际情况更新
            "queue_running": 0,
            "queue_pending": 0,
            "temperature": None,  # GPU 温度
            "last_update": None
        }
        self._running = False
        self._task = None
        self._use_websocket = USE_WEBSOCKET
    
    @property
    def base_url(self) -> str:
        """动态获取当前的 ComfyUI 主机地址"""
        from app.core.config import get_settings
        return get_settings().COMFYUI_HOST
    
    @property
    def ws_url(self) -> str:
        """动态获取当前的 WebSocket 地址"""
        return self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
    
    async def start(self):
        """启动监控"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        print(f"[ComfyUIMonitor] 监控已启动: {self.base_url}")
    
    async def stop(self):
        """停止监控"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[ComfyUIMonitor] 监控已停止")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取当前状态"""
        return self.stats.copy()
    
    async def _monitor_loop(self):
        """监控主循环"""
        retry_count = 0
        max_retry_delay = 30
        
        while self._running:
            try:
                if USE_WEBSOCKET and WEBSOCKETS_AVAILABLE and self._use_websocket:
                    # 尝试 WebSocket 连接
                    await self._ws_monitor()
                else:
                    # 纯 HTTP 轮询模式
                    await self._http_poll_loop()
                    
            except Exception as e:
                retry_count += 1
                delay = min(2 ** retry_count, max_retry_delay)  # 指数退避
                print(f"[ComfyUIMonitor] 监控错误 ({retry_count}): {e}, {delay}s 后重试")
                await asyncio.sleep(delay)
    
    async def _http_poll_loop(self):
        """纯 HTTP 轮询模式"""
        while self._running:
            await self._update_system_stats()
            await asyncio.sleep(3)
    
    async def _ws_monitor(self):
        """WebSocket 监控 - 接收实时消息"""
        print(f"[ComfyUIMonitor] 正在连接 WebSocket: {self.ws_url}")
        
        try:
            async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                print("[ComfyUIMonitor] WebSocket 已连接")
                self.stats["status"] = "online"
                
                # 立即获取一次系统状态
                await self._update_system_stats()
                
                last_stats_update = asyncio.get_event_loop().time()
                
                while self._running:
                    try:
                        # 设置接收超时，定期获取系统状态
                        message = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        
                        if isinstance(message, str):
                            data = json.loads(message)
                            await self._handle_ws_message(data)
                        
                    except asyncio.TimeoutError:
                        # 每 3 秒通过 HTTP 获取系统状态
                        now = asyncio.get_event_loop().time()
                        if now - last_stats_update >= 3:
                            await self._update_system_stats()
                            last_stats_update = now
                    except Exception as e:
                        print(f"[ComfyUIMonitor] WebSocket 错误: {e}")
                        break
                        
        except Exception as e:
            print(f"[ComfyUIMonitor] WebSocket 连接失败: {e}")
            # WebSocket 失败后切换到 HTTP 模式
            self._use_websocket = False
            raise
    
    async def _handle_ws_message(self, data: Dict[str, Any]):
        """处理 WebSocket 消息"""
        msg_type = data.get("type")
        
        if msg_type == "status":
            # 状态更新（队列变化）
            status_data = data.get("data", {})
            exec_info = status_data.get("exec_info", {})
            self.stats["queue_running"] = exec_info.get("queue_remaining", 0)
            print(f"[ComfyUIMonitor] 队列状态: {self.stats['queue_running']} 运行中")
            
        elif msg_type == "progress":
            # 进度更新 - 有任务在执行时 GPU 肯定在工作
            progress_data = data.get("data", {})
            value = progress_data.get("value", 0)
            max_val = progress_data.get("max", 100)
            if max_val > 0:
                percent = (value / max_val) * 100
                # 有进度时 GPU 使用率高，可以达到 95-100%
                # 根据进度值动态调整，步数越多 GPU 越可能满载
                estimated_gpu = min(95, int(percent))
                self.stats["gpu_usage"] = max(self.stats["gpu_usage"], estimated_gpu)
                print(f"[ComfyUIMonitor] 进度: {percent:.1f}%, GPU估算: {self.stats['gpu_usage']}%")
        
        elif msg_type == "execution_start":
            # 任务开始执行 - GPU 开始工作
            self.stats["gpu_usage"] = max(self.stats["gpu_usage"], 70)
            print("[ComfyUIMonitor] 任务开始")
            
        elif msg_type == "executing":
            # 正在执行节点 - GPU 满载工作
            node_id = data.get("data")
            if node_id:
                self.stats["gpu_usage"] = max(self.stats["gpu_usage"], 85)
                print(f"[ComfyUIMonitor] 执行节点: {node_id}")
        
        elif msg_type == "execution_success":
            # 任务成功完成
            print("[ComfyUIMonitor] 任务完成")
            self.stats["gpu_usage"] = max(0, self.stats["gpu_usage"] - 30)
            
        elif msg_type == "execution_error":
            # 任务失败
            print("[ComfyUIMonitor] 任务失败")
            self.stats["gpu_usage"] = max(0, self.stats["gpu_usage"] - 30)
        
        self.stats["last_update"] = datetime.utcnow().isoformat()
    
    async def _update_system_stats(self):
        """通过 HTTP 获取系统状态"""
        try:
            print(f"[ComfyUIMonitor] 正在获取系统状态: {self.base_url}/system_stats")
            async with httpx.AsyncClient() as client:
                # 获取系统状态
                response = await client.get(
                    f"{self.base_url}/system_stats",
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"[ComfyUIMonitor] system_stats 响应: {json.dumps(data, indent=2)[:500]}")
                    
                    # 解析显存信息
                    devices = data.get("devices", [])
                    if devices:
                        device = devices[0]
                        vram_total = device.get("vram_total", 0)
                        torch_vram_total = device.get("torch_vram_total", 0)
                        
                        if vram_total > 0:
                            self.stats["vram_total"] = round(vram_total / (1024**3), 1)
                            self.stats["vram_used"] = round(torch_vram_total / (1024**3), 1) if torch_vram_total > 0 else 0
                        
                        # 获取温度（如果 ComfyUI 提供）
                        if "temperature" in device:
                            self.stats["temperature"] = device.get("temperature")
                            
                    self.stats["status"] = "online"
                
                # 获取队列信息
                queue_response = await client.get(
                    f"{self.base_url}/queue",
                    timeout=5.0
                )
                
                if queue_response.status_code == 200:
                    queue_data = queue_response.json()
                    self.stats["queue_running"] = len(queue_data.get("queue_running", []))
                    self.stats["queue_pending"] = len(queue_data.get("queue_pending", []))
                
                # 根据队列状态估算 GPU 使用率
                if self.stats["queue_running"] > 0:
                    # 有任务在运行，GPU 应该满载工作
                    self.stats["gpu_usage"] = max(self.stats["gpu_usage"], 85)
                else:
                    # 没有任务，GPU 应该空闲，逐渐衰减
                    self.stats["gpu_usage"] = max(0, self.stats["gpu_usage"] - 15)
                
                self.stats["last_update"] = datetime.utcnow().isoformat()
                
        except Exception as e:
            print(f"[ComfyUIMonitor] HTTP 获取状态失败: {e}")
            self.stats["status"] = "offline"


# 全局监控器实例
_comfyui_monitor: Optional[ComfyUIMonitor] = None


def get_monitor() -> Optional[ComfyUIMonitor]:
    """获取监控器实例"""
    return _comfyui_monitor


def init_monitor(comfyui_host: str) -> ComfyUIMonitor:
    """初始化监控器"""
    global _comfyui_monitor
    _comfyui_monitor = ComfyUIMonitor(comfyui_host)
    return _comfyui_monitor
