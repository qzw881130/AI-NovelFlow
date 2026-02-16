from fastapi import APIRouter, HTTPException
import httpx

from app.core.config import get_settings
from app.services.comfyui_monitor import get_monitor, init_monitor
from app.services.llm_service import LLMService

router = APIRouter()
settings = get_settings()

# Windows GPU 监控服务地址（ComfyUI 所在机器）
GPU_MONITOR_HOST = "http://192.168.50.1:9999"  # 可根据实际情况修改


async def get_real_gpu_stats():
    """从 Windows GPU 监控服务获取真实 GPU 和系统数据"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GPU_MONITOR_HOST}/gpu-stats",
                timeout=2.0  # 短超时，快速失败
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ok":
                    return {
                        "gpu_usage": data.get("gpu_usage", 0),
                        "temperature": data.get("temperature"),
                        "vram_used": data.get("vram_used", 0),
                        "vram_total": data.get("vram_total", 32),
                        "gpu_name": data.get("gpu_name", "NVIDIA GPU"),  # 显卡型号
                        "ram_used": data.get("ram_used"),      # 内存使用 (GB)
                        "ram_total": data.get("ram_total"),    # 内存总量 (GB)
                        "ram_percent": data.get("ram_percent"), # 内存使用率 (%)
                        "source": "real"  # 标记为真实数据
                    }
    except Exception as e:
        print(f"[GPU Monitor] 获取真实 GPU 数据失败: {e}")
    return None


@router.get("/llm")
async def check_llm():
    """检查 LLM API 连接状态（支持多厂商）"""
    from app.core.config import get_settings
    settings = get_settings()
    
    llm_service = LLMService()
    
    # 调试信息
    debug_info = {
        "provider": llm_service.provider,
        "model": llm_service.model,
        "api_url": llm_service.api_url,
        "api_key_configured": bool(llm_service.api_key),
        "proxy_enabled": llm_service.proxy_enabled,
    }
    
    if not llm_service.api_key:
        raise HTTPException(
            status_code=503, 
            detail={
                "message": "LLM API Key 未配置",
                "debug": debug_info
            }
        )
    
    try:
        result = await llm_service.chat_completion(
            system_prompt="You are a helpful assistant.",
            user_content="Hi",
            max_tokens=10
        )
        
        if result["success"]:
            return {
                "status": "ok",
                "message": f"{llm_service.provider.upper()} API 连接正常",
                "provider": llm_service.provider,
                "model": llm_service.model
            }
        else:
            raise HTTPException(
                status_code=503, 
                detail={
                    "message": "LLM API 连接失败",
                    "error": result.get("error", "未知错误"),
                    "debug": debug_info
                }
            )
    except Exception as e:
        raise HTTPException(
            status_code=503, 
            detail={
                "message": f"LLM API 连接失败: {str(e)}",
                "debug": debug_info
            }
        )


# 兼容旧接口
@router.get("/deepseek")
async def check_deepseek():
    """检查 DeepSeek API 连接状态（兼容旧接口）"""
    return await check_llm()


@router.get("/comfyui")
async def check_comfyui():
    """检查 ComfyUI 连接状态并获取系统信息 - 优先使用真实 GPU 数据"""
    import traceback
    
    try:
        # 1. 优先尝试获取真实 GPU 数据（从 Windows GPU 监控服务）
        real_gpu_stats = await get_real_gpu_stats()
        
        # 获取队列信息（从 ComfyUI）
        queue_running = 0
        queue_pending = 0
        try:
            async with httpx.AsyncClient() as client:
                queue_response = await client.get(
                    f"{settings.COMFYUI_HOST}/queue",
                    timeout=3.0
                )
                if queue_response.status_code == 200:
                    queue_data = queue_response.json()
                    queue_running = len(queue_data.get("queue_running", []))
                    queue_pending = len(queue_data.get("queue_pending", []))
        except Exception as e:
            print(f"[ComfyUI] 获取队列失败: {e}")
        
        if real_gpu_stats:
            # 使用真实的 GPU 数据
            print(f"[ComfyUI] 使用真实 GPU 数据: {real_gpu_stats['gpu_usage']}%, VRAM={real_gpu_stats['vram_used']}/{real_gpu_stats['vram_total']}GB")
            return {
                "status": "ok",
                "message": "ComfyUI 连接正常",
                "data": {
                    "device_name": real_gpu_stats.get("gpu_name", "NVIDIA GPU"),  # 使用真实的显卡型号
                    "gpu_usage": real_gpu_stats["gpu_usage"],
                    "vram_used": real_gpu_stats["vram_used"],
                    "vram_total": real_gpu_stats["vram_total"],
                    "queue_running": queue_running,
                    "queue_pending": queue_pending,
                    "temperature": real_gpu_stats.get("temperature"),
                    "gpu_source": "real",  # 标记为真实数据
                    # 内存信息
                    "ram_used": real_gpu_stats.get("ram_used"),
                    "ram_total": real_gpu_stats.get("ram_total"),
                    "ram_percent": real_gpu_stats.get("ram_percent")
                }
            }
        
        # 2. 回退到监控器数据（估算值）
        monitor = get_monitor()
        if monitor:
            stats = monitor.get_stats()
            if stats["status"] == "online":
                print(f"[ComfyUI] 使用估算数据: GPU={stats['gpu_usage']}%, VRAM={stats['vram_used']}/{stats['vram_total']}GB")
                return {
                    "status": "ok",
                    "message": "ComfyUI 连接正常",
                    "data": {
                        "device_name": "NVIDIA GPU",
                        "gpu_usage": stats["gpu_usage"],
                        "vram_used": stats["vram_used"],
                        "vram_total": stats["vram_total"],
                        "queue_running": queue_running,
                        "queue_pending": queue_pending,
                        "temperature": stats.get("temperature"),
                        "gpu_source": "estimated"  # 标记为估算数据
                    }
                }
        
        # 监控器不可用，回退到直接 HTTP 请求
        print(f"[ComfyUI] 监控器未启动，直接请求: {settings.COMFYUI_HOST}/system_stats")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.COMFYUI_HOST}/system_stats",
                timeout=10.0
            )
            
            print(f"[ComfyUI] 响应状态: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                system_info = {"gpu_usage": 0, "vram_used": 0, "vram_total": 16}
                
                # 提取显存信息
                devices = data.get("devices", [])
                if devices:
                    device = devices[0]
                    system_info["device_name"] = device.get("name", "Unknown GPU")
                    
                    vram_total = device.get("vram_total", 0)
                    torch_vram_total = device.get("torch_vram_total", 0)
                    
                    if vram_total > 0:
                        system_info["vram_total"] = round(vram_total / (1024**3), 1)
                        system_info["vram_used"] = round(torch_vram_total / (1024**3), 1) if torch_vram_total > 0 else 0
                
                return {
                    "status": "ok", 
                    "message": "ComfyUI 连接正常", 
                    "data": system_info,
                }
            else:
                raise HTTPException(status_code=503, detail=f"ComfyUI 返回错误: {response.status_code}")
                
    except httpx.ConnectError as e:
        print(f"[ComfyUI] 连接错误: {e}")
        raise HTTPException(status_code=503, detail=f"无法连接到 ComfyUI ({settings.COMFYUI_HOST})，请确认服务是否启动")
    except Exception as e:
        print(f"[ComfyUI] 异常: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=503, detail=f"ComfyUI 连接失败: {str(e)}")


@router.get("/comfyui-queue")
async def get_comfyui_queue():
    """获取 ComfyUI 队列信息"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.COMFYUI_HOST}/queue",
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                queue_running = data.get("queue_running", [])
                queue_pending = data.get("queue_pending", [])
                return {
                    "status": "ok",
                    "queue_running": len(queue_running),
                    "queue_pending": len(queue_pending),
                    "queue_size": len(queue_running) + len(queue_pending)
                }
            else:
                return {"status": "ok", "queue_size": 0, "error": "无法获取队列信息"}
    except Exception as e:
        return {"status": "error", "queue_size": 0, "error": str(e)}


@router.get("/comfyui-test")
async def test_comfyui_connection():
    """测试 ComfyUI 连接并返回原始数据"""
    import httpx
    
    try:
        async with httpx.AsyncClient() as client:
            # 测试 system_stats
            stats_response = await client.get(
                f"{settings.COMFYUI_HOST}/system_stats",
                timeout=10.0
            )
            
            # 测试 queue
            queue_response = await client.get(
                f"{settings.COMFYUI_HOST}/queue",
                timeout=10.0
            )
            
            return {
                "status": "ok",
                "comfyui_host": settings.COMFYUI_HOST,
                "system_stats": {
                    "status_code": stats_response.status_code,
                    "data": stats_response.json() if stats_response.status_code == 200 else None
                },
                "queue": {
                    "status_code": queue_response.status_code,
                    "data": queue_response.json() if queue_response.status_code == 200 else None
                }
            }
    except Exception as e:
        return {
            "status": "error",
            "comfyui_host": settings.COMFYUI_HOST,
            "error": str(e)
        }


@router.get("/")
async def health_check():
    """基础健康检查"""
    return {"status": "ok", "service": "NovelFlow API"}
