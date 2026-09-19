"""
ComfyUI HTTP 客户端

负责与 ComfyUI 服务的所有 HTTP 通信
"""
import json

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

    def _client(self) -> httpx.AsyncClient:
        # ComfyUI runs on the local network; bypass env proxies to avoid proxy 502s.
        return httpx.AsyncClient(trust_env=False)
    
    # ==================== 健康检查 ====================
    
    async def check_health(self) -> bool:
        """检查 ComfyUI 服务状态"""
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self.base_url}/system_stats",
                    timeout=5.0
                )
                return response.status_code == 200
        except Exception:
            return False
    
    # ==================== 文件上传 ====================
    
    async def upload_image(
        self,
        image_path: str,
        *,
        upload_name: Optional[str] = None,
        payload: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        上传图片到 ComfyUI

        Args:
            image_path: 本地图片路径
            upload_name: Opt-in ASCII basename; the caller supplies a unique name.
            payload: Frozen nonempty bytes; when supplied, no local path is accessed.

        Returns:
            {
                "success": bool,
                "filename": str,  # ComfyUI 中的文件名
                "message": str
            }

        Opt-in success also returns payload_sha256, payload_size, subfolder and
        type. The receipt must explicitly contain name, subfolder and type=input.
        Names and nonempty subfolder components must match
        [A-Za-z0-9_-]+(?:[.][A-Za-z0-9_-]+)*; subfolder uses relative '/' separators.
        filename is the server's name, prefixed with subfolder when nonempty.
        The hash proves the request payload, not the contents of remote storage.
        """
        if upload_name is None and payload is not None:
            from app.services.external_failure_diagnostic import ExternalFailureDiagnostic
            return {
                "success": False,
                "message": "payload requires upload_name",
                "external_failure": ExternalFailureDiagnostic.build(
                    operation_key={"operation": "UPLOAD_IMAGE", "reference_sha256": None,
                                   "reference_bytes": len(payload) if isinstance(payload, bytes) else None,
                                   "invocation_no": 1},
                    error_code="VALIDATED_REFERENCE_UPLOAD_FAILED", failure_class="VALIDATION",
                    stage="REFERENCE_UPLOAD", operation="UPLOAD_IMAGE", service="comfyui", provider="comfyui",
                    reference={"bytes": len(payload) if isinstance(payload, bytes) else None},
                    external_call={"method": "POST", "timeout_ms": 30000, "receipt_status": "NOT_ATTEMPTED"},
                    submission={"queue_called": False, "submitted": False, "state": "NOT_SUBMITTED",
                                "cid": None, "queue_seen": False, "remote_upload_effect": None},
                ),
            }

        if upload_name is not None:
            from datetime import datetime, timezone
            from time import monotonic
            from app.services.external_failure_diagnostic import (
                ExternalFailureDiagnostic, exception_evidence, response_body_evidence,
            )

            started_at = datetime.now(timezone.utc)
            started = monotonic()
            payload_sha256 = None
            payload_size = len(payload) if isinstance(payload, bytes) else None
            endpoint = None

            def failure(message, failure_class, *, error=None, response=None, receipt_status=None,
                        receipt_violation=None, include_excerpt=True):
                finished_at = datetime.now(timezone.utc)
                external_call = {
                    "endpoint": endpoint,
                    "method": "POST",
                    "timeout_ms": 30000,
                    "receipt_status": receipt_status,
                    "receipt_violation": receipt_violation,
                }
                if error is not None:
                    external_call.update({key: value for key, value in exception_evidence(error).items()
                                          if key != "truncated"})
                if response is not None:
                    external_call.update(response_body_evidence(
                        response.content, response.headers.get("content-type"), include_excerpt=include_excerpt,
                    ))
                    external_call["http_status"] = response.status_code
                diagnostic = ExternalFailureDiagnostic.build(
                    operation_key={"operation": "UPLOAD_IMAGE", "reference_sha256": payload_sha256,
                                   "reference_bytes": payload_size, "invocation_no": 1},
                    error_code="VALIDATED_REFERENCE_UPLOAD_FAILED", failure_class=failure_class,
                    stage="REFERENCE_UPLOAD", operation="UPLOAD_IMAGE", service="comfyui", provider="comfyui",
                    timing={
                        "started_at": started_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        "finished_at": finished_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        "elapsed_ms": max(0, int((monotonic() - started) * 1000)),
                    },
                    reference={"filename": upload_name if isinstance(upload_name, str) else None,
                               "bytes": payload_size, "sha256": payload_sha256},
                    external_call=external_call,
                    submission={"queue_called": False, "submitted": False, "state": "NOT_SUBMITTED",
                                "cid": None, "queue_seen": False, "remote_upload_effect": "UNKNOWN"},
                )
                return {"success": False, "message": message, "external_failure": diagnostic}

            try:
                import hashlib
                import os
                import re

                component = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
                if not isinstance(upload_name, str) or not component.fullmatch(upload_name):
                    return failure("Invalid upload_name: expected a safe ASCII basename", "VALIDATION",
                                   receipt_status="NOT_ATTEMPTED")

                if payload is None:
                    if not os.path.isfile(image_path):
                        return failure(f"Image path is not a local file: {image_path}", "VALIDATION",
                                       receipt_status="NOT_ATTEMPTED")
                    try:
                        with open(image_path, "rb") as f:
                            payload = f.read()
                    except OSError as error:
                        return failure(f"Image upload failed: {str(error)}", "VALIDATION", error=error,
                                       receipt_status="NOT_ATTEMPTED")

                if not isinstance(payload, bytes) or not payload:
                    return failure("payload must be nonempty bytes", "VALIDATION", receipt_status="NOT_ATTEMPTED")

                payload_sha256 = hashlib.sha256(payload).hexdigest()
                payload_size = len(payload)
                endpoint = f"{self.base_url}/upload/image"
                async with self._client() as client:
                    response = await client.post(
                        endpoint,
                        files={"image": (upload_name, payload, "image/png")},
                        data={"type": "input", "overwrite": "true"},
                        timeout=30.0,
                    )

                if response.status_code != 200:
                    return failure(f"Image upload failed (HTTP {response.status_code})", "HTTP_ERROR",
                                   response=response, receipt_status="HTTP_ERROR")

                try:
                    result = response.json()
                except (ValueError, UnicodeDecodeError, RecursionError) as error:
                    return failure(f"Image upload failed: {str(error)}", "INVALID_RESPONSE", error=error,
                                   response=response, receipt_status="INVALID_RESPONSE")
                if not isinstance(result, dict):
                    return failure("Invalid image upload receipt: expected an object", "INVALID_RESPONSE",
                                   response=response, receipt_status="INVALID_RESPONSE")

                name = result.get("name")
                if not isinstance(name, str) or not component.fullmatch(name):
                    return failure("Invalid image upload receipt: unsafe or missing name", "INVALID_RECEIPT",
                                    response=response, receipt_status="INVALID",
                                    receipt_violation="IMAGE_RECEIPT_NAME_MISSING_OR_UNSAFE")
                if result.get("type") != "input":
                    return failure("Invalid image upload receipt: type must be input", "INVALID_RECEIPT",
                                    response=response, receipt_status="INVALID",
                                    receipt_violation="IMAGE_RECEIPT_TYPE_NOT_INPUT")
                subfolder = result.get("subfolder")
                if not isinstance(subfolder, str) or (
                    subfolder and any(not component.fullmatch(part) for part in subfolder.split("/"))
                ):
                    return failure("Invalid image upload receipt: unsafe or missing subfolder", "INVALID_RECEIPT",
                                    response=response, receipt_status="INVALID",
                                    receipt_violation="IMAGE_RECEIPT_SUBFOLDER_MISSING_OR_UNSAFE")

                return {
                    "success": True,
                    "filename": f"{subfolder}/{name}" if subfolder else name,
                    "subfolder": subfolder,
                    "type": "input",
                    "payload_sha256": payload_sha256,
                    "payload_size": len(payload),
                    "message": "上传成功",
                }
            except Exception as e:
                failure_class = "INVALID_RESPONSE" if isinstance(e, httpx.DecodingError) else (
                    "TIMEOUT" if isinstance(e, (TimeoutError, httpx.TimeoutException)) else (
                        "CONNECTION" if isinstance(e, (httpx.TransportError, ConnectionError)) else "UNKNOWN"
                    )
                )
                return failure(f"Image upload failed: {str(e)}", failure_class, error=e,
                               receipt_status="NOT_RECEIVED")

        try:
            import os
            from pathlib import Path

            if not os.path.exists(image_path):
                return {
                    "success": False,
                    "message": f"图片文件不存在: {image_path}"
                }

            filename = os.path.basename(image_path)

            async with self._client() as client:
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

    async def upload_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        上传音频到 ComfyUI

        Args:
            audio_path: 本地音频文件路径

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

            if not os.path.exists(audio_path):
                return {
                    "success": False,
                    "message": f"音频文件不存在: {audio_path}"
                }

            filename = os.path.basename(audio_path)

            # 根据文件扩展名确定 MIME 类型
            ext = os.path.splitext(filename)[1].lower()
            mime_types = {
                '.flac': 'audio/flac',
                '.wav': 'audio/wav',
                '.mp3': 'audio/mpeg',
                '.ogg': 'audio/ogg',
                '.m4a': 'audio/mp4',
                '.aac': 'audio/aac'
            }
            mime_type = mime_types.get(ext, 'audio/flac')

            async with self._client() as client:
                with open(audio_path, 'rb') as f:
                    # ComfyUI 使用 /upload/image 端点上传所有文件类型
                    files = {'image': (filename, f, mime_type)}
                    data = {'type': 'input', 'overwrite': 'true'}

                    response = await client.post(
                        f"{self.base_url}/upload/image",
                        files=files,
                        data=data,
                        timeout=60.0
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
                        "message": f"上传失败: {response.status_code}: {response.text}"
                    }

        except Exception as e:
            return {
                "success": False,
                "message": f"上传音频失败: {str(e)}"
            }
    
    # ==================== 任务提交 ====================
    
    async def queue_prompt(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """提交任务到 ComfyUI"""
        try:
            async with self._client() as client:
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
        print(f"ComfyUI Waiting for result: prompt_id={prompt_id}, workflow_json:\n{json.dumps(workflow, indent=2, ensure_ascii=True)}")
        start_time = asyncio.get_event_loop().time()
        missing_from_queue_since = None

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                return {
                    "success": False,
                    "message": f"任务超时 ({timeout}s)"
                }

            try:
                async with self._client() as client:
                    response = await client.get(
                        f"{self.base_url}/history/{prompt_id}",
                        timeout=10.0
                    )

                    if response.status_code == 200:
                        history = response.json()

                        if prompt_id in history:
                            missing_from_queue_since = None
                            prompt_history = history[prompt_id]
                            outputs = prompt_history.get("outputs", {})
                            status = prompt_history.get("status", {})

                            if outputs:
                                result = self._parse_outputs(
                                    outputs, workflow, save_image_node_id
                                )
                                if result:
                                    return result

                                if self._is_completed_status(status):
                                    return {
                                        "success": False,
                                        "message": "ComfyUI 任务已完成，但未找到可保存的图片或视频输出。请检查保存节点映射和工作流输出。"
                                    }

                            # 检查是否有错误
                            if status.get("status_str") == "error":
                                error_msg = "未知错误"
                                messages = status.get("messages")
                                if messages and len(messages) > 0:
                                    msg_item = messages[0]
                                    if isinstance(msg_item, (list, tuple)) and len(msg_item) > 1:
                                        error_msg = str(msg_item[1])
                                    else:
                                        error_msg = str(msg_item)
                                return {
                                    "success": False,
                                    "message": error_msg
                                }

                            if self._is_completed_status(status):
                                return {
                                    "success": False,
                                    "message": "ComfyUI 任务已完成，但 history 中没有输出结果。请检查工作流保存节点。"
                                }
                        else:
                            queue_info = await self.get_queue_info()
                            if self._queue_contains_prompt(queue_info, prompt_id):
                                missing_from_queue_since = None
                            else:
                                if missing_from_queue_since is None:
                                    missing_from_queue_since = elapsed
                                elif elapsed - missing_from_queue_since >= 30:
                                    return {
                                        "success": False,
                                        "message": "ComfyUI 中已找不到该任务，且未产生 history 结果。任务可能被清理、取消或 ComfyUI 异常退出。"
                                    }

                    await asyncio.sleep(poll_interval)

            except Exception as e:
                print(f"Wait for result error: {e}")
                await asyncio.sleep(poll_interval)

    async def wait_for_audio_result(
        self,
        prompt_id: str,
        workflow: Dict[str, Any] = None,
        save_audio_node_id: str = None,
        timeout: int = 600,
        poll_interval: float = 2.0
    ) -> Dict[str, Any]:
        """等待音频任务完成并获取结果

        Args:
            prompt_id: ComfyUI 任务 ID
            workflow: 提交的工作流
            save_audio_node_id: 配置的 SaveAudio 节点 ID
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）
        """
        start_time = asyncio.get_event_loop().time()
        missing_from_queue_since = None

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                return {
                    "success": False,
                    "message": f"任务超时 ({timeout}s)"
                }

            try:
                async with self._client() as client:
                    response = await client.get(
                        f"{self.base_url}/history/{prompt_id}",
                        timeout=10.0
                    )

                    if response.status_code == 200:
                        history = response.json()

                        if prompt_id in history:
                            missing_from_queue_since = None
                            prompt_history = history[prompt_id]
                            outputs = prompt_history.get("outputs", {})
                            status = prompt_history.get("status", {})

                            if outputs and self._is_completed_status(status):
                                result = self._parse_audio_outputs(
                                    outputs, workflow, save_audio_node_id
                                )
                                if result:
                                    return {**result,"prompt_id":prompt_id,"history":prompt_history,"status":status}

                                if self._is_completed_status(status):
                                    return {
                                        "success": False,
                                        "message": "ComfyUI 音频任务已完成，但未找到可保存的音频输出。请检查保存节点映射和工作流输出。"
                                    }

                            # 检查是否有错误
                            if status.get("status_str") == "error":
                                error_msg = "未知错误"
                                messages = status.get("messages")
                                if messages and len(messages) > 0:
                                    msg_item = messages[0]
                                    if isinstance(msg_item, (list, tuple)) and len(msg_item) > 1:
                                        error_msg = str(msg_item[1])
                                    else:
                                        error_msg = str(msg_item)
                                return {
                                    "success": False,
                                    "message": error_msg
                                }

                            if self._is_completed_status(status):
                                return {
                                    "success": False,
                                    "message": "ComfyUI 音频任务已完成，但 history 中没有输出结果。请检查工作流保存节点。"
                                }
                        else:
                            queue_info = await self.get_queue_info()
                            if self._queue_contains_prompt(queue_info, prompt_id):
                                missing_from_queue_since = None
                            else:
                                if missing_from_queue_since is None:
                                    missing_from_queue_since = elapsed
                                elif elapsed - missing_from_queue_since >= 30:
                                    return {
                                        "success": False,
                                        "message": "ComfyUI 中已找不到该音频任务，且未产生 history 结果。任务可能被清理、取消或 ComfyUI 异常退出。"
                                    }

                    await asyncio.sleep(poll_interval)

            except Exception as e:
                print(f"Wait for audio result error: {e}")
                await asyncio.sleep(poll_interval)
    
    def _parse_outputs(
        self,
        outputs: Dict[str, Any],
        workflow: Dict[str, Any] = None,
        save_image_node_id: str = None
    ) -> Optional[Dict[str, Any]]:
        """解析 ComfyUI 输出结果"""
        def build_media_url(media_info: Dict[str, Any]) -> str:
            filename = media_info.get("filename")
            subfolder = media_info.get("subfolder", "")
            media_type = media_info.get("type", "output")

            params = f"filename={filename}"
            if subfolder:
                params += f"&subfolder={subfolder}"
            params += f"&type={media_type}"
            return f"{self.base_url}/view?{params}"

        def is_video_filename(filename: str) -> bool:
            return str(filename or "").lower().split("?")[0].endswith((".mp4", ".webm", ".mov", ".mkv"))

        # 查找工作流中的所有 SaveImage 节点
        saveimage_nodes = set()
        if workflow:
            for node_id, node in workflow.items():
                if isinstance(node, dict) and node.get("class_type") == "SaveImage":
                    saveimage_nodes.add(str(node_id))
            print(f"[ComfyUI] SaveImage nodes in workflow: {saveimage_nodes}")
        
        # 优先使用配置的保存节点。视频工作流可能同时有高清/低清 SaveVideo，遍历第一个会取错。
        if save_image_node_id:
            configured_output = outputs.get(str(save_image_node_id))
            if configured_output:
                for output_key, label in (("videos", "SaveVideo"), ("gifs", "VHS_VideoCombine")):
                    videos = configured_output.get(output_key)
                    if videos:
                        video_url = build_media_url(videos[0])
                        print(f"[ComfyUI] Found configured video ({label}) from node {save_image_node_id}: {video_url}")
                        return {
                            "success": True,
                            "video_url": video_url,
                            "message": "生成成功"
                        }
                images = configured_output.get("images")
                if images and is_video_filename(images[0].get("filename", "")):
                    video_url = build_media_url(images[0])
                    print(f"[ComfyUI] Found configured video file from images output node {save_image_node_id}: {video_url}")
                    return {
                        "success": True,
                        "video_url": video_url,
                        "message": "生成成功"
                    }

        # 优先检查视频输出（VHS_VideoCombine 输出 gifs，SaveVideo 输出 videos）
        for node_id, node_output in outputs.items():
            # 检查 videos 输出（SaveVideo 节点）
            if "videos" in node_output:
                videos = node_output["videos"]
                if videos:
                    video_url = build_media_url(videos[0])
                    print(f"[ComfyUI] Found video (SaveVideo) from node {node_id}: {video_url}")

                    return {
                        "success": True,
                        "video_url": video_url,
                        "message": "生成成功"
                    }

            # 检查 gifs 输出（VHS_VideoCombine 节点）
            if "gifs" in node_output:
                videos = node_output["gifs"]
                if videos:
                    video_url = build_media_url(videos[0])
                    print(f"[ComfyUI] Found video (VHS_VideoCombine) from node {node_id}: {video_url}")

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
                    if is_video_filename(filename):
                        video_url = build_media_url(img_info)
                        print(f"[ComfyUI] Found video file from images output node {node_id}: {video_url}")
                        return {
                            "success": True,
                            "video_url": video_url,
                            "message": "生成成功"
                        }

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

    def _is_completed_status(self, status: Dict[str, Any]) -> bool:
        """判断 ComfyUI history 状态是否已经结束。"""
        return bool(status.get("completed")) or status.get("status_str") in {"success", "completed"}

    def _extract_status_error(self, status: Dict[str, Any]) -> str:
        """提取 ComfyUI history status 中的错误信息。"""
        messages = status.get("messages")
        if messages and len(messages) > 0:
            msg_item = messages[0]
            if isinstance(msg_item, (list, tuple)) and len(msg_item) > 1:
                return str(msg_item[1])
            return str(msg_item)
        return "未知错误"

    def _queue_contains_prompt(self, queue_info: Dict[str, Any], prompt_id: str) -> bool:
        """ComfyUI queue item 结构随版本变化，递归查找 prompt_id 更稳妥。"""
        def contains(value: Any) -> bool:
            if isinstance(value, str):
                return value == prompt_id
            if isinstance(value, dict):
                return any(contains(v) for v in value.values())
            if isinstance(value, (list, tuple)):
                return any(contains(v) for v in value)
            return False

        return contains(queue_info.get("queue_running", [])) or contains(queue_info.get("queue_pending", []))

    def _parse_audio_outputs(
        self,
        outputs: Dict[str, Any],
        workflow: Dict[str, Any] = None,
        save_audio_node_id: str = None
    ) -> Optional[Dict[str, Any]]:
        """解析 ComfyUI 音频输出结果"""
        # 查找工作流中的所有音频输出节点（SaveAudio 和 PreviewAudio）
        audio_output_nodes = set()
        if workflow:
            for node_id, node in workflow.items():
                if isinstance(node, dict) and node.get("class_type") in ("SaveAudio", "PreviewAudio"):
                    audio_output_nodes.add(str(node_id))
            print(f"[ComfyUI] Audio output nodes in workflow: {audio_output_nodes}")

        # 查找音频输出
        best_audio = None
        best_node_id = None

        for node_id, node_output in outputs.items():
            if "audio" in node_output:
                audio_info = node_output["audio"]
                if audio_info:
                    audio_data = audio_info[0] if isinstance(audio_info, list) else audio_info
                    filename = audio_data.get("filename", "")

                    node_id_str = str(node_id)

                    # 如果配置了 save_audio_node_id，优先匹配该节点
                    if save_audio_node_id:
                        if node_id_str == str(save_audio_node_id):
                            best_audio = audio_data
                            best_node_id = node_id
                            print(f"[ComfyUI] Found configured audio node {node_id} output: {filename}")
                            break
                    elif node_id_str in audio_output_nodes:
                        best_audio = audio_data
                        best_node_id = node_id
                        print(f"[ComfyUI] Found audio output node {node_id} output: {filename}")
                        break

                    if best_audio is None and not save_audio_node_id:
                        best_audio = audio_data
                        best_node_id = node_id

        if best_audio:
            filename = best_audio.get("filename")
            subfolder = best_audio.get("subfolder", "")
            audio_type = best_audio.get("type", "output")

            params = f"filename={filename}"
            if subfolder:
                params += f"&subfolder={subfolder}"
            params += f"&type={audio_type}"

            audio_url = f"{self.base_url}/view?{params}"
            print(f"[ComfyUI] Selected audio from node {best_node_id}: {audio_url}")

            return {
                "success": True,
                "audio_url": audio_url,
                "output_node_id": str(best_node_id),
                "output": best_audio,
                "message": "生成成功"
            }

        return None

    # ==================== 队列管理 ====================
    
    async def get_queue_info(self) -> Dict[str, Any]:
        """获取 ComfyUI 队列信息"""
        try:
            async with self._client() as client:
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

    async def discover_prompt_by_client_id(self, client_id: str, *, max_history: int = 200) -> Dict[str, Any]:
        """Strictly discover one existing prompt without creating or cancelling remote work."""
        if not isinstance(client_id, str) or not client_id.strip():
            return {"state": "unknown", "message": "invalid client_id"}
        try:
            async with self._client() as client:
                queue_response, history_response = await asyncio.gather(
                    client.get(f"{self.base_url}/queue", timeout=10.0),
                    client.get(f"{self.base_url}/history", params={"max_items": max_history}, timeout=30.0),
                )
            if queue_response.status_code != 200 or history_response.status_code != 200:
                return {"state": "unknown", "message": (
                    f"queue HTTP {queue_response.status_code}; history HTTP {history_response.status_code}"
                )}
            queue, histories = queue_response.json(), history_response.json()
            if not isinstance(queue, dict) or not isinstance(histories, dict):
                return {"state": "unknown", "message": "malformed queue/history response"}
            candidates = {}

            def add_prompt(prompt_id, graph, extra, location, history=None):
                if not isinstance(extra, dict) or extra.get("client_id") != client_id:
                    return
                if not isinstance(prompt_id, str) or not prompt_id or not isinstance(graph, dict):
                    raise ValueError("malformed correlated prompt")
                current = candidates.setdefault(prompt_id, {"prompt_id": prompt_id, "graph": graph,
                    "locations": [], "history": None, "client_id": client_id})
                if current["graph"] != graph:
                    raise ValueError("conflicting graph for correlated prompt")
                current["locations"].append(location)
                if history is not None:
                    if current["history"] is not None and current["history"] != history:
                        raise ValueError("conflicting history for correlated prompt")
                    current["history"] = history

            for location, key in (("running", "queue_running"), ("pending", "queue_pending")):
                rows = queue.get(key) or []
                if not isinstance(rows, list):
                    raise ValueError("malformed queue rows")
                for row in rows:
                    if isinstance(row, list) and len(row) >= 4:
                        add_prompt(row[1], row[2], row[3], location)
            for prompt_id, history in histories.items():
                prompt = history.get("prompt") if isinstance(history, dict) else None
                if isinstance(prompt, list) and len(prompt) >= 4:
                    if prompt[1] != prompt_id:
                        raise ValueError("history prompt identity mismatch")
                    add_prompt(prompt_id, prompt[2], prompt[3], "history", history)
            values = list(candidates.values())
            if not values:
                return {"state": "missing"}
            if len(values) != 1:
                return {"state": "ambiguous", "prompt_ids": sorted(candidates)}
            return {"state": "found", **values[0]}
        except Exception as exc:
            return {"state": "unknown", "message": str(exc)}

    async def get_prompt_state(self, prompt_id: str, queue_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """查询 prompt 当前在 ComfyUI 的状态。"""
        queue_info = queue_info if queue_info is not None else await self.get_queue_info()
        if self._queue_contains_prompt(queue_info, prompt_id):
            return {"state": "queued"}

        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self.base_url}/history/{prompt_id}",
                    timeout=10.0
                )
            if response.status_code != 200:
                return {"state": "unknown", "message": f"history HTTP {response.status_code}"}

            history = response.json()
            prompt_history = history.get(prompt_id)
            if not prompt_history:
                return {"state": "missing"}

            status = prompt_history.get("status", {})
            if status.get("status_str") == "error":
                return {"state": "error", "message": self._extract_status_error(status)}
            if self._is_completed_status(status):
                return {"state": "completed", "history": prompt_history}
            return {"state": "history", "history": prompt_history}
        except Exception as e:
            return {"state": "unknown", "message": str(e)}
    
    async def clear_queue(self, max_retries: int = 3) -> Dict[str, Any]:
        """清空 ComfyUI 队列中的所有等待任务"""
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                async with self._client() as client:
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
            async with self._client() as client:
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
                async with self._client() as client:
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
