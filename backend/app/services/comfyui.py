import httpx
import json
import uuid
import asyncio
import random
from typing import Dict, Any, Optional, List


class ComfyUIService:
    """ComfyUI 服务封装"""
    
    def __init__(self):
        # 不在初始化时设置base_url，改为每次都动态获取
        self.client_id = str(uuid.uuid4())
    
    @property
    def base_url(self):
        """动态获取当前的ComfyUI主机地址"""
        from app.core.config import get_settings
        return get_settings().COMFYUI_HOST
    
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
    
    def build_character_workflow(self, prompt: str, workflow_json: str = None, novel_id: str = None, character_name: str = None, aspect_ratio: str = None, node_mapping: Dict[str, str] = None, style: str = "anime style, high quality, detailed", **kwargs) -> Dict[str, Any]:
        """
        构建角色人设图工作流（注入参数后的完整工作流）
        
        Args:
            prompt: 提示词
            workflow_json: 工作流 JSON 字符串（可选，不提供则使用默认工作流）
            novel_id: 小说ID，用于设置保存路径
            character_name: 角色名称，用于设置保存路径
            aspect_ratio: 画面比例
            node_mapping: 节点映射配置
            style: 风格描述，用于替换 ##STYLE## 占位符
            
        Returns:
            构建好的工作流字典
        """
        # 使用提供的工作流或构建默认工作流
        if workflow_json:
            workflow = json.loads(workflow_json)
            # 在工作流中查找并替换 prompt
            workflow = self._inject_prompt_to_workflow(workflow, prompt, novel_id, character_name, aspect_ratio, node_mapping, style)
        else:
            # 构建 z-image 工作流提示
            width, height = self._get_aspect_ratio_dimensions(aspect_ratio)
            workflow = self._build_z_image_workflow(
                prompt=prompt,
                width=width,
                height=height,
                seed=kwargs.get('seed'),
                novel_id=novel_id,
                character_name=character_name
            )
        return workflow

    async def generate_character_image(self, prompt: str, workflow_json: str = None, novel_id: str = None, character_name: str = None, aspect_ratio: str = None, node_mapping: Dict[str, str] = None, **kwargs) -> Dict[str, Any]:
        """
        使用指定工作流生成角色人设图
        
        Args:
            prompt: 提示词
            workflow_json: 工作流 JSON 字符串（可选，不提供则使用默认工作流）
            novel_id: 小说ID，用于设置保存路径
            character_name: 角色名称，用于设置保存路径
            aspect_ratio: 画面比例 (16:9, 9:16, 4:3, 3:4, 1:1, 21:9, 2.35:1)
            node_mapping: 节点映射配置 {"prompt_node_id": "133", "save_image_node_id": "9"}
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
            # 构建工作流（使用预构建的或重新构建）
            workflow = kwargs.get('workflow') or self.build_character_workflow(
                prompt=prompt,
                workflow_json=workflow_json,
                novel_id=novel_id,
                character_name=character_name,
                aspect_ratio=aspect_ratio,
                node_mapping=node_mapping,
                **{k: v for k, v in kwargs.items() if k != 'workflow'}
            )
            
            # 提交任务到 ComfyUI
            queue_result = await self._queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            
            # 等待任务完成，传入工作流和 save_image_node_id 配置以识别正确的输出节点
            save_image_node_id = node_mapping.get("save_image_node_id") if node_mapping else None
            result = await self._wait_for_result(prompt_id, workflow, save_image_node_id, timeout=7200)  # 2小时超时
            
            if result.get("success"):
                return {
                    "success": True,
                    "image_url": result.get("image_url"),
                    "message": "生成成功",
                    "submitted_workflow": workflow  # 返回实际提交给ComfyUI的工作流
                }
            else:
                return {
                    "success": False,
                    "message": result.get("message", "生成失败"),
                    "submitted_workflow": workflow  # 即使失败也返回工作流用于调试
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
            
            result = await self._wait_for_result(prompt_id, workflow, timeout=7200)  # 2小时超时
            
            return {
                "success": result.get("success"),
                "image_url": result.get("image_url"),
                "message": result.get("message", ""),
                "submitted_workflow": workflow  # 返回实际提交给ComfyUI的工作流
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
            
            result = await self._wait_for_result(prompt_id, workflow, timeout=7200)  # 视频生成时间较长，2小时超时
            
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
    
    async def _upload_image(self, image_path: str) -> Dict[str, Any]:
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
            
            # 读取图片文件
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
                                # 查找工作流中的所有 SaveImage 节点
                                saveimage_nodes = set()
                                if workflow:
                                    for node_id, node in workflow.items():
                                        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
                                            saveimage_nodes.add(str(node_id))
                                    print(f"[ComfyUI] SaveImage nodes in workflow: {saveimage_nodes}")
                                
                                # 优先查找 SaveImage 节点的输出，或过滤掉临时文件
                                best_image = None
                                best_node_id = None
                                
                                for node_id, node_output in outputs.items():
                                    if "images" in node_output:
                                        images = node_output["images"]
                                        if images:
                                            img_info = images[0]
                                            filename = img_info.get("filename", "")
                                            
                                            # 跳过临时文件 (ComfyUI_temp_xxx)
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
                                            # 否则优先选择任意 SaveImage 节点的输出
                                            elif node_id_str in saveimage_nodes:
                                                best_image = img_info
                                                best_node_id = node_id
                                                print(f"[ComfyUI] Found SaveImage node {node_id} output: {filename}")
                                                break
                                            
                                            # 记录第一个非临时图片作为备选
                                            if best_image is None:
                                                best_image = img_info
                                                best_node_id = node_id
                                
                                # 优先检查视频输出（VHS_VideoCombine 输出）
                                video_found = False
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
                                
                                # 检查图片输出
                                if best_image:
                                    filename = best_image.get("filename")
                                    subfolder = best_image.get("subfolder", "")
                                    img_type = best_image.get("type", "output")
                                    
                                    # 构建 view URL，包含 type 参数
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
        width: int = 1024, 
        height: int = 1024,
        seed: Optional[int] = None,
        novel_id: str = None,
        character_name: str = None
    ) -> Dict[str, Any]:
        """
        构建 Flux 角色人设生成工作流
        
        使用 Flux1-dev 模型生成高质量角色概念图
        """
        if seed is None:
            import random
            seed = random.randint(1, 2**32 - 1)
        
        # Flux1-dev 工作流配置
        workflow = {
            "1": {
                "inputs": {
                    "clip_name1": "clip_l.safetensors",
                    "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                    "type": "flux"
                },
                "class_type": "DualCLIPLoader"
            },
            "2": {
                "inputs": {
                    "unet_name": "flux1-dev-fp8-e4m3fn.safetensors",
                    "weight_dtype": "fp8_e4m3fn"
                },
                "class_type": "UNETLoader"
            },
            "3": {
                "inputs": {
                    "vae_name": "ae.safetensors"
                },
                "class_type": "VAELoader"
            },
            "4": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                },
                "class_type": "EmptyFlux2LatentImage"
            },
            "5": {
                "inputs": {
                    "seed": seed,
                    "steps": 20,
                    "cfg": 1,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1,
                    "model": ["2", 0],
                    "positive": ["11", 0],
                    "negative": ["12", 0],
                    "latent_image": ["4", 0]
                },
                "class_type": "KSampler"
            },
            "6": {
                "inputs": {
                    "samples": ["5", 0],
                    "vae": ["3", 0]
                },
                "class_type": "VAEDecode"
            },
            "11": {
                "inputs": {
                    "text": prompt,
                    "clip": ["1", 0]
                },
                "class_type": "CLIPTextEncode"
            },
            "12": {
                "inputs": {
                    "text": "",
                    "clip": ["1", 0]
                },
                "class_type": "CLIPTextEncode"
            },
            "13": {
                "inputs": {
                    "filename_prefix": "character_",
                    "images": ["6", 0]
                },
                "class_type": "SaveImage"
            }
        }
        
        # 如果有 novel_id 和 character_name，更新 filename_prefix
        if novel_id and character_name:
            import re
            safe_name = re.sub(r'[^\w\s-]', '', character_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = "character"
            save_prefix = f"story_{novel_id}/{safe_name}"
            workflow["13"]["inputs"]["filename_prefix"] = save_prefix
            print(f"[Workflow] Set default workflow filename_prefix to: {save_prefix}")
        
        return workflow
    
    # 不需要在 API 中执行的节点类型（UI 辅助节点）
    UI_ONLY_NODE_TYPES = {"Note", "Reroute", "PrimitiveNode", "Comment", "Group"}
    
    def _convert_ui_workflow_to_api(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 ComfyUI UI 格式（nodes/links）转换为 API 格式（prompt）
        
        UI 格式: {"nodes": [...], "links": [...], ...}
        API 格式: {"node_id": {"inputs": {...}, "class_type": "..."}, ...}
        """
        # 如果已经是 API 格式，直接返回
        if "nodes" not in workflow:
            return workflow
        
        api_workflow = {}
        nodes = workflow.get("nodes", [])
        links = workflow.get("links", [])
        
        # 过滤掉 UI 辅助节点
        valid_nodes = [n for n in nodes if n.get("type") not in self.UI_ONLY_NODE_TYPES]
        valid_node_ids = {str(n.get("id")) for n in valid_nodes}
        
        # 构建 link 查找表: link_id -> (source_node, source_slot, target_node, target_slot)
        link_map = {}
        for link in links:
            if len(link) >= 4:
                link_id = link[0]
                source_node = str(link[1])
                source_slot = link[2]
                target_node = str(link[3])
                target_slot = link[4] if len(link) > 4 else 0
                # 只保留连接到有效节点的 link
                if source_node in valid_node_ids and target_node in valid_node_ids:
                    link_map[link_id] = (source_node, source_slot, target_node, target_slot)
        
        # 转换每个节点
        for node in valid_nodes:
            node_id = str(node.get("id"))
            node_type = node.get("type", "")
            inputs_data = node.get("inputs", [])
            outputs_data = node.get("outputs", [])
            widgets = node.get("widgets_values", [])
            
            # 构建 inputs
            inputs = {}
            
            # 处理输入连接
            for i, inp in enumerate(inputs_data):
                if not isinstance(inp, dict):
                    continue
                input_name = inp.get("name", f"input_{i}")
                link = inp.get("link")
                
                if link and link in link_map:
                    # 这是一个连接输入
                    source_node, source_slot, _, _ = link_map[link]
                    inputs[input_name] = [str(source_node), source_slot]
                elif "widget" in inp and inp.get("widget"):
                    # 这是一个 widget 输入，使用 widgets_values
                    widget_config = inp.get("widget", {})
                    widget_name = widget_config.get("name", input_name)
                    # 从 widgets_values 中找到对应的值
                    widget_idx = None
                    for wi, w in enumerate(inputs_data):
                        if w.get("name") == widget_name:
                            widget_idx = wi
                            break
                    if widget_idx is not None and widget_idx < len(widgets):
                        inputs[input_name] = widgets[widget_idx]
            
            # 添加 widget 值作为输入（对于没有连接的 widget）
            widget_idx = 0
            for inp in inputs_data:
                if not isinstance(inp, dict):
                    continue
                input_name = inp.get("name", "")
                # 如果这个输入还没有被设置，且是 widget
                if input_name not in inputs and inp.get("widget"):
                    if widget_idx < len(widgets):
                        inputs[input_name] = widgets[widget_idx]
                    widget_idx += 1
            
            # 处理特殊节点类型
            if node_type == "CheckpointLoaderSimple":
                # 确保 ckpt_name 被正确设置
                if widgets and len(widgets) > 0:
                    inputs["ckpt_name"] = widgets[0]
            
            api_workflow[node_id] = {
                "inputs": inputs,
                "class_type": node_type
            }
        
        return api_workflow
    
    def _get_aspect_ratio_dimensions(self, aspect_ratio: str) -> tuple[int, int]:
        """
        根据画面比例返回对应的图片尺寸 (width, height)
        尺寸按64的倍数调整，以符合模型要求
        """
        # 基础尺寸配置 (按64倍数调整)
        dimensions = {
            "16:9": (1088, 704),    # 横向宽屏 1920x1080 -> 1088x704
            "9:16": (1088, 1920),   # 竖屏 1088x1920
            "4:3": (1088, 832),     # 横向标准 1024x768 -> 1088x832
            "3:4": (832, 1088),     # 竖版 768x1024 -> 832x1088
            "1:1": (1088, 1088),    # 正方形 1024x1024 -> 1088x1088
            "21:9": (1088, 480),    # 超宽屏 2560x1080 -> 1088x480
            "2.35:1": (1088, 480),  # 电影宽银幕 ~1088x463 -> 1088x480
        }
        return dimensions.get(aspect_ratio, (1088, 1920))  # 默认竖屏
    
    def _inject_prompt_to_workflow(self, workflow: Dict[str, Any], prompt: str, novel_id: str = None, character_name: str = None, aspect_ratio: str = None, node_mapping: Dict[str, str] = None, style: str = "anime style, high quality, detailed") -> Dict[str, Any]:
        """
        将提示词注入到工作流中
        
        支持两种格式：
        1. API 格式: {"node_id": {"inputs": {...}, "class_type": "..."}}
        2. UI 格式: {"nodes": [...], "links": [...]} - 将使用内置工作流
        
        Args:
            workflow: 工作流 JSON
            prompt: 提示词
            novel_id: 小说ID
            character_name: 角色名称
            aspect_ratio: 画面比例
            node_mapping: 节点映射配置 {"prompt_node_id": "133", "save_image_node_id": "9"}
            style: 风格描述，用于替换 ##STYLE## 占位符
        """
        # 检测工作流格式
        if "nodes" in workflow:
            # UI 格式 - 使用内置的简化工作流
            print("[Workflow] Detected UI format workflow, using built-in workflow")
            return self._build_z_image_workflow(prompt)
        
        # API 格式 - 直接注入 prompt
        api_workflow = workflow
        modified_count = 0
        
        # 构建保存路径（不含汉字）
        save_prefix = None
        if novel_id and character_name:
            import re
            safe_name = re.sub(r'[^\w\s-]', '', character_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = "character"
            save_prefix = f"story_{novel_id}/{safe_name}"
            print(f"[Workflow] Save prefix: {save_prefix}")
        
        # 根据画面比例获取尺寸
        width, height = self._get_aspect_ratio_dimensions(aspect_ratio or "9:16")
        print(f"[Workflow] Aspect ratio: {aspect_ratio}, Setting dimensions: {width}x{height}")
        
        # 获取用户配置的节点ID（如果没有配置，使用默认值）
        prompt_node_id = str(node_mapping.get("prompt_node_id", "")) if node_mapping else ""
        save_image_node_id = str(node_mapping.get("save_image_node_id", "")) if node_mapping else ""
        print(f"[Workflow] Node mapping: prompt_node_id={prompt_node_id or 'auto'}, save_image_node_id={save_image_node_id or 'auto'}")
        
        # 遍历所有节点
        for node_id, node in api_workflow.items():
            if not isinstance(node, dict):
                continue
                
            inputs = node.get("inputs", {})
            class_type = node.get("class_type", "")
            
            # 1. 设置 SaveImage 节点的 filename_prefix（优先使用用户配置的节点）
            if class_type == "SaveImage" and save_prefix:
                # 如果配置了 save_image_node_id，只修改该节点；否则修改所有 SaveImage 节点
                if not save_image_node_id or str(node_id) == save_image_node_id:
                    inputs["filename_prefix"] = save_prefix
                    print(f"[Workflow] Set SaveImage node {node_id} filename_prefix to: {save_prefix}")
            
            # 2. 设置图片尺寸节点
            if class_type in ["EmptySD3LatentImage", "EmptyFlux2LatentImage", "EmptyLatentImage"]:
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height
                print(f"[Workflow] Set {class_type} node {node_id} dimensions to {width}x{height}")
            
            # 3. 设置调度器的尺寸参数
            if class_type == "Flux2Scheduler":
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height
                print(f"[Workflow] Set Flux2Scheduler node {node_id} dimensions to {width}x{height}")
            
            # 4. 注入提示词到指定节点或包含占位符的节点
            node_id_str = str(node_id)
            if "text" in inputs:
                current_text = inputs.get("text", "")
                if isinstance(current_text, str):
                    # 优先：如果配置了 prompt_node_id 且匹配当前节点
                    if prompt_node_id and node_id_str == prompt_node_id:
                        inputs["text"] = prompt
                        modified_count += 1
                        print(f"[Workflow] Injected prompt to configured node {node_id}")
                    # 其次：如果包含 {CHARACTER_PROMPT} 占位符
                    elif "{CHARACTER_PROMPT}" in current_text:
                        inputs["text"] = prompt
                        modified_count += 1
                        print(f"[Workflow] Injected prompt to {class_type} node {node_id} (placeholder)")
                    # 最后：空文本或默认占位符
                    elif current_text == "" or current_text == "prompt here":
                        inputs["text"] = prompt
                        modified_count += 1
                        print(f"[Workflow] Injected prompt to {class_type} node {node_id} (empty/default)")
        
        # 如果没有找到占位符且没有配置节点，回退到自动查找 CLIPTextEncode
        if modified_count == 0 and not prompt_node_id:
            for node_id, node in api_workflow.items():
                if not isinstance(node, dict):
                    continue
                    
                class_type = node.get("class_type", "")
                inputs = node.get("inputs", {})
                
                if class_type == "CLIPTextEncode":
                    current_text = inputs.get("text", "")
                    if isinstance(current_text, str):
                        if any(kw in current_text.lower() for kw in ["negative", "bad", "worst", "low quality"]):
                            continue
                        if "三视图" in current_text or "正面" in current_text:
                            continue
                    
                    inputs["text"] = prompt
                    modified_count += 1
                    print(f"[Workflow] Injected prompt to CLIPTextEncode node {node_id} (fallback)")
                    break
        
        # 设置随机种子（如果有）
        import random
        for node_id, node in api_workflow.items():
            if not isinstance(node, dict):
                continue
                
            inputs = node.get("inputs", {})
            class_type = node.get("class_type", "")
            
            # 查找 KSampler 或类似采样节点，设置随机种子
            if class_type in ["KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced", "RandomNoise"]:
                if "seed" in inputs:
                    inputs["seed"] = random.randint(1, 2**32)
                    print(f"[Workflow] Set random seed for {class_type} node {node_id}")
                # 处理 RandomNoise 节点的 noise_seed
                if "noise_seed" in inputs:
                    inputs["noise_seed"] = random.randint(1, 2**32)
                    print(f"[Workflow] Set random noise_seed for {class_type} node {node_id}")
        
        # 搜索并处理三视图提示词节点 (CR Text) - 添加 ##STYLE## 占位符
        # 通过搜索包含特定文本的节点来定位，而不是硬编码节点ID
        for node_id, node in api_workflow.items():
            if not isinstance(node, dict):
                continue
            
            class_type = node.get("class_type", "")
            inputs = node.get("inputs", {})
            
            # 查找 CR Text 节点，且包含三视图相关文本
            if class_type == "CR Text" and "text" in inputs:
                current_text = inputs.get("text", "")
                # 如果是默认的三视图文本（不含##STYLE##），替换为带 ##STYLE## 的版本
                if "三视图" in current_text and "##STYLE##" not in current_text:
                    inputs["text"] = current_text + ", ##STYLE##"
                    print(f"[Workflow] Updated CR Text node {node_id} to include ##STYLE## placeholder")
        
        # 替换所有 ##STYLE## 占位符为传入的 style
        for node_id, node in api_workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for key, value in inputs.items():
                if isinstance(value, str) and "##STYLE##" in value:
                    inputs[key] = value.replace("##STYLE##", style)
                    print(f"[Workflow] Replaced ##STYLE## with '{style}' in node {node_id}.{key}")
        
        return api_workflow
    
    def build_shot_workflow(
        self,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        aspect_ratio: str = "16:9",
        seed: Optional[int] = None,
        style: str = "anime style, high quality, detailed"
    ) -> Dict[str, Any]:
        """
        构建分镜图片工作流（注入参数后的完整工作流，不含图片上传）
        
        Args:
            prompt: 分镜描述提示词
            workflow_json: 工作流 JSON 字符串
            node_mapping: 节点映射配置
            aspect_ratio: 画面比例
            seed: 随机种子
            style: 风格描述，用于替换 ##STYLE## 占位符
            
        Returns:
            构建好的工作流字典
        """
        # 解析工作流
        workflow = json.loads(workflow_json)
        
        # 遍历工流，替换 ##STYLE## 占位符
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for key, value in inputs.items():
                if isinstance(value, str) and "##STYLE##" in value:
                    inputs[key] = value.replace("##STYLE##", style)
                    print(f"[Workflow] Replaced ##STYLE## with '{style}' in node {node_id}.{key}")
        
        # 获取宽高
        width, height = self._get_aspect_ratio_dimensions(aspect_ratio)
        
        # 根据节点映射修改工作流
        prompt_node_id = node_mapping.get("prompt_node_id")
        save_image_node_id = node_mapping.get("save_image_node_id")
        width_node_id = node_mapping.get("width_node_id")
        height_node_id = node_mapping.get("height_node_id")
        
        # 1. 设置提示词
        if prompt_node_id and prompt_node_id in workflow:
            node = workflow[prompt_node_id]
            if node.get("class_type") == "CLIPTextEncode":
                workflow[prompt_node_id]["inputs"]["text"] = prompt
                print(f"[ComfyUI] Set prompt to CLIPTextEncode node {prompt_node_id}")
            elif node.get("class_type") == "CR Text":
                workflow[prompt_node_id]["inputs"]["text"] = prompt
                print(f"[ComfyUI] Set prompt to CR Text node {prompt_node_id}")
        
        # 2. 设置宽高
        if width_node_id and width_node_id in workflow:
            workflow[width_node_id]["inputs"]["value"] = width
            print(f"[ComfyUI] Set width {width} to node {width_node_id}")
        
        if height_node_id and height_node_id in workflow:
            workflow[height_node_id]["inputs"]["value"] = height
            print(f"[ComfyUI] Set height {height} to node {height_node_id}")
        
        # 3. 设置随机种子
        if seed is None:
            seed = random.randint(1, 2**32)
        for node_id, node in workflow.items():
            if node.get("class_type") in ["RandomNoise", "KSampler"]:
                if "seed" in node.get("inputs", {}):
                    workflow[node_id]["inputs"]["seed"] = seed
                if "noise_seed" in node.get("inputs", {}):
                    workflow[node_id]["inputs"]["noise_seed"] = seed
        
        # 4. 设置保存路径前缀
        if save_image_node_id and save_image_node_id in workflow:
            save_node = workflow[save_image_node_id]
            if save_node.get("class_type") == "SaveImage":
                current_prefix = save_node["inputs"].get("filename_prefix", "")
                print(f"[ComfyUI] SaveImage node {save_image_node_id} current prefix: {current_prefix}")
        
        return workflow

    async def generate_shot_image_with_workflow(
        self,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        aspect_ratio: str = "16:9",
        character_reference_path: Optional[str] = None,
        seed: Optional[int] = None,
        workflow: Dict[str, Any] = None,
        style: str = "anime style, high quality, detailed"
    ) -> Dict[str, Any]:
        """
        使用指定工作流生成分镜图片
        
        Args:
            prompt: 分镜描述提示词
            workflow_json: 工作流 JSON 字符串
            node_mapping: 节点映射配置 {"prompt_node_id": "110", "save_image_node_id": "9", "width_node_id": "123", "height_node_id": "125"}
            aspect_ratio: 画面比例 (16:9, 9:16, 4:3, 3:4, 1:1)
            character_reference_path: 角色参考图本地路径（合并后的角色图）
            seed: 随机种子
            workflow: 预构建的工作流（可选，如果提供则直接使用）
            style: 风格描述，用于替换 ##STYLE## 占位符
            
        Returns:
            {
                "success": bool,
                "image_url": str,  # ComfyUI 返回的临时URL
                "message": str
            }
        """
        try:
            # 使用预构建的工作流或重新构建
            if workflow is None:
                workflow = self.build_shot_workflow(
                    prompt=prompt,
                    workflow_json=workflow_json,
                    node_mapping=node_mapping,
                    aspect_ratio=aspect_ratio,
                    seed=seed,
                    style=style
                )
            
            # 获取节点映射中的 save_image_node_id
            save_image_node_id = node_mapping.get("save_image_node_id")
            
            # 上传并设置角色参考图（如果提供）
            if character_reference_path:
                print(f"[ComfyUI] Uploading character reference image: {character_reference_path}")
                upload_result = await self._upload_image(character_reference_path)
                
                if upload_result.get("success"):
                    uploaded_filename = upload_result.get("filename")
                    print(f"[ComfyUI] Image uploaded successfully: {uploaded_filename}")
                    
                    # 优先使用 node_mapping 中配置的 reference_image_node_id
                    reference_image_node_id = node_mapping.get("reference_image_node_id")
                    if reference_image_node_id and reference_image_node_id in workflow:
                        workflow[reference_image_node_id]["inputs"]["image"] = uploaded_filename
                        print(f"[ComfyUI] Set character reference to configured LoadImage node {reference_image_node_id}: {uploaded_filename}")
                    else:
                        # 如果没有配置或配置的节点不存在，查找第一个 LoadImage 节点
                        for node_id, node in workflow.items():
                            if node.get("class_type") == "LoadImage":
                                workflow[node_id]["inputs"]["image"] = uploaded_filename
                                print(f"[ComfyUI] Set character reference to first LoadImage node {node_id}: {uploaded_filename}")
                                break
                else:
                    print(f"[ComfyUI] Failed to upload image: {upload_result.get('message')}")
            
            # 提交任务
            print(f"[ComfyUI] Submitting shot generation task with seed {seed}")
            queue_result = await self._queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            
            # 等待结果
            result = await self._wait_for_result(
                prompt_id, 
                workflow, 
                save_image_node_id=save_image_node_id,
                timeout=7200  # 2小时超时
            )
            
            return {
                "success": result.get("success"),
                "image_url": result.get("image_url"),
                "message": result.get("message", ""),
                "submitted_workflow": workflow,  # 返回实际提交给ComfyUI的工作流
                "prompt_id": prompt_id  # 返回 ComfyUI 任务 ID，用于取消任务
            }
            
        except Exception as e:
            print(f"[ComfyUI] Generate shot image failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"生成失败: {str(e)}"
            }
    
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
    
    async def generate_shot_video_with_workflow(
        self,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        aspect_ratio: str = "16:9",
        character_reference_path: Optional[str] = None,
        seed: Optional[int] = None,
        frame_count: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        使用指定工作流生成分镜视频 (LTX2)
        
        Args:
            prompt: 视频描述提示词
            workflow_json: 工作流 JSON 字符串
            node_mapping: 节点映射配置 {
                "prompt_node_id": "15",           # CR Prompt Text 或 CLIPTextEncode
                "video_save_node_id": "1",        # VHS_VideoCombine
                "reference_image_node_id": "12",  # LoadImage
                "max_side_node_id": "36",         # 最长边设置
                "frame_count_node_id": "35"       # 总帧数设置
            }
            aspect_ratio: 画面比例 (16:9, 9:16, 4:3, 3:4, 1:1)
            character_reference_path: 角色参考图本地路径（分镜图）
            seed: 随机种子
            frame_count: 总帧数（8的倍数+1）
            
        Returns:
            {
                "success": bool,
                "video_url": str,  # ComfyUI 返回的视频URL
                "message": str,
                "submitted_workflow": dict  # 实际提交给ComfyUI的工作流
            }
        """
        try:
            # 解析工作流
            workflow = json.loads(workflow_json)
            
            # 获取节点映射
            prompt_node_id = node_mapping.get("prompt_node_id")
            video_save_node_id = node_mapping.get("video_save_node_id", "1")
            reference_image_node_id = node_mapping.get("reference_image_node_id", "12")
            max_side_node_id = node_mapping.get("max_side_node_id", "36")
            frame_count_node_id = node_mapping.get("frame_count_node_id", "35")
            
            print(f"[ComfyUI] Video node mapping: prompt={prompt_node_id}, save={video_save_node_id}, image={reference_image_node_id}")
            
            # 1. 设置提示词
            if prompt_node_id and prompt_node_id in workflow:
                node = workflow[prompt_node_id]
                class_type = node.get("class_type", "")
                if class_type == "CLIPTextEncode":
                    workflow[prompt_node_id]["inputs"]["text"] = prompt
                    print(f"[ComfyUI] Set prompt to CLIPTextEncode node {prompt_node_id}")
                elif class_type == "CR Prompt Text":
                    workflow[prompt_node_id]["inputs"]["prompt"] = prompt
                    print(f"[ComfyUI] Set prompt to CR Prompt Text node {prompt_node_id}")
                else:
                    # 尝试查找 text 或 prompt 字段
                    inputs = node.get("inputs", {})
                    if "text" in inputs:
                        inputs["text"] = prompt
                    elif "prompt" in inputs:
                        inputs["prompt"] = prompt
                    print(f"[ComfyUI] Set prompt to node {prompt_node_id} (type: {class_type})")
            
            # 2. 上传并设置参考图片（分镜图）
            if character_reference_path:
                print(f"[ComfyUI] Uploading shot reference image: {character_reference_path}")
                upload_result = await self._upload_image(character_reference_path)
                
                if upload_result.get("success"):
                    uploaded_filename = upload_result.get("filename")
                    print(f"[ComfyUI] Image uploaded: {uploaded_filename}")
                    
                    # 设置到指定的 LoadImage 节点
                    if reference_image_node_id and reference_image_node_id in workflow:
                        workflow[reference_image_node_id]["inputs"]["image"] = uploaded_filename
                        print(f"[ComfyUI] Set reference image to node {reference_image_node_id}: {uploaded_filename}")
                    else:
                        print(f"[ComfyUI] Warning: reference_image_node_id {reference_image_node_id} not found in workflow")
                        # 查找所有 LoadImage 节点并设置第一个
                        for node_id, node in workflow.items():
                            if node.get("class_type") == "LoadImage":
                                workflow[node_id]["inputs"]["image"] = uploaded_filename
                                print(f"[ComfyUI] Auto-set reference image to LoadImage node {node_id}: {uploaded_filename}")
                                break
                else:
                    print(f"[ComfyUI] Failed to upload image: {upload_result.get('message')}")
                    return {
                        "success": False,
                        "message": f"图片上传失败: {upload_result.get('message')}"
                    }
            
            # 3. 根据画面比例设置最长边
            if max_side_node_id and max_side_node_id in workflow:
                # 根据比例计算最长边
                max_side = 960  # 默认
                if aspect_ratio in ["16:9", "21:9", "2.35:1"]:
                    max_side = 1280  # 横屏使用更大的尺寸
                elif aspect_ratio in ["9:16"]:
                    max_side = 960   # 竖屏
                elif aspect_ratio == "1:1":
                    max_side = 1024  # 方形
                
                workflow[max_side_node_id]["inputs"]["value"] = max_side
                print(f"[ComfyUI] Set max side {max_side} to node {max_side_node_id}")
            
            # 3.5 设置总帧数（如果提供了）
            frame_count_node_id = node_mapping.get("frame_count_node_id", "35")
            if frame_count and frame_count_node_id and frame_count_node_id in workflow:
                workflow[frame_count_node_id]["inputs"]["value"] = frame_count
                print(f"[ComfyUI] Set frame count {frame_count} to node {frame_count_node_id}")
            
            # 4. 设置随机种子
            if seed is None:
                seed = random.randint(1, 2**32)
            for node_id, node in workflow.items():
                if node.get("class_type") in ["RandomNoise", "KSampler", "PainterSamplerLTXV"]:
                    if "seed" in node.get("inputs", {}):
                        workflow[node_id]["inputs"]["seed"] = seed
                    if "noise_seed" in node.get("inputs", {}):
                        workflow[node_id]["inputs"]["noise_seed"] = seed
            print(f"[ComfyUI] Set seed: {seed}")
            
            # 5. 设置视频保存前缀
            if video_save_node_id and video_save_node_id in workflow:
                save_node = workflow[video_save_node_id]
                if save_node.get("class_type") == "VHS_VideoCombine":
                    current_prefix = save_node["inputs"].get("filename_prefix", "LTX2")
                    print(f"[ComfyUI] Video save node {video_save_node_id} prefix: {current_prefix}")
            
            # 提交任务
            print(f"[ComfyUI] Submitting video generation task")
            queue_result = await self._queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            
            # 等待结果（视频生成时间较长，使用 2 小时超时）
            result = await self._wait_for_result(
                prompt_id, 
                workflow, 
                save_image_node_id=video_save_node_id,
                timeout=7200
            )
            
            # 视频输出可能通过 video_url 或 image_url 返回
            video_url = result.get("video_url") or result.get("image_url")
            return {
                "success": result.get("success"),
                "video_url": video_url,
                "message": result.get("message", ""),
                "submitted_workflow": workflow,  # 返回实际提交的工作流
                "prompt_id": prompt_id  # 返回 ComfyUI 任务 ID，用于取消任务
            }
            
        except Exception as e:
            print(f"[ComfyUI] Generate shot video failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"生成失败: {str(e)}"
            }
    
    async def generate_transition_video_with_workflow(
        self,
        workflow_json: str,
        node_mapping: Dict[str, str],
        first_image_path: str,
        last_image_path: str,
        aspect_ratio: str = "16:9",
        frame_count: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        使用指定工作流生成转场视频 (首帧+尾帧)
        
        Args:
            workflow_json: 工作流 JSON 字符串
            node_mapping: 节点映射配置 {
                "first_image_node_id": "98",      # LoadImage - 首帧
                "last_image_node_id": "106",      # LoadImage - 尾帧
                "video_save_node_id": "105",      # VHS_VideoCombine
                "frame_count_node_id": "174"      # 总帧数设置
            }
            first_image_path: 首帧图片本地路径
            last_image_path: 尾帧图片本地路径
            aspect_ratio: 画面比例
            frame_count: 总帧数（8的倍数+1，如 33, 41, 49, 57）
            
        Returns:
            {
                "success": bool,
                "video_url": str,
                "message": str,
                "submitted_workflow": dict
            }
        """
        try:
            # 解析工作流
            workflow = json.loads(workflow_json)
            
            # 获取节点映射
            first_image_node_id = node_mapping.get("first_image_node_id", "98")
            last_image_node_id = node_mapping.get("last_image_node_id", "106")
            video_save_node_id = node_mapping.get("video_save_node_id", "105")
            frame_count_node_id = node_mapping.get("frame_count_node_id", "174")
            
            print(f"[ComfyUI] Transition node mapping: first={first_image_node_id}, last={last_image_node_id}, save={video_save_node_id}")
            
            # 1. 上传首帧图片
            print(f"[ComfyUI] Uploading first frame image: {first_image_path}")
            first_upload = await self._upload_image(first_image_path)
            if not first_upload.get("success"):
                return {"success": False, "message": f"首帧图片上传失败: {first_upload.get('message')}"}
            
            # 2. 上传尾帧图片
            print(f"[ComfyUI] Uploading last frame image: {last_image_path}")
            last_upload = await self._upload_image(last_image_path)
            if not last_upload.get("success"):
                return {"success": False, "message": f"尾帧图片上传失败: {last_upload.get('message')}"}
            
            # 3. 设置首帧图片到工作流
            if first_image_node_id in workflow:
                workflow[first_image_node_id]["inputs"]["image"] = first_upload.get("filename")
                print(f"[ComfyUI] Set first frame to node {first_image_node_id}: {first_upload.get('filename')}")
            else:
                # 查找第一个 LoadImage 节点
                for node_id, node in workflow.items():
                    if node.get("class_type") == "LoadImage":
                        workflow[node_id]["inputs"]["image"] = first_upload.get("filename")
                        print(f"[ComfyUI] Auto-set first frame to LoadImage node {node_id}")
                        break
            
            # 4. 设置尾帧图片到工作流
            if last_image_node_id in workflow:
                workflow[last_image_node_id]["inputs"]["image"] = last_upload.get("filename")
                print(f"[ComfyUI] Set last frame to node {last_image_node_id}: {last_upload.get('filename')}")
            else:
                # 查找第二个 LoadImage 节点
                load_image_count = 0
                for node_id, node in workflow.items():
                    if node.get("class_type") == "LoadImage":
                        load_image_count += 1
                        if load_image_count == 2:
                            workflow[node_id]["inputs"]["image"] = last_upload.get("filename")
                            print(f"[ComfyUI] Auto-set last frame to LoadImage node {node_id}")
                            break
            
            # 5. 设置总帧数
            if frame_count and frame_count_node_id in workflow:
                workflow[frame_count_node_id]["inputs"]["value"] = frame_count
                print(f"[ComfyUI] Set frame count {frame_count} to node {frame_count_node_id}")
            
            # 6. 设置随机种子
            seed = random.randint(1, 2**32)
            for node_id, node in workflow.items():
                if node.get("class_type") in ["RandomNoise", "KSampler", "PainterSamplerLTXV"]:
                    if "seed" in node.get("inputs", {}):
                        workflow[node_id]["inputs"]["seed"] = seed
                    if "noise_seed" in node.get("inputs", {}):
                        workflow[node_id]["inputs"]["noise_seed"] = seed
            print(f"[ComfyUI] Set seed: {seed}")
            
            # 提交任务
            print(f"[ComfyUI] Submitting transition video generation task")
            queue_result = await self._queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            
            # 等待结果
            result = await self._wait_for_result(
                prompt_id, 
                workflow, 
                save_image_node_id=video_save_node_id,
                timeout=7200
            )
            
            video_url = result.get("video_url") or result.get("image_url")
            return {
                "success": result.get("success"),
                "video_url": video_url,
                "message": result.get("message", ""),
                "submitted_workflow": workflow,
                "prompt_id": prompt_id  # 返回 ComfyUI 任务 ID，用于取消任务
            }
            
        except Exception as e:
            print(f"[ComfyUI] Generate transition video failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"生成失败: {str(e)}"
            }
    
    async def clear_queue(self, max_retries: int = 3) -> Dict[str, Any]:
        """
        清空 ComfyUI 队列中的所有等待任务
        
        Args:
            max_retries: 最大重试次数，默认3次
            
        Returns:
            {
                "success": bool,
                "message": str,
                "attempts": int
            }
        """
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
                    print(f"[ComfyUI] Clear queue response: {response.status_code} (attempt {attempt})")
                    
                    if response.status_code == 200:
                        return {
                            "success": True,
                            "message": "队列已清空" if attempt == 1 else f"队列已清空 (第{attempt}次尝试成功)",
                            "attempts": attempt
                        }
                    else:
                        last_error = f"HTTP {response.status_code}"
                        print(f"[ComfyUI] Clear queue attempt {attempt} failed: {last_error}")
                        
            except Exception as e:
                last_error = str(e)
                print(f"[ComfyUI] Clear queue attempt {attempt} error: {e}")
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < max_retries:
                wait_time = 0.5 * attempt  # 递增延迟：0.5s, 1s, 1.5s
                print(f"[ComfyUI] Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
        
        # 所有尝试都失败
        return {
            "success": False,
            "message": f"清空队列请求失败 (已尝试{max_retries}次): {last_error}",
            "attempts": max_retries
        }
    
    async def delete_from_queue(self, prompt_id: str) -> Dict[str, Any]:
        """
        从 ComfyUI 队列中删除等待执行的任务
        
        Args:
            prompt_id: ComfyUI 任务 ID
            
        Returns:
            {
                "success": bool,
                "message": str
            }
        """
        try:
            async with httpx.AsyncClient() as client:
                print(f"[ComfyUI] Deleting prompt {prompt_id} from queue")
                response = await client.post(
                    f"{self.base_url}/queue",
                    json={"delete": [prompt_id]},
                    timeout=10.0
                )
                print(f"[ComfyUI] Delete queue response: {response.status_code}")
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "message": "已从队列中删除"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"删除失败: {response.status_code}"
                    }
        except Exception as e:
            print(f"[ComfyUI] Delete from queue failed: {e}")
            return {
                "success": False,
                "message": f"删除请求失败: {str(e)}"
            }
    
    async def interrupt_execution(self, max_retries: int = 3) -> Dict[str, Any]:
        """
        中断 ComfyUI 当前正在执行的任务
        
        Args:
            max_retries: 最大重试次数，默认3次
            
        Returns:
            {
                "success": bool,
                "message": str,
                "attempts": int
            }
        """
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    print(f"[ComfyUI] Interrupting current execution (attempt {attempt}/{max_retries})")
                    response = await client.post(
                        f"{self.base_url}/interrupt",
                        timeout=10.0
                    )
                    print(f"[ComfyUI] Interrupt response: {response.status_code} (attempt {attempt})")
                    
                    if response.status_code == 200:
                        return {
                            "success": True,
                            "message": f"已发送中断请求 (第{attempt}次尝试成功)" if attempt > 1 else "已发送中断请求",
                            "attempts": attempt
                        }
                    else:
                        last_error = f"HTTP {response.status_code}"
                        print(f"[ComfyUI] Interrupt attempt {attempt} failed: {last_error}")
                        
            except Exception as e:
                last_error = str(e)
                print(f"[ComfyUI] Interrupt attempt {attempt} error: {e}")
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < max_retries:
                wait_time = 0.5 * attempt  # 递增延迟：0.5s, 1s, 1.5s
                print(f"[ComfyUI] Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
        
        # 所有尝试都失败
        return {
            "success": False,
            "message": f"中断请求失败 (已尝试{max_retries}次): {last_error}",
            "attempts": max_retries
        }
    
    async def cancel_prompt(self, prompt_id: str) -> Dict[str, Any]:
        """
        取消 ComfyUI 中正在执行或等待的任务（综合方法）
        
        Args:
            prompt_id: ComfyUI 任务 ID
            
        Returns:
            {
                "success": bool,
                "message": str
            }
        """
        # 首先尝试从队列中删除
        result = await self.delete_from_queue(prompt_id)
        if result["success"]:
            return result
        
        # 如果删除队列失败，尝试中断当前执行
        return await self.interrupt_execution()
    
    async def get_queue_info(self) -> Dict[str, Any]:
        """
        获取 ComfyUI 队列信息
        
        Returns:
            {
                "queue_running": [...],  # 正在执行的任务
                "queue_pending": [...]   # 等待执行的任务
            }
        """
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
    
    async def cancel_all_matching_tasks(self, prompt_ids: List[str]) -> Dict[str, Any]:
        """
        取消所有匹配的任务（从队列中删除 + 中断正在执行的）
        
        Args:
            prompt_ids: 要取消的 ComfyUI 任务 ID 列表
            
        Returns:
            {
                "deleted_from_queue": [...],
                "interrupted": bool,
                "not_found": [...]
            }
        """
        result = {
            "deleted_from_queue": [],
            "interrupted": False,
            "not_found": []
        }
        
        if not prompt_ids:
            return result
        
        # 1. 获取 ComfyUI 当前队列信息
        queue_info = await self.get_queue_info()
        queue_running = queue_info.get("queue_running", [])
        queue_pending = queue_info.get("queue_pending", [])
        
        print(f"[ComfyUI] Queue running: {len(queue_running)}, pending: {len(queue_pending)}")
        
        # 提取队列中的 prompt_id
        running_ids = set()
        for item in queue_running:
            # queue_running 是一个数组，每个元素是 [prompt_id, ...]
            if isinstance(item, list) and len(item) > 0:
                running_ids.add(str(item[0]))
        
        pending_ids = set()
        for item in queue_pending:
            # queue_pending 结构相同
            if isinstance(item, list) and len(item) > 0:
                pending_ids.add(str(item[0]))
        
        print(f"[ComfyUI] Running IDs: {running_ids}")
        print(f"[ComfyUI] Pending IDs: {pending_ids}")
        
        # 2. 从队列中删除等待中的任务
        for pid in prompt_ids:
            if pid in pending_ids:
                delete_result = await self.delete_from_queue(pid)
                if delete_result["success"]:
                    result["deleted_from_queue"].append(pid)
                    print(f"[ComfyUI] Deleted {pid} from queue")
        
        # 3. 检查是否有正在执行的任务需要中断
        has_running_match = any(pid in running_ids for pid in prompt_ids)
        
        if has_running_match:
            print(f"[ComfyUI] Found running task match, sending interrupt")
            interrupt_result = await self.interrupt_execution()
            result["interrupted"] = interrupt_result["success"]
        
        # 4. 找出未找到的任务
        all_queue_ids = running_ids | pending_ids
        for pid in prompt_ids:
            if pid not in all_queue_ids and pid not in result["deleted_from_queue"]:
                result["not_found"].append(pid)
        
        return result
