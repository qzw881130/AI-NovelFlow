from fastapi import APIRouter, HTTPException
import httpx

from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/deepseek")
async def check_deepseek():
    """检查 DeepSeek API 连接状态"""
    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=503, detail="DeepSeek API Key 未配置")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.DEEPSEEK_API_URL}/models",
                headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                timeout=5.0
            )
            if response.status_code == 200:
                return {"status": "ok", "message": "DeepSeek API 连接正常"}
            else:
                raise HTTPException(status_code=503, detail="DeepSeek API 连接失败")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DeepSeek API 连接失败: {str(e)}")


@router.get("/comfyui")
async def check_comfyui():
    """检查 ComfyUI 连接状态并获取系统信息"""
    import traceback
    
    try:
        print(f"[ComfyUI] 正在连接: {settings.COMFYUI_HOST}/system_stats")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.COMFYUI_HOST}/system_stats",
                timeout=10.0
            )
            
            print(f"[ComfyUI] 响应状态: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[ComfyUI] 原始数据: {data}")
                
                system_info = {}
                
                # 提取系统信息 (system 部分)
                system_data = data.get("system", {})
                if system_data:
                    # RAM信息 (字节转GB)
                    ram_total = system_data.get("ram_total", 0)
                    ram_free = system_data.get("ram_free", 0)
                    if ram_total > 0:
                        ram_total_gb = ram_total / (1024**3)
                        ram_used_gb = (ram_total - ram_free) / (1024**3)
                        system_info["ram_total"] = round(ram_total_gb, 1)
                        system_info["ram_used"] = round(ram_used_gb, 1)
                        print(f"[ComfyUI] RAM: {system_info['ram_used']} / {system_info['ram_total']} GB")
                
                # 提取设备信息 (devices 部分)
                devices = data.get("devices", [])
                if devices and len(devices) > 0:
                    device = devices[0]
                    # GPU信息
                    system_info["device_name"] = device.get("name", "Unknown GPU")
                    
                    # 显存计算 (字节转GB)
                    vram_total = device.get("vram_total", 0)
                    # vram_free 可能是 comfyui 计算的可用显存
                    # torch_vram_free 是 pytorch 实际可用的
                    # 我们使用 vram_total - torch_vram_total 来估算已用显存
                    torch_vram_total = device.get("torch_vram_total", 0)
                    
                    if vram_total > 0:
                        vram_total_gb = vram_total / (1024**3)
                        # 已用显存 = 总显存 - (总显存 - torch占用的) 的估算
                        # 或者直接用 torch_vram_total 作为已用显存
                        vram_used_gb = torch_vram_total / (1024**3) if torch_vram_total > 0 else 0
                        
                        system_info["vram_total"] = round(vram_total_gb, 1)
                        system_info["vram_used"] = round(vram_used_gb, 1)
                        
                        print(f"[ComfyUI] VRAM: {system_info['vram_used']} / {system_info['vram_total']} GB")
                    
                    # GPU使用率 (某些ComfyUI版本可能提供)
                    system_info["gpu_usage"] = device.get("gpu_usage", 0)
                    
                    # 温度信息 (某些ComfyUI版本可能提供)
                    if "temperature" in device:
                        system_info["temperature"] = device.get("temperature")
                else:
                    # 如果没有设备信息，设置默认值
                    system_info["device_name"] = "Unknown GPU"
                    system_info["vram_total"] = 16.0
                    system_info["vram_used"] = 0.0
                    system_info["gpu_usage"] = 0
                
                # 尝试获取CPU和HDD信息 (ComfyUI可能不直接提供，这里预留)
                # 如果需要，可以通过其他系统监控工具获取
                
                print(f"[ComfyUI] 解析后的信息: {system_info}")
                return {
                    "status": "ok", 
                    "message": "ComfyUI 连接正常", 
                    "data": system_info,
                    "raw": data  # 返回原始数据用于调试
                }
            else:
                print(f"[ComfyUI] 连接失败: {response.status_code} - {response.text}")
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
