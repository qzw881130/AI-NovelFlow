"""
ComfyUI HTTP 客户端

负责与 ComfyUI 服务的所有 HTTP 通信
"""
import httpx
import uuid
import asyncio
from typing import Dict, Any, Optional, List


class ComfyUIClient:
    """ComfyUI HTTP 客户端"""
    
    def __init__(self):
        self.client_id = str(uuid.uuid4())
    
    @property
    def base_url(self) -> str:
        """动态获取当前的 ComfyUI 主机地址"""
        from app.core.config import get_settings
        return get_settings().COMFYUI_HOST
    
    # ==================== 健康检查 ====================
    
    async def check_health(self) -> bool:
        """检查 ComfyUI 服务状态"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/system_stats",
                    timeout=5.0
                )
                return response.status_code == 200
        except Exception:
            return False
    
    # ==================== 文件上传 ====================
    
    async def upload_image(self, image_path: str) -> Dict[str, Any]:
        """
        上传图片到 ComfyUI
        
        Args:
            image_path: 本地图片路径
            
        Returns:
            {
                "success": bool,
                "filename": str,  # ComfyUI 中的文件名
                "message": str
            }
        """
        try:
            import os
            from pathlib import Path
            
            if not os.path.exists(image_path):
                return {
                    "success": False,
                    "message": f"图片文件不存在: {image_path}"
                }
            
            filename = os.path.basename(image_path)
            
            async with httpx.AsyncClient() as client:
                with open(image_path, 'rb') as f:
                    files = {'image': (filename, f, 'image/png')}
                    data = {'type': 'input', 'overwrite': 'true'}
                    
                    response = await client.post(
                        f"{self.base_url}/upload/image",
                        files=files,
                        data=data,
                        timeout=30.0
                    )
                
                if response.status_code == 200:
                    result = response.json()
                    return {
                        "success": True,
                        "filename": result.get('name', filename),
                        "message": "上传成功"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"上传失败: {response.text}"
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "message": f"上传图片失败: {str(e)}"
            }
    
    # ==================== 任务提交 ====================
    
    async def queue_prompt(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """提交任务到 ComfyUI"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/prompt",
                    json={
                        "prompt": workflow,
                        "client_id": self.client_id
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "prompt_id": data.get("prompt_id")
                    }
                else:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        if "error" in error_data:
                            error_text = error_data["error"]
                        elif "detail" in error_data:
                            error_text = str(error_data["detail"])
                    except:
                        pass
                    
                    print(f"Queue prompt failed: {response.status_code} - {error_text}")
                    return {
                        "success": False,
                        "error": f"ComfyUI 错误 (HTTP {response.status_code}): {error_text}"
                    }
                    
        except Exception as e:
            print(f"Queue prompt error: {e}")
            return {
                "success": False,
                "error": f"连接 ComfyUI 失败: {str(e)}"
            }
    
    # ==================== 结果等待 ====================
    
    async def wait_for_result(
        self, 
        prompt_id: str, 
        workflow: Dict[str, Any] = None,
        save_image_node_id: str = None,
        timeout: int = 120,
        poll_interval: float = 2.0
    ) -> Dict[str, Any]:
        """等待任务完成并获取结果
        
        Args:
            prompt_id: ComfyUI 任务 ID
            workflow: 提交的工作流，用于识别正确的 SaveImage 节点
            save_image_node_id: 配置的 SaveImage 节点 ID，优先使用
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                return {
                    "success": False,
                    "message": f"任务超时 ({timeout}s)"
                }
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.base_url}/history/{prompt_id}",
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        history = response.json()
                        
                        if prompt_id in history:
                            prompt_history = history[prompt_id]
                            outputs = prompt_history.get("outputs", {})
                            
                            if outputs:
                                result = self._parse_outputs(
                                    outputs, workflow, save_image_node_id
                                )
                                if result:
                                    return result
                            
                            # 检查是否有错误
                            status = prompt_history.get("status", {})
                            if status.get("status_str") == "error":
                                return {
                                    "success": False,
                                    "message": status.get("messages", [["", "未知错误"]])[0][1]
                                }
                    
                    await asyncio.sleep(poll_interval)
                    
            except Exception as e:
                print(f"Wait for result error: {e}")
                await asyncio.sleep(poll_interval)
    
    def _parse_outputs(
        self,
        outputs: Dict[str, Any],
        workflow: Dict[str, Any] = None,
        save_image_node_id: str = None
    ) -> Optional[Dict[str, Any]]:
        """解析 ComfyUI 输出结果"""
        # 查找工作流中的所有 SaveImage 节点
        saveimage_nodes = set()
        if workflow:
            for node_id, node in workflow.items():
                if isinstance(node, dict) and node.get("class_type") == "SaveImage":
                    saveimage_nodes.add(str(node_id))
            print(f"[ComfyUI] SaveImage nodes in workflow: {saveimage_nodes}")
        
        # 优先检查视频输出（VHS_VideoCombine 输出）
        for node_id, node_output in outputs.items():
            if "gifs" in node_output:
                videos = node_output["gifs"]
                if videos:
                    video_info = videos[0]
                    filename = video_info.get("filename")
                    subfolder = video_info.get("subfolder", "")
                    video_type = video_info.get("type", "output")
                    
                    params = f"filename={filename}"
                    if subfolder:
                        params += f"&subfolder={subfolder}"
                    params += f"&type={video_type}"
                    
                    video_url = f"{self.base_url}/view?{params}"
                    print(f"[ComfyUI] Found video from node {node_id}: {video_url}")
                    
                    return {
                        "success": True,
                        "video_url": video_url,
                        "message": "生成成功"
                    }
        
        # 查找图片输出
        best_image = None
        best_node_id = None
        
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                images = node_output["images"]
                if images:
                    img_info = images[0]
                    filename = img_info.get("filename", "")
                    
                    # 跳过临时文件
                    if "temp" in filename.lower():
                        print(f"[ComfyUI] Skipping temp file from node {node_id}: {filename}")
                        continue
                    
                    node_id_str = str(node_id)
                    
                    # 如果配置了 save_image_node_id，优先匹配该节点
                    if save_image_node_id:
                        if node_id_str == str(save_image_node_id):
                            best_image = img_info
                            best_node_id = node_id
                            print(f"[ComfyUI] Found configured SaveImage node {node_id} output: {filename}")
                            break
                    elif node_id_str in saveimage_nodes:
                        best_image = img_info
                        best_node_id = node_id
                        print(f"[ComfyUI] Found SaveImage node {node_id} output: {filename}")
                        break
                    
                    if best_image is None:
                        best_image = img_info
                        best_node_id = node_id
        
        if best_image:
            filename = best_image.get("filename")
            subfolder = best_image.get("subfolder", "")
            img_type = best_image.get("type", "output")
            
            params = f"filename={filename}"
            if subfolder:
                params += f"&subfolder={subfolder}"
            params += f"&type={img_type}"
            
            image_url = f"{self.base_url}/view?{params}"
            print(f"[ComfyUI] Selected image from node {best_node_id}: {image_url}")
            
            return {
                "success": True,
                "image_url": image_url,
                "message": "生成成功"
            }
        
        return None
    
    # ==================== 队列管理 ====================
    
    async def get_queue_info(self) -> Dict[str, Any]:
        """获取 ComfyUI 队列信息"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/queue",
                    timeout=10.0
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"[ComfyUI] Get queue failed: {response.status_code}")
                    return {"queue_running": [], "queue_pending": []}
        except Exception as e:
            print(f"[ComfyUI] Get queue error: {e}")
            return {"queue_running": [], "queue_pending": []}
    
    async def clear_queue(self, max_retries: int = 3) -> Dict[str, Any]:
        """清空 ComfyUI 队列中的所有等待任务"""
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    print(f"[ComfyUI] Clearing queue (attempt {attempt}/{max_retries})")
                    response = await client.post(
                        f"{self.base_url}/queue",
                        json={"clear": True},
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        return {
                            "success": True,
                            "message": "队列已清空" if attempt == 1 else f"队列已清空 (第{attempt}次尝试成功)",
                            "attempts": attempt
                        }
                    else:
                        last_error = f"HTTP {response.status_code}"
                        
            except Exception as e:
                last_error = str(e)
            
            if attempt < max_retries:
                wait_time = 0.5 * attempt
                await asyncio.sleep(wait_time)
        
        return {
            "success": False,
            "message": f"清空队列请求失败 (已尝试{max_retries}次): {last_error}",
            "attempts": max_retries
        }
    
    async def delete_from_queue(self, prompt_id: str) -> Dict[str, Any]:
        """从队列中删除等待执行的任务"""
        try:
            async with httpx.AsyncClient() as client:
                print(f"[ComfyUI] Deleting prompt {prompt_id} from queue")
                response = await client.post(
                    f"{self.base_url}/queue",
                    json={"delete": [prompt_id]},
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    return {"success": True, "message": "已从队列中删除"}
                else:
                    return {"success": False, "message": f"删除失败: {response.status_code}"}
        except Exception as e:
            return {"success": False, "message": f"删除请求失败: {str(e)}"}
    
    async def interrupt_execution(self, max_retries: int = 3) -> Dict[str, Any]:
        """中断当前正在执行的任务"""
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.base_url}/interrupt",
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        return {
                            "success": True,
                            "message": "已发送中断请求",
                            "attempts": attempt
                        }
                    else:
                        last_error = f"HTTP {response.status_code}"
                        
            except Exception as e:
                last_error = str(e)
            
            if attempt < max_retries:
                await asyncio.sleep(0.5 * attempt)
        
        return {
            "success": False,
            "message": f"中断请求失败: {last_error}",
            "attempts": max_retries
        }
    
    async def cancel_all_matching_tasks(self, prompt_ids: List[str]) -> Dict[str, Any]:
        """取消所有匹配的任务"""
        result = {
            "deleted_from_queue": [],
            "interrupted": False,
            "not_found": []
        }
        
        if not prompt_ids:
            return result
        
        queue_info = await self.get_queue_info()
        queue_running = queue_info.get("queue_running", [])
        queue_pending = queue_info.get("queue_pending", [])
        
        running_ids = set()
        for item in queue_running:
            if isinstance(item, list) and len(item) > 0:
                running_ids.add(str(item[0]))
        
        pending_ids = set()
        for item in queue_pending:
            if isinstance(item, list) and len(item) > 0:
                pending_ids.add(str(item[0]))
        
        # 从队列中删除等待中的任务
        for pid in prompt_ids:
            if pid in pending_ids:
                delete_result = await self.delete_from_queue(pid)
                if delete_result["success"]:
                    result["deleted_from_queue"].append(pid)
        
        # 检查是否有正在执行的任务需要中断
        has_running_match = any(pid in running_ids for pid in prompt_ids)
        
        if has_running_match:
            interrupt_result = await self.interrupt_execution()
            result["interrupted"] = interrupt_result["success"]
        
        # 找出未找到的任务
        all_queue_ids = running_ids | pending_ids
        for pid in prompt_ids:
            if pid not in all_queue_ids and pid not in result["deleted_from_queue"]:
                result["not_found"].append(pid)
        
        return result
