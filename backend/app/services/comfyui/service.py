"""
ComfyUI 服务

高级业务方法，组合客户端和工作流构建器
"""
from hashlib import sha256
import inspect
import json
from typing import Dict, Any, Optional, List
from uuid import uuid4

from .client import ComfyUIClient
from .workflows import WorkflowBuilder
from app.utils.workflow_disconnect import (
    disconnect_reference_chain,
    disconnect_unuploaded_reference_nodes,
)


class H3PromptSubmissionError(ValueError):
    """A definite pre-queue prompt/binding rejection, not a transport failure."""


class VisualReferenceSubmissionError(ValueError):
    """The opted-in, observed image bytes were not bound to the requested inputs."""


def is_h3_workflow(workflow: Dict[str, Any]) -> bool:
    """Detect H3 by executable node classes, not names, mappings or prompt text."""
    return isinstance(workflow, dict) and any(
        isinstance(node, dict)
        and isinstance(node.get("class_type"), str)
        and node["class_type"].startswith("MiniMaxH3")
        for node in workflow.values()
    )


def resolve_h3_consumed_prompt(
    workflow: Dict[str, Any], node_mapping: Dict[str, str]
) -> str:
    """Resolve shipped H3 STRING chains without executing or modifying the graph.

    Every H3 text consumer must use the mapped prompt node. Unknown node/slot
    semantics, dynamic text, cycles and conflicting consumers fail closed.
    """
    if not isinstance(workflow, dict):
        raise H3PromptSubmissionError("H3 workflow must be an API graph")
    mapped_id = node_mapping.get("prompt_node_id") if isinstance(node_mapping, dict) else None
    if not isinstance(mapped_id, str) or not mapped_id or not isinstance(workflow.get(mapped_id), dict):
        raise H3PromptSubmissionError("H3 requires a valid prompt_node_id mapping")

    consumers = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if class_type in ("MiniMaxH3AudioConditioningT8", "MiniMaxH3ReferenceToVideo"):
            consumers.append((node_id, node))
        elif isinstance(class_type, str) and class_type.startswith("MiniMaxH3") and class_type not in (
            "MiniMaxH3AVDecodeT8",
            "MiniMaxH3DualClockSamplerT8",
            "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "MiniMaxH3SigmaShift",
            "MiniMaxH3PromptEnhancerT8",
        ):
            raise H3PromptSubmissionError(f"Unsupported H3 node semantics: {class_type}")
    if not consumers:
        raise H3PromptSubmissionError("H3 workflow has no supported prompt consumer")

    # Both shipped consumers take STRING, not CLIPTextEncode's CONDITIONING.
    string_inputs = {"CR Prompt Text": "prompt", "PrimitiveStringMultiline": "value"}
    consumed_prompt = None
    for consumer_id, consumer in consumers:
        inputs = consumer.get("inputs")
        if not isinstance(inputs, dict):
            raise H3PromptSubmissionError(f"Invalid H3 consumer inputs: {consumer_id}")
        value = inputs.get("prompt")
        visited = {consumer_id}
        while isinstance(value, list):
            if len(value) != 2 or not isinstance(value[0], str) or not value[0]:
                raise H3PromptSubmissionError(f"Uncertain H3 prompt link at consumer {consumer_id}")
            source_id, slot = value
            if type(slot) is not int or slot != 0:
                raise H3PromptSubmissionError(f"Unsupported H3 STRING output slot: {source_id}:{slot}")
            if source_id in visited:
                raise H3PromptSubmissionError(f"Cyclic H3 prompt chain at node {source_id}")
            visited.add(source_id)
            source = workflow.get(source_id)
            if not isinstance(source, dict):
                raise H3PromptSubmissionError(f"Invalid H3 prompt source: {source_id}")
            field = string_inputs.get(source.get("class_type"))
            if field is None:
                raise H3PromptSubmissionError(f"Unsupported dynamic H3 prompt chain at node {source_id}")
            inputs = source.get("inputs")
            if not isinstance(inputs, dict):
                raise H3PromptSubmissionError(f"Invalid H3 prompt source inputs: {source_id}")
            value = inputs.get(field)
        if not isinstance(value, str):
            raise H3PromptSubmissionError(f"H3 prompt is not a literal STRING at consumer {consumer_id}")
        if consumed_prompt is not None and value != consumed_prompt:
            raise H3PromptSubmissionError("Conflicting H3 prompt consumers")
        if mapped_id not in visited:
            raise H3PromptSubmissionError(f"H3 prompt_node_id is unconnected to consumer {consumer_id}")
        consumed_prompt = value
    return consumed_prompt


