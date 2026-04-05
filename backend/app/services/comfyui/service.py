"""
ComfyUI 服务

高级业务方法，组合客户端和工作流构建器
"""
from typing import Dict, Any, Optional, List

from .client import ComfyUIClient
from .workflows import WorkflowBuilder
from app.utils.workflow_disconnect import (
    disconnect_reference_chain,
    disconnect_unuploaded_reference_nodes,
)


class ComfyUIService:
    """ComfyUI 服务封装"""
    
    def __init__(self, base_url: str = None):
        self.client = ComfyUIClient()
        self.builder = WorkflowBuilder()
    
    @property
    def base_url(self) -> str:
        """获取 ComfyUI 基础 URL"""
        return self.client.base_url
    
    # ==================== 健康检查 ====================
    
    async def check_health(self) -> bool:
        """检查 ComfyUI 服务状态"""
        return await self.client.check_health()
    
    async def get_workflows(self) -> Dict[str, Any]:
        """获取可用的工作流列表"""
        return {
            "character_portrait": "z-image",
            "shot_image": "qwen-edit-2511",
            "shot_video": "ltx-2"
        }
    
    # ==================== 图片生成 ====================
    
    async def generate_character_image(
        self,
        prompt: str,
        workflow_json: str = None,
        novel_id: str = None,
        character_name: str = None,
        aspect_ratio: str = None,
        node_mapping: Dict[str, str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """生成角色人设图"""
        try:
            workflow = kwargs.get('workflow') or self.builder.build_character_workflow(
                prompt=prompt,
                workflow_json=workflow_json,
                novel_id=novel_id,
                character_name=character_name,
                aspect_ratio=aspect_ratio,
                node_mapping=node_mapping,
                **{k: v for k, v in kwargs.items() if k != 'workflow'}
            )
            
            queue_result = await self.client.queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }
            
            prompt_id = queue_result.get("prompt_id")
            save_image_node_id = node_mapping.get("save_image_node_id") if node_mapping else None
            
            result = await self.client.wait_for_result(
                prompt_id, workflow, save_image_node_id, timeout=7200
            )
            
            return {
                "success": result.get("success") if result else False,
                "image_url": result.get("image_url") if result else None,
                "message": str(result.get("message", "生成成功" if (result and result.get("success")) else "生成失败")) if result else "生成失败",
                "submitted_workflow": workflow
            }
            
        except Exception as e:
            return {"success": False, "message": f"生成失败: {str(e)}"}
    
    async def generate_scene_image(
        self,
        prompt: str,
        workflow_json: str = None,
        novel_id: str = None,
        scene_name: str = None,
        aspect_ratio: str = None,
        node_mapping: Dict[str, str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """生成场景图"""
        return await self.generate_character_image(
            prompt=prompt,
            workflow_json=workflow_json,
            novel_id=novel_id,
            character_name=scene_name,
            aspect_ratio=aspect_ratio,
            node_mapping=node_mapping,
            **kwargs
        )
    
    async def generate_shot_image_with_workflow(
        self,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        aspect_ratio: str = "16:9",
        character_reference_path: Optional[str] = None,
        scene_reference_path: Optional[str] = None,
        seed: Optional[int] = None,
        workflow: Dict[str, Any] = None,
        style: str = "anime style, high quality, detailed"
    ) -> Dict[str, Any]:
        """使用指定工作流生成分镜图片"""
        try:
            if workflow is None:
                workflow = self.builder.build_shot_workflow(
                    prompt=prompt,
                    workflow_json=workflow_json,
                    node_mapping=node_mapping,
                    aspect_ratio=aspect_ratio,
                    seed=seed,
                    style=style
                )
            
            save_image_node_id = node_mapping.get("save_image_node_id")
            uploaded_filenames = []
            
            # 上传角色参考图
            if character_reference_path:
                upload_result = await self.client.upload_image(character_reference_path)
                if upload_result.get("success"):
                    uploaded_filenames.append(upload_result.get("filename"))
            
            # 上传场景参考图
            if scene_reference_path:
                upload_result = await self.client.upload_image(scene_reference_path)
                if upload_result.get("success"):
                    uploaded_filenames.append(upload_result.get("filename"))
            
            # 设置参考图到 LoadImage 节点
            if uploaded_filenames:
                loadimage_nodes = [
                    nid for nid, node in workflow.items()
                    if node.get("class_type") == "LoadImage"
                ]
                
                for i, filename in enumerate(uploaded_filenames):
                    if i < len(loadimage_nodes):
                        node_id = loadimage_nodes[i]
                        workflow[node_id]["inputs"]["image"] = filename
                        print(f"[ComfyUI] Set reference to LoadImage node {node_id}: {filename}")
            
            # 提交任务
            queue_result = await self.client.queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {"success": False, "message": queue_result.get("error", "提交任务失败")}
            
            prompt_id = queue_result.get("prompt_id")
            
            result = await self.client.wait_for_result(
                prompt_id, workflow, save_image_node_id, timeout=7200
            )
            
            return {
                "success": result.get("success") if result else False,
                "image_url": result.get("image_url") if result else None,
                "message": str(result.get("message")) if result and result.get("message") else "",
                "submitted_workflow": workflow,
                "prompt_id": prompt_id
            }
            
        except Exception as e:
            print(f"[ComfyUI] Generate shot image failed: {e}")
            return {"success": False, "message": f"生成失败: {str(e)}"}
    
    # ==================== 视频生成 ====================
    
    async def generate_shot_video_with_workflow(
        self,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        aspect_ratio: str = "16:9",
        character_reference_path: Optional[str] = None,
        seed: Optional[int] = None,
        frame_count: Optional[int] = None,
        duration_seconds: Optional[int] = None,
        style: Optional[str] = None,
        character_appearances: Optional[Dict[str, str]] = None,
        scene_setting: Optional[str] = None,
        prop_appearances: Optional[Dict[str, str]] = None,
        reference_audio_path: Optional[str] = None,
        keyframe_paths: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """使用指定工作流生成分镜视频 (LTX2)

        Args:
            reference_audio_path: 参考音频本地路径，用于口型同步
            keyframe_paths: 关键帧图片本地路径列表，用于视频生成
            duration_seconds: 视频时长秒数（优先于 frame_count）
        """
        try:
            workflow = self.builder.build_video_workflow(
                prompt=prompt,
                workflow_json=workflow_json,
                node_mapping=node_mapping,
                aspect_ratio=aspect_ratio,
                seed=seed,
                frame_count=frame_count,
                duration_seconds=duration_seconds,
                style=style,
                character_appearances=character_appearances,
                scene_setting=scene_setting,
                prop_appearances=prop_appearances
            )

            reference_image_node_id = node_mapping.get("reference_image_node_id", "12")

            # 上传参考图片
            if character_reference_path:
                upload_result = await self.client.upload_image(character_reference_path)

                if upload_result.get("success"):
                    uploaded_filename = upload_result.get("filename")

                    if reference_image_node_id in workflow:
                        workflow[reference_image_node_id]["inputs"]["image"] = uploaded_filename
                    else:
                        # 自动查找 LoadImage 节点
                        for node_id, node in workflow.items():
                            if node.get("class_type") == "LoadImage":
                                workflow[node_id]["inputs"]["image"] = uploaded_filename
                                break
                else:
                    return {"success": False, "message": f"图片上传失败: {upload_result.get('message')}"}

            # 上传参考音频并注入工作流
            if reference_audio_path:
                audio_upload_result = await self.client.upload_audio(reference_audio_path)

                if audio_upload_result.get("success"):
                    uploaded_audio_filename = audio_upload_result.get("filename")
                    print(f"[ComfyUI] Audio uploaded: {uploaded_audio_filename}")

                    # 获取参考音频节点 ID
                    reference_audio_node_id = node_mapping.get("reference_audio_node_id")

                    if reference_audio_node_id and reference_audio_node_id in workflow:
                        # 设置到指定节点
                        workflow[reference_audio_node_id]["inputs"]["audio"] = uploaded_audio_filename
                        print(f"[ComfyUI] Set audio to node {reference_audio_node_id}")
                    else:
                        # 尝试查找 LoadAudio 节点
                        for node_id, node in workflow.items():
                            if node.get("class_type") == "LoadAudio":
                                workflow[node_id]["inputs"]["audio"] = uploaded_audio_filename
                                print(f"[ComfyUI] Set audio to LoadAudio node {node_id}")
                                break
                else:
                    print(f"[ComfyUI] Audio upload failed: {audio_upload_result.get('message')}")
                    # 音频上传失败不阻止视频生成，只是没有口型同步

            # 上传关键帧图片并注入工作流
            if keyframe_paths:
                for idx, keyframe_path in enumerate(keyframe_paths):
                    if not keyframe_path:
                        continue

                    keyframe_index = idx + 1  # 关键帧索引从 1 开始
                    print(f"[ComfyUI] Uploading keyframe {keyframe_index}: {keyframe_path}")

                    keyframe_upload_result = await self.client.upload_image(keyframe_path)

                    if keyframe_upload_result.get("success"):
                        uploaded_keyframe_filename = keyframe_upload_result.get("filename")
                        print(f"[ComfyUI] Keyframe {keyframe_index} uploaded: {uploaded_keyframe_filename}")

                        # 使用动态命名约定获取关键帧节点 ID: keyframe_node_1, keyframe_node_2, ...
                        keyframe_node_id = node_mapping.get(f"keyframe_node_{keyframe_index}")

                        if keyframe_node_id and keyframe_node_id in workflow:
                            workflow[keyframe_node_id]["inputs"]["image"] = uploaded_keyframe_filename
                            print(f"[ComfyUI] Set keyframe {keyframe_index} to node {keyframe_node_id}")
                        else:
                            # 如果没有配置关键帧节点，尝试自动查找未使用的 LoadImage 节点
                            print(f"[ComfyUI] No keyframe_node_{keyframe_index} in mapping, skipping")
                    else:
                        print(f"[ComfyUI] Keyframe {keyframe_index} upload failed: {keyframe_upload_result.get('message')}")

            # 断开未上传关键帧图片的节点
            # 收集所有关键帧节点
            keyframe_keys = [
                key for key in node_mapping
                if key.startswith("keyframe_node_")
            ]
            for kf_key in keyframe_keys:
                node_id = node_mapping.get(kf_key)
                if node_id and str(node_id) in workflow:
                    node_id_str = str(node_id)
                    # 检查该节点是否有有效的图片
                    image_value = workflow[node_id_str].get("inputs", {}).get("image", "")
                    # 如果没有有效图片，断开下游参考链路
                    if not image_value or image_value in ["", ""]:
                        disconnect_reference_chain(workflow, node_id_str)
                        print(f"[ComfyUI] Disconnected {kf_key} {node_id_str} - no image uploaded")

            # 提交任务
            queue_result = await self.client.queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {"success": False, "message": queue_result.get("error", "提交任务失败")}
            
            prompt_id = queue_result.get("prompt_id")
            video_save_node_id = node_mapping.get("video_save_node_id", "1")
            
            result = await self.client.wait_for_result(
                prompt_id, workflow, video_save_node_id, timeout=7200
            )
            video_url = result.get("video_url") or result.get("image_url")
            return {
                "success": result.get("success") if result else False,
                "video_url": video_url,
                "message": str(result.get("message")) if result and result.get("message") else "",
                "submitted_workflow": workflow,
                "prompt_id": prompt_id
            }
            
        except Exception as e:
            print(f"[ComfyUI] Generate shot video failed: {e}")
            return {"success": False, "message": f"生成失败: {str(e)}"}
    
    async def generate_transition_video_with_workflow(
        self,
        workflow_json: str,
        node_mapping: Dict[str, str],
        first_image_path: str,
        last_image_path: str,
        aspect_ratio: str = "16:9",
        frame_count: Optional[int] = None
    ) -> Dict[str, Any]:
        """生成转场视频 (首帧+尾帧)"""
        try:
            import json
            workflow = json.loads(workflow_json)
            
            first_image_node_id = node_mapping.get("first_image_node_id", "98")
            last_image_node_id = node_mapping.get("last_image_node_id", "106")
            video_save_node_id = node_mapping.get("video_save_node_id", "105")
            frame_count_node_id = node_mapping.get("frame_count_node_id", "174")
            
            # 上传首帧图片
            first_upload = await self.client.upload_image(first_image_path)
            if not first_upload.get("success"):
                return {"success": False, "message": f"首帧图片上传失败: {first_upload.get('message')}"}
            
            # 上传尾帧图片
            last_upload = await self.client.upload_image(last_image_path)
            if not last_upload.get("success"):
                return {"success": False, "message": f"尾帧图片上传失败: {last_upload.get('message')}"}
            
            # 设置图片节点
            if first_image_node_id in workflow:
                workflow[first_image_node_id]["inputs"]["image"] = first_upload.get("filename")
            
            if last_image_node_id in workflow:
                workflow[last_image_node_id]["inputs"]["image"] = last_upload.get("filename")
            
            # 设置帧数
            if frame_count and frame_count_node_id in workflow:
                workflow[frame_count_node_id]["inputs"]["value"] = frame_count
            
            # 设置随机种子
            import random
            self.builder._set_random_seed(workflow, random.randint(1, 2**32))
            
            # 提交任务
            queue_result = await self.client.queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {"success": False, "message": queue_result.get("error", "提交任务失败")}
            
            prompt_id = queue_result.get("prompt_id")
            
            result = await self.client.wait_for_result(
                prompt_id, workflow, video_save_node_id, timeout=7200
            )
            
            video_url = result.get("video_url") or result.get("image_url")
            return {
                "success": result.get("success") if result else False,
                "video_url": video_url,
                "message": str(result.get("message")) if result and result.get("message") else "",
                "submitted_workflow": workflow,
                "prompt_id": prompt_id
            }
            
        except Exception as e:
            print(f"[ComfyUI] Generate transition video failed: {e}")
            return {"success": False, "message": f"生成失败: {str(e)}"}
    
    # ==================== 队列管理 ====================
    
    async def clear_queue(self, max_retries: int = 3) -> Dict[str, Any]:
        """清空队列"""
        return await self.client.clear_queue(max_retries)
    
    async def delete_from_queue(self, prompt_id: str) -> Dict[str, Any]:
        """从队列删除任务"""
        return await self.client.delete_from_queue(prompt_id)
    
    async def interrupt_execution(self, max_retries: int = 3) -> Dict[str, Any]:
        """中断当前执行"""
        return await self.client.interrupt_execution(max_retries)
    
    async def cancel_prompt(self, prompt_id: str) -> Dict[str, Any]:
        """取消任务"""
        result = await self.client.delete_from_queue(prompt_id)
        if result["success"]:
            return result
        return await self.client.interrupt_execution()
    
    async def get_queue_info(self) -> Dict[str, Any]:
        """获取队列信息"""
        return await self.client.get_queue_info()
    
    async def cancel_all_matching_tasks(self, prompt_ids: List[str]) -> Dict[str, Any]:
        """取消所有匹配的任务"""
        return await self.client.cancel_all_matching_tasks(prompt_ids)

    # ==================== 音频生成 ====================

    async def generate_voice(
        self,
        voice_prompt: str,
        text: str,
        workflow_json: str = None,
        novel_id: str = None,
        character_name: str = None,
        node_mapping: Dict[str, str] = None,
        workflow: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        生成角色音色

        Args:
            voice_prompt: 音色提示词
            text: 要合成的文本
            workflow_json: 自定义工作流JSON
            novel_id: 小说ID
            character_name: 角色名称
            node_mapping: 节点映射配置
            workflow: 预构建的工作流

        Returns:
            {"success": bool, "audio_url": str, "message": str}
        """
        try:
            if workflow is None:
                workflow = self.builder.build_voice_design_workflow(
                    voice_prompt=voice_prompt,
                    text=text,
                    workflow_json=workflow_json,
                    novel_id=novel_id,
                    character_name=character_name,
                    node_mapping=node_mapping
                )

            queue_result = await self.client.queue_prompt(workflow)

            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": queue_result.get("error", "提交任务失败")
                }

            prompt_id = queue_result.get("prompt_id")
            save_audio_node_id = node_mapping.get("save_audio_node_id") if node_mapping else None

            result = await self.client.wait_for_audio_result(
                prompt_id, workflow, save_audio_node_id, timeout=600
            )

            return {
                "success": result.get("success") if result else False,
                "audio_url": result.get("audio_url") if result else None,
                "message": str(result.get("message")) if result and result.get("message") else "生成失败",
                "submitted_workflow": workflow
            }

        except Exception as e:
            return {"success": False, "message": f"生成失败: {str(e)}"}


def get_comfyui_service() -> ComfyUIService:
    """获取 ComfyUI 服务实例"""
    return ComfyUIService()