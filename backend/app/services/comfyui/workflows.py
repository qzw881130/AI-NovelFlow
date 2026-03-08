"""
ComfyUI 工作流构建器

负责构建和修改 ComfyUI 工作流
"""
import json
import random
import re
from typing import Dict, Any, Optional, Tuple


class WorkflowBuilder:
    """工作流构建器"""
    
    # 不需要在 API 中执行的节点类型（UI 辅助节点）
    UI_ONLY_NODE_TYPES = {"Note", "Reroute", "PrimitiveNode", "Comment", "Group"}
    
    # 画面比例尺寸配置 (按64倍数调整)
    ASPECT_RATIOS = {
        "16:9": (1088, 704),    # 横向宽屏
        "9:16": (1088, 1920),   # 竖屏
        "4:3": (1088, 832),     # 横向标准
        "3:4": (832, 1088),     # 竖版
        "1:1": (1088, 1088),    # 正方形
        "21:9": (1088, 480),    # 超宽屏
        "2.35:1": (1088, 480),  # 电影宽银幕
    }
    
    # ==================== 工作流构建 ====================
    
    def build_character_workflow(
        self,
        prompt: str,
        workflow_json: str = None,
        novel_id: str = None,
        character_name: str = None,
        aspect_ratio: str = None,
        node_mapping: Dict[str, str] = None,
        style: str = "anime style, high quality, detailed",
        **kwargs
    ) -> Dict[str, Any]:
        """构建角色人设图工作流"""
        if workflow_json:
            workflow = json.loads(workflow_json)
            return self.inject_prompt(
                workflow, prompt, novel_id, character_name,
                aspect_ratio, node_mapping, style
            )
        else:
            width, height = self.get_aspect_ratio_dimensions(aspect_ratio)
            return self._build_flux_workflow(
                prompt=prompt,
                width=width,
                height=height,
                seed=kwargs.get('seed'),
                novel_id=novel_id,
                character_name=character_name
            )
    
    def build_scene_workflow(
        self,
        prompt: str,
        workflow_json: str = None,
        novel_id: str = None,
        scene_name: str = None,
        aspect_ratio: str = None,
        node_mapping: Dict[str, str] = None,
        style: str = "anime style, high quality, detailed",
        **kwargs
    ) -> Dict[str, Any]:
        """构建场景图工作流"""
        # 场景工作流与角色工作流结构相同
        return self.build_character_workflow(
            prompt=prompt,
            workflow_json=workflow_json,
            novel_id=novel_id,
            character_name=scene_name,
            aspect_ratio=aspect_ratio,
            node_mapping=node_mapping,
            style=style,
            **kwargs
        )
    
    def build_shot_workflow(
        self,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        aspect_ratio: str = "16:9",
        seed: Optional[int] = None,
        style: str = "anime style, high quality, detailed",
        reference_images: Dict[str, str] = None,
        character_appearances: Optional[Dict[str, str]] = None,
        scene_setting: Optional[str] = None,
        prop_appearances: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """构建分镜图片工作流

        Args:
            prompt: 分镜描述提示词
            workflow_json: 工作流 JSON 字符串
            node_mapping: 节点映射配置
            aspect_ratio: 画面比例
            seed: 随机种子
            style: 风格提示词
            reference_images: 参考图片映射
            character_appearances: 角色外貌描述映射 {角色名: 外貌描述}
            scene_setting: 场景环境设定
            prop_appearances: 道具外观描述映射 {道具名: 外观描述}

        注意：参考图节点的检测和断开逻辑已移至 shot_image_service 的 _upload_references_and_update_workflow 方法中，
        因为只有在上传参考图之后才能正确判断哪些节点没有图片。
        """
        workflow = json.loads(workflow_json)

        # 替换占位符
        self._replace_style_placeholder(workflow, style)
        self._replace_scene_placeholder(workflow, scene_setting)
        self._replace_characters_placeholder(workflow, character_appearances)
        self._replace_props_placeholder(workflow, prop_appearances)
        
        # 获取宽高
        width, height = self.get_aspect_ratio_dimensions(aspect_ratio)
        
        # 根据节点映射修改工作流
        prompt_node_id = node_mapping.get("prompt_node_id")
        save_image_node_id = node_mapping.get("save_image_node_id")
        width_node_id = node_mapping.get("width_node_id")
        height_node_id = node_mapping.get("height_node_id")
        
        # 设置提示词
        if prompt_node_id and prompt_node_id in workflow:
            self._set_prompt(workflow, prompt_node_id, prompt)
        
        # 设置宽高
        if width_node_id and width_node_id in workflow:
            workflow[width_node_id]["inputs"]["value"] = width
        
        if height_node_id and height_node_id in workflow:
            workflow[height_node_id]["inputs"]["value"] = height
        
        # 处理参考图节点 - 设置已上传的图片
        # 注意：此处的 reference_images 参数用于预设置已知的图片文件名
        # 实际上传和断开未上传节点的逻辑在 shot_image_service 中处理
        if reference_images:
            for ref_key, filename in reference_images.items():
                node_id = node_mapping.get(f"{ref_key}_node_id")
                if node_id and node_id in workflow:
                    workflow[node_id]["inputs"]["image"] = filename
        
        # 设置随机种子
        if seed is None:
            seed = random.randint(1, 2**32)
        self._set_random_seed(workflow, seed)
        
        return workflow
    
    def build_video_workflow(
        self,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        aspect_ratio: str = "16:9",
        seed: Optional[int] = None,
        frame_count: Optional[int] = None,
        style: Optional[str] = None,
        character_appearances: Optional[Dict[str, str]] = None,
        scene_setting: Optional[str] = None,
        prop_appearances: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        构建视频生成工作流

        Args:
            prompt: 视频描述提示词
            workflow_json: 工作流 JSON 字符串
            node_mapping: 节点映射配置
            aspect_ratio: 画面比例
            seed: 随机种子
            frame_count: 总帧数
            style: 风格提示词
            character_appearances: 角色外貌描述映射 {角色名：外貌描述}
            scene_setting: 场景环境设定
            prop_appearances: 道具外观描述映射 {道具名：外观描述}
        """
        workflow = json.loads(workflow_json)

        # 替换占位符
        self._replace_style_placeholder(workflow, style)
        self._replace_scene_placeholder(workflow, scene_setting)
        self._replace_characters_placeholder(workflow, character_appearances)
        self._replace_props_placeholder(workflow, prop_appearances)

        # 获取节点映射
        prompt_node_id = node_mapping.get("prompt_node_id")
        max_side_node_id = node_mapping.get("max_side_node_id", "36")
        frame_count_node_id = node_mapping.get("frame_count_node_id", "35")

        # 设置提示词
        if prompt_node_id and prompt_node_id in workflow:
            self._set_prompt(workflow, prompt_node_id, prompt)

        # 根据画面比例设置最长边
        if max_side_node_id and max_side_node_id in workflow:
            max_side = self._get_max_side(aspect_ratio)
            workflow[max_side_node_id]["inputs"]["value"] = max_side

        # 设置总帧数
        if frame_count and frame_count_node_id in workflow:
            workflow[frame_count_node_id]["inputs"]["value"] = frame_count

        # 设置随机种子
        if seed is None:
            seed = random.randint(1, 2**32)
        self._set_random_seed(workflow, seed)

        return workflow

    def build_voice_design_workflow(
        self,
        voice_prompt: str,
        text: str,
        workflow_json: str = None,
        novel_id: str = None,
        character_name: str = None,
        node_mapping: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        构建音色设计工作流

        Args:
            voice_prompt: 音色提示词（如"温柔女声"、"萝莉音"等）
            text: 要合成的文本
            workflow_json: 自定义工作流JSON字符串
            novel_id: 小说ID
            character_name: 角色名称
            node_mapping: 节点映射配置

        Returns:
            构建好的工作流字典
        """
        if workflow_json:
            workflow = json.loads(workflow_json)
        else:
            return self._build_default_voice_design_workflow(voice_prompt, text, novel_id, character_name)

        # 获取节点映射
        voice_prompt_node_id = str(node_mapping.get("voice_prompt_node_id", "")) if node_mapping else ""
        ref_text_node_id = str(node_mapping.get("ref_text_node_id", "")) if node_mapping else ""
        save_audio_node_id = str(node_mapping.get("save_audio_node_id", "")) if node_mapping else ""

        # 构建保存路径前缀
        save_prefix = None
        if novel_id and character_name:
            safe_name = re.sub(r'[^\w\s-]', '', character_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = "voice"
            save_prefix = f"story_{novel_id}/voices/{safe_name}"
            print(f"[VoiceWorkflow] Save prefix: {save_prefix}")

        # 设置音色提示词（CR Prompt Text 节点）
        if voice_prompt_node_id and voice_prompt_node_id in workflow:
            self._set_prompt(workflow, voice_prompt_node_id, voice_prompt)
            print(f"[VoiceWorkflow] Set voice prompt to node {voice_prompt_node_id}")

        # 设置参考文本（CR Prompt Text 节点）
        if ref_text_node_id and ref_text_node_id in workflow and text:
            self._set_prompt(workflow, ref_text_node_id, text)
            print(f"[VoiceWorkflow] Set text to node {ref_text_node_id}")

        # 设置 SaveAudio 节点的 filename_prefix
        if save_prefix:
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                class_type = node.get("class_type", "")
                inputs = node.get("inputs", {})
                node_id_str = str(node_id)

                if class_type == "SaveAudio":
                    if not save_audio_node_id or node_id_str == save_audio_node_id:
                        inputs["filename_prefix"] = save_prefix
                        print(f"[VoiceWorkflow] Set save prefix to node {node_id}")

        return workflow

    def build_audio_workflow(
        self,
        text: str,
        workflow_json: str = None,
        novel_id: str = None,
        character_name: str = None,
        node_mapping: Dict[str, str] = None,
        reference_audio_filename: str = None,
        emotion_prompt: str = None
    ) -> Dict[str, Any]:
        """
        构建音频生成工作流（带参考音频的语音克隆）

        Args:
            text: 要合成的文本
            workflow_json: 自定义工作流JSON字符串
            novel_id: 小说ID
            character_name: 角色名称
            node_mapping: 节点映射配置
            reference_audio_filename: 参考音频文件名（已上传到 ComfyUI input 目录）
            emotion_prompt: 情感提示词

        Returns:
            构建好的工作流字典
        """
        if workflow_json:
            workflow = json.loads(workflow_json)
        else:
            return self._build_default_audio_workflow(text, novel_id, character_name, reference_audio_filename, emotion_prompt)

        # 获取节点映射
        text_node_id = str(node_mapping.get("text_node_id", "")) if node_mapping else ""
        emotion_prompt_node_id = str(node_mapping.get("emotion_prompt_node_id", "")) if node_mapping else ""
        reference_audio_node_id = str(node_mapping.get("reference_audio_node_id", "")) if node_mapping else ""
        save_audio_node_id = str(node_mapping.get("save_audio_node_id", "")) if node_mapping else ""

        # 设置生成文本（CR Prompt Text 节点）
        if text_node_id and text_node_id in workflow and text:
            self._set_prompt(workflow, text_node_id, text)
            print(f"[AudioWorkflow] Set text to node {text_node_id}")

        # 设置情感提示词（CR Prompt Text 节点）
        if emotion_prompt_node_id and emotion_prompt_node_id in workflow and emotion_prompt:
            self._set_prompt(workflow, emotion_prompt_node_id, emotion_prompt)
            print(f"[AudioWorkflow] Set emotion prompt to node {emotion_prompt_node_id}")

        # 设置参考音频（LoadAudio 节点）
        if reference_audio_node_id and reference_audio_node_id in workflow and reference_audio_filename:
            workflow[reference_audio_node_id]["inputs"]["audio"] = reference_audio_filename
            print(f"[AudioWorkflow] Set reference audio to node {reference_audio_node_id}: {reference_audio_filename}")

        return workflow

    def _build_default_audio_workflow(
        self,
        text: str,
        novel_id: str = None,
        character_name: str = None,
        reference_audio_filename: str = None,
        emotion_prompt: str = None
    ) -> Dict[str, Any]:
        """构建默认的音频生成工作流"""
        workflow = {
            "15": {
                "inputs": {
                    "purge_cache": True,
                    "purge_models": True,
                    "anything": ["31", 0]
                },
                "class_type": "LayerUtility: PurgeVRAM V2"
            },
            "19": {
                "inputs": {
                    "audio": reference_audio_filename or "default.flac",
                    "audioUI": ""
                },
                "class_type": "LoadAudio"
            },
            "24": {
                "inputs": {
                    "model_path": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
                    "precision": "bf16",
                    "device": "cuda",
                    "attn_implementation": "sdpa",
                    "auto_download": False,
                    "download_source": "ModelScope"
                },
                "class_type": "TDQwen3TTSModelLoader"
            },
            "32": {
                "inputs": {
                    "prompt": text
                },
                "class_type": "CR Prompt Text"
            },
            "33": {
                "inputs": {
                    "prompt": emotion_prompt or "自然"
                },
                "class_type": "CR Prompt Text"
            },
            "31": {
                "inputs": {
                    "text": ["32", 0],
                    "language": "Chinese",
                    "ref_text": ["33", 0],
                    "x_vector_only_mode": True,
                    "model": ["24", 0],
                    "ref_audio": ["19", 0]
                },
                "class_type": "TDQwen3TTSVoiceClone"
            },
            "30": {
                "inputs": {
                    "audioUI": "",
                    "audio": ["31", 0]
                },
                "class_type": "PreviewAudio"
            }
        }

        return workflow

    def _build_default_voice_design_workflow(
        self,
        voice_prompt: str,
        text: str,
        novel_id: str = None,
        character_name: str = None
    ) -> Dict[str, Any]:
        """构建默认的音色设计工作流"""
        save_prefix = "audio/ComfyUI"
        if novel_id and character_name:
            safe_name = re.sub(r'[^\w\s-]', '', character_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = "voice"
            save_prefix = f"story_{novel_id}/voices/{safe_name}"

        workflow = {
            "12": {
                "inputs": {
                    "purge_cache": True,
                    "purge_models": True,
                    "anything": ["23", 0]
                },
                "class_type": "LayerUtility: PurgeVRAM V2"
            },
            "22": {
                "inputs": {
                    "model_path": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                    "precision": "bf16",
                    "device": "cuda",
                    "attn_implementation": "sdpa",
                    "auto_download": False,
                    "download_source": "ModelScope"
                },
                "class_type": "TDQwen3TTSModelLoader"
            },
            "53": {
                "inputs": {
                    "prompt": voice_prompt
                },
                "class_type": "CR Prompt Text"
            },
            "54": {
                "inputs": {
                    "prompt": text
                },
                "class_type": "CR Prompt Text"
            },
            "23": {
                "inputs": {
                    "text": ["54", 0],
                    "instruct": ["53", 0],
                    "language": "Chinese",
                    "model": ["22", 0]
                },
                "class_type": "TDQwen3TTSVoiceDesign"
            },
            "52": {
                "inputs": {
                    "filename_prefix": save_prefix,
                    "audioUI": "",
                    "audio": ["23", 0]
                },
                "class_type": "SaveAudio"
            }
        }

        return workflow
    
    # ==================== 工作流修改 ====================
    
    def inject_prompt(
        self,
        workflow: Dict[str, Any],
        prompt: str,
        novel_id: str = None,
        character_name: str = None,
        aspect_ratio: str = None,
        node_mapping: Dict[str, str] = None,
        style: str = "anime style, high quality, detailed"
    ) -> Dict[str, Any]:
        """将提示词注入到工作流中"""
        # 检测工作流格式
        if "nodes" in workflow:
            print("[Workflow] Detected UI format workflow, using built-in workflow")
            return self._build_flux_workflow(prompt)
        
        api_workflow = workflow
        modified_count = 0
        
        # 构建保存路径
        save_prefix = None
        if novel_id and character_name:
            safe_name = re.sub(r'[^\w\s-]', '', character_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = "character"
            save_prefix = f"story_{novel_id}/{safe_name}"
            print(f"[Workflow] Save prefix: {save_prefix}")
        
        # 根据画面比例获取尺寸
        width, height = self.get_aspect_ratio_dimensions(aspect_ratio or "9:16")
        
        # 获取节点映射
        prompt_node_id = str(node_mapping.get("prompt_node_id", "")) if node_mapping else ""
        save_image_node_id = str(node_mapping.get("save_image_node_id", "")) if node_mapping else ""
        
        # 遍历所有节点进行修改
        for node_id, node in api_workflow.items():
            if not isinstance(node, dict):
                continue
            
            inputs = node.get("inputs", {})
            class_type = node.get("class_type", "")
            
            # 设置 SaveImage 节点的 filename_prefix
            if class_type == "SaveImage" and save_prefix:
                if not save_image_node_id or str(node_id) == save_image_node_id:
                    inputs["filename_prefix"] = save_prefix
            
            # 设置图片尺寸
            if class_type in ["EmptySD3LatentImage", "EmptyFlux2LatentImage", "EmptyLatentImage"]:
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height
            
            # 设置调度器尺寸
            if class_type == "Flux2Scheduler":
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height
            
            # 注入提示词
            node_id_str = str(node_id)
            if "text" in inputs:
                current_text = inputs.get("text", "")
                if isinstance(current_text, str):
                    if prompt_node_id and node_id_str == prompt_node_id:
                        inputs["text"] = prompt
                        modified_count += 1
                    elif "{CHARACTER_PROMPT}" in current_text:
                        inputs["text"] = prompt
                        modified_count += 1
                    elif current_text == "" or current_text == "prompt here":
                        inputs["text"] = prompt
                        modified_count += 1
        
        # 回退：自动查找 CLIPTextEncode
        if modified_count == 0 and not prompt_node_id:
            for node_id, node in api_workflow.items():
                if not isinstance(node, dict):
                    continue
                
                class_type = node.get("class_type", "")
                inputs = node.get("inputs", {})
                
                if class_type == "CLIPTextEncode":
                    current_text = inputs.get("text", "")
                    if isinstance(current_text, str):
                        if any(kw in current_text.lower() for kw in ["negative", "bad", "worst"]):
                            continue
                        if "三视图" in current_text or "正面" in current_text:
                            continue
                    
                    inputs["text"] = prompt
                    modified_count += 1
                    break
        
        # 设置随机种子
        self._set_random_seed(api_workflow, random.randint(1, 2**32))
        
        # 替换 ##STYLE## 占位符
        self._replace_style_placeholder(api_workflow, style)
        
        return api_workflow
    
    def set_reference_image(
        self,
        workflow: Dict[str, Any],
        filename: str,
        node_id: str = None,
        image_index: int = 0
    ) -> bool:
        """设置参考图片到工作流"""
        if node_id and node_id in workflow:
            workflow[node_id]["inputs"]["image"] = filename
            return True
        
        # 查找 LoadImage 节点
        load_image_count = 0
        for nid, node in workflow.items():
            if node.get("class_type") == "LoadImage":
                if load_image_count == image_index:
                    workflow[nid]["inputs"]["image"] = filename
                    return True
                load_image_count += 1

        return False

    # ==================== 参考图节点处理 ====================

    def disconnect_reference_chain(
        self,
        workflow: Dict[str, Any],
        start_node_id: str
    ) -> Dict[str, Any]:
        """
        从 LoadImage 节点开始，断开下游参考图链路的输入连接

        当参考图节点未上传图片时，应该断开下游使用 latent、pixels、image 类型输入的连接，
        而不是直接删除节点，这样可以避免工作流报错，兼容性更好。

        匹配规则：
        - latent、pixels：精确匹配
        - image：支持 image 或 image 后跟数字（如 image1, image2, image_1）

        Args:
            workflow: 工作流字典
            start_node_id: 起始节点 ID（通常是 LoadImage 节点）

        Returns:
            修改后的工作流
        """
        # 需要断开的输入类型
        # latent 和 pixels 精确匹配
        # image 支持后跟数字（如 image1, image2, image_1 等）
        EXACT_MATCH_TYPES = {"latent", "pixels"}

        # 追踪已访问的节点，避免循环
        visited = set()
        # 待处理的节点队列
        queue = [str(start_node_id)]

        while queue:
            current_node_id = queue.pop(0)

            if current_node_id in visited:
                continue
            visited.add(current_node_id)

            # 查找所有引用当前节点的下游节点
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue

                inputs = node.get("inputs", {})
                inputs_to_disconnect = []

                for input_name, input_value in inputs.items():
                    # 检查是否是连接到当前节点的输入
                    if isinstance(input_value, list) and len(input_value) >= 2:
                        source_node_id = str(input_value[0])
                        if source_node_id == current_node_id:
                            input_name_lower = input_name.lower()
                            should_disconnect = False

                            # 精确匹配 latent 和 pixels
                            if input_name_lower in EXACT_MATCH_TYPES:
                                should_disconnect = True
                            # image 类型：支持 image 或 image 后跟数字（如 image1, image2, image_1）
                            elif input_name_lower == "image":
                                should_disconnect = True
                            elif input_name_lower.startswith("image"):
                                suffix = input_name_lower[5:]  # 去掉 "image" 前缀
                                # 允许空字符串（即 "image"）或纯数字或 _数字
                                if suffix.isdigit() or (suffix.startswith("_") and suffix[1:].isdigit()):
                                    should_disconnect = True

                            if should_disconnect:
                                inputs_to_disconnect.append(input_name)
                            # 将下游节点加入队列继续追踪
                            if node_id not in visited:
                                queue.append(str(node_id))

                # 断开匹配的输入连接
                for input_name in inputs_to_disconnect:
                    del inputs[input_name]
                    print(f"[Workflow] Disconnected input '{input_name}' from node {node_id} (source: {current_node_id})")

        return workflow

    # ==================== 辅助方法 ====================

    def get_aspect_ratio_dimensions(self, aspect_ratio: str) -> Tuple[int, int]:
        """根据画面比例返回对应的图片尺寸"""
        return self.ASPECT_RATIOS.get(aspect_ratio, (1088, 1920))
    
    def _get_max_side(self, aspect_ratio: str) -> int:
        """根据画面比例获取最长边"""
        if aspect_ratio in ["16:9", "21:9", "2.35:1"]:
            return 1280
        elif aspect_ratio == "9:16":
            return 960
        elif aspect_ratio == "1:1":
            return 1024
        return 960
    
    def _build_flux_workflow(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        seed: Optional[int] = None,
        novel_id: str = None,
        character_name: str = None
    ) -> Dict[str, Any]:
        """构建 Flux 角色人设生成工作流"""
        if seed is None:
            seed = random.randint(1, 2**32 - 1)
        
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
                "inputs": {"vae_name": "ae.safetensors"},
                "class_type": "VAELoader"
            },
            "4": {
                "inputs": {"width": width, "height": height, "batch_size": 1},
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
                "inputs": {"samples": ["5", 0], "vae": ["3", 0]},
                "class_type": "VAEDecode"
            },
            "11": {
                "inputs": {"text": prompt, "clip": ["1", 0]},
                "class_type": "CLIPTextEncode"
            },
            "12": {
                "inputs": {"text": "", "clip": ["1", 0]},
                "class_type": "CLIPTextEncode"
            },
            "13": {
                "inputs": {"filename_prefix": "character_", "images": ["6", 0]},
                "class_type": "SaveImage"
            }
        }
        
        # 设置保存路径前缀
        if novel_id and character_name:
            safe_name = re.sub(r'[^\w\s-]', '', character_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = "character"
            workflow["13"]["inputs"]["filename_prefix"] = f"story_{novel_id}/{safe_name}"
        
        return workflow
    
    def _set_prompt(self, workflow: Dict[str, Any], node_id: str, prompt: str):
        """设置节点提示词"""
        if node_id not in workflow:
            return
        
        node = workflow[node_id]
        class_type = node.get("class_type", "")
        
        if class_type == "CLIPTextEncode":
            workflow[node_id]["inputs"]["text"] = prompt
            print(f"[ComfyUI] Set prompt to CLIPTextEncode node {node_id}")
        elif class_type == "CR Text":
            workflow[node_id]["inputs"]["text"] = prompt
            print(f"[ComfyUI] Set prompt to CR Text node {node_id}")
        elif class_type == "CR Prompt Text":
            workflow[node_id]["inputs"]["prompt"] = prompt
            print(f"[ComfyUI] Set prompt to CR Prompt Text node {node_id}")
        else:
            inputs = node.get("inputs", {})
            if "text" in inputs:
                inputs["text"] = prompt
            elif "prompt" in inputs:
                inputs["prompt"] = prompt
            print(f"[ComfyUI] Set prompt to node {node_id} (type: {class_type})")
    
    def _set_random_seed(self, workflow: Dict[str, Any], seed: int):
        """设置随机种子"""
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            
            inputs = node.get("inputs", {})
            class_type = node.get("class_type", "")
            
            if class_type in ["KSampler", "KSamplerAdvanced", "SamplerCustom", 
                             "SamplerCustomAdvanced", "RandomNoise", "PainterSamplerLTXV"]:
                if "seed" in inputs:
                    inputs["seed"] = seed
                if "noise_seed" in inputs:
                    inputs["noise_seed"] = seed
    
    def _replace_style_placeholder(self, workflow: Dict[str, Any], style: str):
        """替换 ##STYLE## 占位符"""
        if not style:
            return
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for key, value in inputs.items():
                if isinstance(value, str) and "##STYLE##" in value:
                    inputs[key] = value.replace("##STYLE##", style)
                    print(f"[Workflow] Replaced ##STYLE## with '{style}' in node {node_id}.{key}")

    def _replace_scene_placeholder(self, workflow: Dict[str, Any], scene_setting: Optional[str]):
        """替换 ##SCENE## 占位符

        Args:
            workflow: 工作流字典
            scene_setting: 场景环境设定，来自 Scene.setting 字段
        """
        if not scene_setting:
            return
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for key, value in inputs.items():
                if isinstance(value, str) and "##SCENE##" in value:
                    inputs[key] = value.replace("##SCENE##", scene_setting)
                    print(f"[Workflow] Replaced ##SCENE## with '{scene_setting}' in node {node_id}.{key}")

    def _replace_characters_placeholder(self, workflow: Dict[str, Any], character_appearances: Optional[Dict[str, str]]):
        """替换 ##CHARACTERS## 占位符

        Args:
            workflow: 工作流字典
            character_appearances: 角色外貌描述映射 {角色名: 外貌描述}
        """
        if not character_appearances:
            return
        # 合并所有角色的外貌描述
        merged = ", ".join([app for app in character_appearances.values() if app])
        if not merged:
            return
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for key, value in inputs.items():
                if isinstance(value, str) and "##CHARACTERS##" in value:
                    inputs[key] = value.replace("##CHARACTERS##", merged)
                    print(f"[Workflow] Replaced ##CHARACTERS## with '{merged}' in node {node_id}.{key}")

    def _replace_props_placeholder(self, workflow: Dict[str, Any], prop_appearances: Optional[Dict[str, str]]):
        """替换 ##PROPS## 占位符

        Args:
            workflow: 工作流字典
            prop_appearances: 道具外观描述映射 {道具名: 外观描述}
        """
        if not prop_appearances:
            return
        # 合并所有道具的外观描述
        merged = ", ".join([app for app in prop_appearances.values() if app])
        if not merged:
            return
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for key, value in inputs.items():
                if isinstance(value, str) and "##PROPS##" in value:
                    inputs[key] = value.replace("##PROPS##", merged)
                    print(f"[Workflow] Replaced ##PROPS## with '{merged}' in node {node_id}.{key}")
    
    def convert_ui_to_api(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """将 ComfyUI UI 格式转换为 API 格式"""
        if "nodes" not in workflow:
            return workflow
        
        api_workflow = {}
        nodes = workflow.get("nodes", [])
        links = workflow.get("links", [])
        
        valid_nodes = [n for n in nodes if n.get("type") not in self.UI_ONLY_NODE_TYPES]
        valid_node_ids = {str(n.get("id")) for n in valid_nodes}
        
        # 构建 link 查找表
        link_map = {}
        for link in links:
            if len(link) >= 4:
                link_id = link[0]
                source_node = str(link[1])
                source_slot = link[2]
                target_node = str(link[3])
                target_slot = link[4] if len(link) > 4 else 0
                if source_node in valid_node_ids and target_node in valid_node_ids:
                    link_map[link_id] = (source_node, source_slot, target_node, target_slot)
        
        # 转换每个节点
        for node in valid_nodes:
            node_id = str(node.get("id"))
            node_type = node.get("type", "")
            inputs_data = node.get("inputs", [])
            widgets = node.get("widgets_values", [])
            
            inputs = {}
            
            # 处理输入连接
            for i, inp in enumerate(inputs_data):
                if not isinstance(inp, dict):
                    continue
                input_name = inp.get("name", f"input_{i}")
                link = inp.get("link")
                
                if link and link in link_map:
                    source_node, source_slot, _, _ = link_map[link]
                    inputs[input_name] = [str(source_node), source_slot]
            
            # 处理特殊节点
            if node_type == "CheckpointLoaderSimple":
                if widgets:
                    inputs["ckpt_name"] = widgets[0]
            
            api_workflow[node_id] = {
                "inputs": inputs,
                "class_type": node_type
            }
        
        return api_workflow