class ComfyUIService:
    """ComfyUI 服务封装"""
    
    def __init__(self, base_url: str = None):
        self.client = ComfyUIClient()
        self.builder = WorkflowBuilder()

    @staticmethod
    def _notify_prompt_queued(callback, prompt_id: str, workflow: Dict[str, Any]) -> None:
        if not callback or not prompt_id:
            return
        try:
            signature = inspect.signature(callback)
            positional_params = [
                param for param in signature.parameters.values()
                if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
            ]
            has_varargs = any(param.kind == param.VAR_POSITIONAL for param in signature.parameters.values())
            if has_varargs or len(positional_params) >= 2:
                callback(prompt_id, workflow)
            else:
                callback(prompt_id)
        except (TypeError, ValueError):
            callback(prompt_id)
    
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

    async def edit_image_with_workflow(
        self,
        image_path: str,
        prompt: str,
        workflow_json: str,
        node_mapping: Dict[str, str],
        on_prompt_queued=None,
    ) -> Dict[str, Any]:
        """使用单图编辑工作流编辑图片。"""
        try:
            import json

            workflow = json.loads(workflow_json)
            load_image_node_id = str(node_mapping.get("load_image_node_id", ""))
            prompt_node_id = str(node_mapping.get("prompt_node_id", ""))
            save_image_node_id = str(node_mapping.get("save_image_node_id", ""))

            if not load_image_node_id or load_image_node_id not in workflow:
                return {"success": False, "message": "单图编辑工作流缺少 Load Image 节点映射"}
            if not prompt_node_id or prompt_node_id not in workflow:
                return {"success": False, "message": "单图编辑工作流缺少提示词节点映射"}
            if not save_image_node_id or save_image_node_id not in workflow:
                return {"success": False, "message": "单图编辑工作流缺少 Save Image 节点映射"}

            upload_result = await self.client.upload_image(image_path)
            if not upload_result.get("success"):
                return {"success": False, "message": upload_result.get("message", "图片上传失败")}

            workflow[load_image_node_id].setdefault("inputs", {})["image"] = upload_result.get("filename")
            self.builder._set_prompt(workflow, prompt_node_id, prompt)

            queue_result = await self.client.queue_prompt(workflow)
            if not queue_result.get("success"):
                return {"success": False, "message": queue_result.get("error", "提交任务失败")}

            prompt_id = queue_result.get("prompt_id")
            self._notify_prompt_queued(on_prompt_queued, prompt_id, workflow)

            result = await self.client.wait_for_result(
                prompt_id,
                workflow,
                save_image_node_id,
                timeout=7200,
            )

            return {
                "success": result.get("success") if result else False,
                "image_url": result.get("image_url") if result else None,
                "message": str(result.get("message", "编辑成功" if (result and result.get("success")) else "编辑失败")) if result else "编辑失败",
                "submitted_workflow": workflow,
                "prompt_id": prompt_id,
            }
        except Exception as e:
            print(f"[ComfyUI] Edit image failed: {e}")
            return {"success": False, "message": f"编辑失败: {str(e)}"}
    
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
        style: str = "anime style, high quality, detailed",
        on_prompt_queued=None
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
            self._notify_prompt_queued(on_prompt_queued, prompt_id, workflow)
            
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
        drive_audio_path: Optional[str] = None,
        final_audio_path: Optional[str] = None,
        keyframe_paths: Optional[List[str]] = None,
        on_prompt_queued=None,
        on_before_submit=None,
        frozen_image_inputs: Optional[List[Dict[str, Any]]] = None,
        on_image_inputs_bound=None,
    ) -> Dict[str, Any]:
        """使用指定工作流生成分镜视频 (LTX2)

        Args:
            reference_audio_path: 参考音频本地路径，用于口型同步
            keyframe_paths: 关键帧图片本地路径列表，用于视频生成
            duration_seconds: 视频时长秒数（优先于 frame_count）
            on_before_submit: Required for H3; sync/async callback(workflow).
                Must not mutate H3 graphs; raise an exception to veto submission.
            frozen_image_inputs: Opt-in primary/extra payloads already observed by
                the visual-state validator; never re-read their source paths.
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
            h3_workflow = is_h3_workflow(workflow)

            reference_image_node_id = node_mapping.get("reference_image_node_id", "12")

            image_bindings = []
            if frozen_image_inputs is not None:
                paths = [character_reference_path, *(keyframe_paths or [])]
                if not paths[0] or len(frozen_image_inputs) != len(paths) or not callable(on_image_inputs_bound):
                    raise VisualReferenceSubmissionError("VALIDATED_REFERENCE_SET_MISMATCH")
                nodes = [reference_image_node_id, *[node_mapping.get(f"keyframe_node_{i}") for i in range(1, len(paths))]]
                if (any(not isinstance(node, str) or not node or workflow.get(node, {}).get("class_type") != "LoadImage"
                        or not isinstance(workflow[node].get("inputs"), dict) for node in nodes)
                        or len(set(nodes)) != len(nodes)):
                    raise VisualReferenceSubmissionError("VALIDATED_REFERENCE_MAPPING_MISSING_OR_DUPLICATED")
                # Check the whole set before starting uploads, not one image at a time.
                for index, (item, path) in enumerate(zip(frozen_image_inputs, paths)):
                    payload = item.get("payload")
                    if (type(item.get("reference_index")) is not int or item["reference_index"] != index
                            or item.get("source_path") != path or type(payload) is not bytes or not payload
                            or item.get("sha256") != sha256(payload).hexdigest()):
                        raise VisualReferenceSubmissionError("VALIDATED_REFERENCE_PAYLOAD_MISMATCH")
                for index, (item, path, node) in enumerate(zip(frozen_image_inputs, paths, nodes)):
                    uploaded = await self.client.upload_image(path, payload=item["payload"],
                                                              upload_name=f"visual-state-{uuid4().hex}.png")
                    if (uploaded.get("success") is not True or uploaded.get("type") != "input"
                            or not isinstance(uploaded.get("filename"), str) or not uploaded["filename"]
                            or uploaded.get("payload_sha256") != item["sha256"]
                            or type(uploaded.get("payload_size")) is not int or uploaded["payload_size"] != len(item["payload"])):
                        raise VisualReferenceSubmissionError("VALIDATED_REFERENCE_UPLOAD_FAILED")
                    workflow[node]["inputs"]["image"] = uploaded["filename"]
                    image_bindings.append({"reference_index": index, "source_path": path,
                                           "sha256": item["sha256"], "bytes": len(item["payload"]),
                                           "node_id": node, "field": "image", "upload": dict(uploaded)})

            # 上传参考图片
            if character_reference_path and frozen_image_inputs is None:
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

            # 上传 AudioDrive 音频并注入工作流。H3 V2.1 使用 drive/final 两路 LoadAudio。
            audio_inputs = []
            if drive_audio_path:
                audio_inputs.append(("drive_audio_node_id", drive_audio_path, "drive_audio"))
            if final_audio_path:
                audio_inputs.append(("final_audio_node_id", final_audio_path, "final_audio"))
            for mapping_key, audio_path, label in audio_inputs:
                audio_upload_result = await self.client.upload_audio(audio_path)
                if not audio_upload_result.get("success"):
                    return {"success": False, "message": f"{label} 上传失败: {audio_upload_result.get('message')}"}
                uploaded_audio_filename = audio_upload_result.get("filename")
                audio_node_id = node_mapping.get(mapping_key)
                if audio_node_id and audio_node_id in workflow:
                    workflow[audio_node_id]["inputs"]["audio"] = uploaded_audio_filename
                    print(f"[ComfyUI] Set {label} to node {audio_node_id}")
                else:
                    return {"success": False, "message": f"工作流未配置有效的 {mapping_key}"}

            # 上传旧参考音频并注入工作流。仅在未使用 AudioDrive 双音轨时作为兼容路径。
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
            if keyframe_paths and frozen_image_inputs is None:
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

            # Audit only the fully prepared graph, after every media upload/injection.
            if frozen_image_inputs is not None:
                for binding in image_bindings:
                    if workflow.get(binding["node_id"], {}).get("inputs", {}).get("image") != binding["upload"]["filename"]:
                        raise VisualReferenceSubmissionError("VALIDATED_REFERENCE_GRAPH_CHANGED")
                bound = on_image_inputs_bound(image_bindings)
                if inspect.isawaitable(bound):
                    await bound
            h3_workflow = h3_workflow or is_h3_workflow(workflow)
            prepared_workflow_json = None
            if h3_workflow:
                if not callable(on_before_submit):
                    raise H3PromptSubmissionError("H3 submission requires on_before_submit(workflow)")
                if resolve_h3_consumed_prompt(workflow, node_mapping) != prompt:
                    raise H3PromptSubmissionError("H3 consumed prompt does not match the prompt argument")
                prepared_workflow_json = json.dumps(workflow, sort_keys=True)

            if on_before_submit is not None:
                callback_result = on_before_submit(workflow)
                if inspect.isawaitable(callback_result):
                    await callback_result

            # No graph edits or awaits between this final check and queue_prompt.
            if h3_workflow or is_h3_workflow(workflow):
                if resolve_h3_consumed_prompt(workflow, node_mapping) != prompt:
                    raise H3PromptSubmissionError("H3 consumed prompt does not match the prompt argument")
                if json.dumps(workflow, sort_keys=True) != prepared_workflow_json:
                    raise H3PromptSubmissionError("H3 workflow changed during on_before_submit")

            if any(workflow.get(item["node_id"], {}).get("inputs", {}).get(item["field"]) != item["upload"]["filename"]
                   for item in image_bindings):
                raise VisualReferenceSubmissionError("VALIDATED_REFERENCE_GRAPH_CHANGED")

            # 提交任务
            queue_result = await self.client.queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {"success": False, "message": queue_result.get("error", "提交任务失败")}
            
            prompt_id = queue_result.get("prompt_id")
            self._notify_prompt_queued(on_prompt_queued, prompt_id, workflow)
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
            
        except VisualReferenceSubmissionError as exc:
            return {"success": False, "failure_kind": "VISUAL_STATE_REFERENCE_REJECTED", "message": str(exc)}
        except H3PromptSubmissionError as exc:
            return {"success": False, "failure_kind": "H3_PROMPT_SUBMISSION_REJECTED", "message": str(exc)}
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
        duration_seconds: Optional[float] = None,
        frame_count: Optional[int] = None,
        on_prompt_queued=None
    ) -> Dict[str, Any]:
        """生成转场视频 (首帧+尾帧)"""
        try:
            import json
            workflow = json.loads(workflow_json)
            
            first_image_node_id = node_mapping.get("first_image_node_id", "98")
            last_image_node_id = node_mapping.get("last_image_node_id", "106")
            video_save_node_id = node_mapping.get("video_save_node_id", "105")
            frame_count_node_id = node_mapping.get("frame_count_node_id", "174")
            duration_seconds_node_id = node_mapping.get("duration_seconds_node_id", "")
            megapixels_node_id = node_mapping.get("megapixels_node_id", "")
            megapixels_value = node_mapping.get("megapixels_value", 0.4)
            
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
            
            # Megapixels 是转场工作流的可选尺寸控制节点。
            if megapixels_node_id:
                self.builder._set_value(workflow, megapixels_node_id, float(megapixels_value))

            # 时长秒数节点和总帧数节点由映射配置二选一。
            if duration_seconds and duration_seconds_node_id:
                self.builder._set_value(workflow, duration_seconds_node_id, duration_seconds)
            elif frame_count and frame_count_node_id:
                self.builder._set_value(workflow, frame_count_node_id, frame_count)
            
            # 设置随机种子
            import random
            self.builder._set_random_seed(workflow, random.randint(1, 2**32))
            
            # 提交任务
            queue_result = await self.client.queue_prompt(workflow)
            
            if not queue_result.get("success"):
                return {"success": False, "message": queue_result.get("error", "提交任务失败")}
            
            prompt_id = queue_result.get("prompt_id")
            self._notify_prompt_queued(on_prompt_queued, prompt_id, workflow)
            
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
