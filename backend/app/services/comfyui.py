import httpx
import json
import uuid
import asyncio
from typing import Dict, Any, Optional
from app.core.config import get_settings

settings = get_settings()


class ComfyUIService:
    """ComfyUI 服务封装"""
    
    def __init__(self):
        self.base_url = settings.COMFYUI_HOST
        self.client_id = str(uuid.uuid4())
    
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
    
    async def get_workflows(self) -> Dict[str, Any]:
        """获取可用的工作流列表"""
        # z-image: 人设生成
        # qwen-edit-2511: 分镜生图
        # ltx-2: 视频生成
        return {
            "character_portrait": "z-image",
            "shot_image": "qwen-edit-2511",
            "shot_video": "ltx-2"
        }
    
    async def generate_character_image(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        使用 z-image 工作流生成角色人设图
        
        Args:
            prompt: 提示词
            width: 图片宽度 (默认 512)
            height: 图片高度 (默认 768)
            seed: 随机种子
            
        Returns:
            {
                "success": bool,
                "image_url": str,  # 生成的图片URL
                "message": str
            }
        """
        try:
            # 构建 z-image 工作流提示
            workflow = self._build_z_image_workflow(
                prompt=prompt,
                width=kwargs.get('width', 512),
                height=kwargs.get('height', 768),
                seed=kwargs.get('seed')
            )
            
            # 提交任务到 ComfyUI
            queue_result = await self._queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            
            # 等待任务完成
            result = await self._wait_for_result(prompt_id)
            
            if result.get("success"):
                return {
                    "success": True,
                    "image_url": result.get("image_url"),
                    "message": "生成成功"
                }
            else:
                return {
                    "success": False,
                    "message": result.get("message", "生成失败")
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"生成失败: {str(e)}"
            }
    
    async def generate_shot_image(
        self, 
        prompt: str, 
        character_reference: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        使用 qwen-edit-2511 工作流生成分镜图
        
        Args:
            prompt: 场景描述
            character_reference: 角色参考图URL
            width: 图片宽度 (默认 1920)
            height: 图片高度 (默认 1080)
            
        Returns:
            {
                "success": bool,
                "image_url": str,
                "message": str
            }
        """
        try:
            workflow = self._build_qwen_edit_workflow(
                prompt=prompt,
                character_reference=character_reference,
                width=kwargs.get('width', 1920),
                height=kwargs.get('height', 1080)
            )
            
            queue_result = await self._queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            
            result = await self._wait_for_result(prompt_id)
            
            return {
                "success": result.get("success"),
                "image_url": result.get("image_url"),
                "message": result.get("message", "")
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"生成失败: {str(e)}"
            }
    
    async def generate_shot_video(
        self,
        image_url: str,
        motion_strength: float = 1.0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        使用 ltx-2 工作流生成视频
        
        Args:
            image_url: 输入图片URL
            motion_strength: 运动强度
            fps: 帧率
            num_frames: 帧数
            
        Returns:
            {
                "success": bool,
                "video_url": str,
                "message": str
            }
        """
        try:
            workflow = self._build_ltx_workflow(
                image_url=image_url,
                motion_strength=motion_strength,
                fps=kwargs.get('fps', 24),
                num_frames=kwargs.get('num_frames', 48)
            )
            
            queue_result = await self._queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            
            result = await self._wait_for_result(prompt_id, timeout=300)  # 视频生成时间较长
            
            return {
                "success": result.get("success"),
                "video_url": result.get("video_url"),
                "message": result.get("message", "")
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"生成失败: {str(e)}"
            }
    
    async def _queue_prompt(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
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
                        # 尝试解析 JSON 错误
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
    
    async def _wait_for_result(
        self, 
        prompt_id: str, 
        timeout: int = 120,
        poll_interval: float = 2.0
    ) -> Dict[str, Any]:
        """等待任务完成并获取结果"""
        start_time = asyncio.get_event_loop().time()
        
        while True:
            # 检查是否超时
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                return {
                    "success": False,
                    "message": f"任务超时 ({timeout}s)"
                }
            
            try:
                async with httpx.AsyncClient() as client:
                    # 获取历史记录
                    response = await client.get(
                        f"{self.base_url}/history/{prompt_id}",
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        history = response.json()
                        
                        if prompt_id in history:
                            prompt_history = history[prompt_id]
                            
                            # 检查是否有输出
                            outputs = prompt_history.get("outputs", {})
                            
                            if outputs:
                                # 找到图片输出
                                for node_id, node_output in outputs.items():
                                    if "images" in node_output:
                                        images = node_output["images"]
                                        if images:
                                            # 构建图片URL
                                            filename = images[0].get("filename")
                                            subfolder = images[0].get("subfolder", "")
                                            image_url = f"{self.base_url}/view?filename={filename}&subfolder={subfolder}"
                                            
                                            return {
                                                "success": True,
                                                "image_url": image_url,
                                                "message": "生成成功"
                                            }
                                    
                                    # 检查视频输出
                                    if "gifs" in node_output or "videos" in node_output:
                                        videos = node_output.get("gifs") or node_output.get("videos")
                                        if videos:
                                            filename = videos[0].get("filename")
                                            subfolder = videos[0].get("subfolder", "")
                                            video_url = f"{self.base_url}/view?filename={filename}&subfolder={subfolder}"
                                            
                                            return {
                                                "success": True,
                                                "video_url": video_url,
                                                "message": "生成成功"
                                            }
                            
                            # 检查是否有错误
                            status = prompt_history.get("status", {})
                            if status.get("status_str") == "error":
                                return {
                                    "success": False,
                                    "message": status.get("messages", [["", "未知错误"]])[0][1]
                                }
                    
                    # 任务还在进行中，等待后重试
                    await asyncio.sleep(poll_interval)
                    
            except Exception as e:
                print(f"Wait for result error: {e}")
                await asyncio.sleep(poll_interval)
    
    def _build_z_image_workflow(
        self, 
        prompt: str, 
        width: int = 512, 
        height: int = 768,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        构建 z-image 人设生成工作流
        
        这是一个简化的工作流结构，实际需要根据你的 ComfyUI 中 z-image 工作流的具体节点来配置
        """
        if seed is None:
            seed = uuid.uuid4().int % (2**32)
        
        # 基础工作流结构 - 需要根据实际 ComfyUI 工作流调整
        workflow = {
            "1": {
                "inputs": {
                    "text": prompt,
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "2": {
                "inputs": {
                    "text": "text, watermark, low quality, blurry",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "3": {
                "inputs": {
                    "seed": seed,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["1", 0],
                    "negative": ["2", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler"
            },
            "4": {
                "inputs": {
                    "ckpt_name": "z-image.safetensors"  # 需要根据实际模型名称调整
                },
                "class_type": "CheckpointLoaderSimple"
            },
            "5": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            "6": {
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                },
                "class_type": "VAEDecode"
            },
            "7": {
                "inputs": {
                    "filename_prefix": "character",
                    "images": ["6", 0]
                },
                "class_type": "SaveImage"
            }
        }
        
        return workflow
    
    def _build_qwen_edit_workflow(
        self,
        prompt: str,
        character_reference: Optional[str] = None,
        width: int = 1920,
        height: int = 1080
    ) -> Dict[str, Any]:
        """构建 qwen-edit-2511 分镜生图工作流"""
        # 占位符 - 需要根据实际工作流配置
        workflow = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "character_reference": character_reference
        }
        return workflow
    
    def _build_ltx_workflow(
        self,
        image_url: str,
        motion_strength: float = 1.0,
        fps: int = 24,
        num_frames: int = 48
    ) -> Dict[str, Any]:
        """构建 ltx-2 视频生成工作流"""
        # 占位符 - 需要根据实际工作流配置
        workflow = {
            "image": image_url,
            "motion_strength": motion_strength,
            "fps": fps,
            "num_frames": num_frames
        }
        return workflow
